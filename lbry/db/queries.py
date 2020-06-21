# pylint: disable=singleton-comparison
import struct
import logging
import itertools
from datetime import date
from decimal import Decimal
from binascii import unhexlify
from operator import itemgetter
from typing import Tuple, List, Dict, Optional, Union

from sqlalchemy import union, func, text
from sqlalchemy.future import select, Select

from lbry.schema.tags import clean_tags
from lbry.schema.result import Censor, Outputs
from lbry.schema.url import URL, normalize_name
from lbry.error import ResolveCensoredError
from lbry.blockchain.transaction import Transaction, Output, OutputScript, TXRefImmutable

from .utils import query, in_account_ids
from .query_context import context
from .constants import (
    TXO_TYPES, CLAIM_TYPE_CODES, STREAM_TYPES, ATTRIBUTE_ARRAY_MAX_LENGTH,
    SEARCH_INTEGER_PARAMS, SEARCH_ORDER_FIELDS
)
from .tables import (
    metadata,
    SCHEMA_VERSION, Version,
    Block, TX, TXO, TXI, txi_join_account, txo_join_account,
    Claim, Support, Takeover,
    PubkeyAddress, AccountAddress
)


MAX_QUERY_VARIABLES = 900


log = logging.getLogger(__name__)


def check_version_and_create_tables():
    with context("db.connecting") as ctx:
        if ctx.is_sqlite:
            ctx.execute(text("PRAGMA journal_mode=WAL;"))
        if ctx.has_table('version'):
            version = ctx.fetchone(select(Version.c.version).limit(1))
            if version and version['version'] == SCHEMA_VERSION:
                return
        metadata.drop_all(ctx.engine)
        metadata.create_all(ctx.engine)
        ctx.execute(Version.insert().values(version=SCHEMA_VERSION))
        if ctx.is_postgres:
            ctx.execute(text("ALTER TABLE txi DISABLE TRIGGER ALL;"))
            ctx.execute(text("ALTER TABLE txo DISABLE TRIGGER ALL;"))
            ctx.execute(text("ALTER TABLE tx DISABLE TRIGGER ALL;"))
            ctx.execute(text("ALTER TABLE claim DISABLE TRIGGER ALL;"))
            ctx.execute(text("ALTER TABLE claimtrie DISABLE TRIGGER ALL;"))
            ctx.execute(text("ALTER TABLE block DISABLE TRIGGER ALL;"))


def insert_block(block):
    context().get_bulk_loader().add_block(block).save()


def insert_transaction(block_hash, tx):
    context().get_bulk_loader().add_transaction(block_hash, tx).save()


def execute(sql):
    return context().execute(text(sql))


def execute_fetchall(sql):
    return context().fetchall(text(sql))


def get_best_tx_height():
    return context().fetchone(
        select(func.coalesce(func.max(TX.c.height), -1).label('height')).select_from(TX)
    )['height']


def get_best_block_height_for_file(file_number):
    return context().fetchone(
        select(func.coalesce(func.max(Block.c.height), -1).label('height'))
        .select_from(Block)
        .where(Block.c.file_number == file_number)
    )['height']


def get_blocks_without_filters():
    return context().fetchall(
        select(Block.c.block_hash)
        .select_from(Block)
        .where(Block.c.block_filter == None)
    )


def get_transactions_without_filters():
    return context().fetchall(
        select(TX.c.tx_hash)
        .select_from(TX)
        .where(TX.c.tx_filter == None)
    )


def get_block_tx_addresses(block_hash=None, tx_hash=None):
    if block_hash is not None:
        constraint = (TX.c.block_hash == block_hash)
    elif tx_hash is not None:
        constraint = (TX.c.tx_hash == tx_hash)
    else:
        raise ValueError('block_hash or tx_hash must be provided.')
    return context().fetchall(
        union(
            select(TXO.c.address).select_from(TXO.join(TX)).where((TXO.c.address != None) & constraint),
            select(TXI.c.address).select_from(TXI.join(TX)).where((TXI.c.address != None) & constraint),
        )
    )


def get_block_address_filters():
    return context().fetchall(
        select(Block.c.block_hash, Block.c.block_filter).select_from(Block)
    )


def get_transaction_address_filters(block_hash):
    return context().fetchall(
        select(TX.c.tx_hash, TX.c.tx_filter)
        .select_from(TX)
        .where(TX.c.block_hash == block_hash)
    )


def update_address_used_times(addresses):
    context().execute(
        PubkeyAddress.update()
        .values(used_times=(
            select(func.count(TXO.c.address)).where((TXO.c.address == PubkeyAddress.c.address)),
        ))
        .where(PubkeyAddress.c.address._in(addresses))
    )


def reserve_outputs(txo_hashes, is_reserved=True):
    context().execute(
        TXO.update().values(is_reserved=is_reserved).where(TXO.c.txo_hash.in_(txo_hashes))
    )


def release_all_outputs(account_id):
    context().execute(
        TXO.update().values(is_reserved=False).where(
            (TXO.c.is_reserved == True) &
            (TXO.c.address.in_(select(AccountAddress.c.address).where(in_account_ids(account_id))))
        )
    )


def get_takeover_names(above_height, limit_height, offset, limit):
    return context().fetchall(
        select(
            Takeover.c.normalized.label('_name'),
            func.max(Takeover.c.height).label('_height'),

        )
        .where((Takeover.c.height < above_height) & (Takeover.c.height >= limit_height))
        .group_by(Takeover.c.normalized)
        .limit(limit).offset(offset)
    )


def get_takeovers(above_height, limit_height, offset, limit):
    return context().fetchall(
        select(
            Takeover.c.normalized,
            Takeover.c.claim_hash,
            Takeover.c.height,
        )
        .select_from(Takeover)
        .where((Takeover.c.height < above_height) & (Takeover.c.height >= limit_height))
        .group_by(Takeover.c.normalized)
        .limit(limit).offset(offset)
    )


def select_transactions(cols, account_ids=None, **constraints):
    s: Select = select(*cols).select_from(TX)
    if not {'tx_hash', 'tx_hash__in'}.intersection(constraints):
        assert account_ids, "'accounts' argument required when no 'tx_hash' constraint is present"
        where = in_account_ids(account_ids)
        tx_hashes = union(
            select(TXO.c.tx_hash).select_from(txo_join_account).where(where),
            select(TXI.c.tx_hash).select_from(txi_join_account).where(where)
        )
        s = s.where(TX.c.tx_hash.in_(tx_hashes))
    return context().fetchall(query([TX], s, **constraints))


TXO_NOT_MINE = Output(None, None, is_my_output=False)


def get_raw_transactions(tx_hashes):
    return context().fetchall(
        select(TX.c.tx_hash, TX.c.raw).where(TX.c.tx_hash.in_(tx_hashes))
    )


def get_transactions(**constraints) -> Tuple[List[Transaction], Optional[int]]:
    txs = []
    sql = select(TX.c.raw, TX.c.height, TX.c.position).select_from(TX)
    rows = context().fetchall(query([TX], sql, **constraints))
    for row in rows:
        txs.append(Transaction(row['raw'], height=row['height'], position=row['position']))
    return txs, 0


def _get_transactions(wallet=None, include_total=False, **constraints) -> Tuple[List[Transaction], Optional[int]]:
    include_is_spent = constraints.pop('include_is_spent', False)
    include_is_my_input = constraints.pop('include_is_my_input', False)
    include_is_my_output = constraints.pop('include_is_my_output', False)

    tx_rows = select_transactions(
        [TX.c.tx_hash, TX.c.raw, TX.c.height, TX.c.position, TX.c.is_verified],
        order_by=constraints.pop('order_by', ["height=0 DESC", "height DESC", "position DESC"]),
        **constraints
    )

    txids, txs, txi_txoids = [], [], []
    for row in tx_rows:
        txids.append(row['tx_hash'])
        txs.append(Transaction(
            raw=row['raw'], height=row['height'], position=row['position'],
            is_verified=bool(row['is_verified'])
        ))
        for txi in txs[-1].inputs:
            txi_txoids.append(txi.txo_ref.hash)

    annotated_txos = {}
    for offset in range(0, len(txids), MAX_QUERY_VARIABLES):
        annotated_txos.update({
            txo.id: txo for txo in
            get_txos(
                wallet=wallet,
                tx_hash__in=txids[offset:offset + MAX_QUERY_VARIABLES], order_by='txo.tx_hash',
                include_is_spent=include_is_spent,
                include_is_my_input=include_is_my_input,
                include_is_my_output=include_is_my_output,
            )[0]
        })

    referenced_txos = {}
    for offset in range(0, len(txi_txoids), MAX_QUERY_VARIABLES):
        referenced_txos.update({
            txo.id: txo for txo in
            get_txos(
                wallet=wallet,
                txo_hash__in=txi_txoids[offset:offset + MAX_QUERY_VARIABLES], order_by='txo.txo_hash',
                include_is_my_output=include_is_my_output,
            )[0]
        })

    for tx in txs:
        for txi in tx.inputs:
            txo = referenced_txos.get(txi.txo_ref.id)
            if txo:
                txi.txo_ref = txo.ref
        for txo in tx.outputs:
            _txo = annotated_txos.get(txo.id)
            if _txo:
                txo.update_annotations(_txo)
            else:
                txo.update_annotations(TXO_NOT_MINE)

    for tx in txs:
        txos = tx.outputs
        if len(txos) >= 2 and txos[1].can_decode_purchase_data:
            txos[0].purchase = txos[1]

    return txs, get_transaction_count(**constraints) if include_total else None


def get_transaction_count(**constraints):
    constraints.pop('wallet', None)
    constraints.pop('offset', None)
    constraints.pop('limit', None)
    constraints.pop('order_by', None)
    count = select_transactions([func.count().label('total')], **constraints)
    return count[0]['total'] or 0


BASE_SELECT_TXO_COLUMNS = [
    TX.c.tx_hash, TX.c.raw, TX.c.height, TX.c.position.label('tx_position'),
    TX.c.is_verified, TX.c.timestamp,
    TXO.c.txo_type, TXO.c.position.label('txo_position'), TXO.c.amount, TXO.c.is_spent,
    TXO.c.script_offset, TXO.c.script_length,
]


def select_txos(
        cols=None, account_ids=None, is_my_input=None,
        is_my_output=True, is_my_input_or_output=None, exclude_internal_transfers=False,
        include_is_my_input=False, claim_id_not_in_claim_table=None,
        txo_id_not_in_claim_table=None, txo_id_not_in_support_table=None,
        **constraints) -> Select:
    if cols is None:
        cols = BASE_SELECT_TXO_COLUMNS
    s: Select = select(*cols)
    if account_ids:
        my_addresses = select(AccountAddress.c.address).where(in_account_ids(account_ids))
        if is_my_input_or_output:
            include_is_my_input = True
            s = s.where(
                TXO.c.address.in_(my_addresses) | (
                    (TXI.c.address != None) &
                    (TXI.c.address.in_(my_addresses))
                )
            )
        else:
            if is_my_output:
                s = s.where(TXO.c.address.in_(my_addresses))
            elif is_my_output is False:
                s = s.where(TXO.c.address.notin_(my_addresses))
            if is_my_input:
                include_is_my_input = True
                s = s.where(
                    (TXI.c.address != None) &
                    (TXI.c.address.in_(my_addresses))
                )
            elif is_my_input is False:
                include_is_my_input = True
                s = s.where(
                    (TXI.c.address == None) |
                    (TXI.c.address.notin_(my_addresses))
                )
        if exclude_internal_transfers:
            include_is_my_input = True
            s = s.where(
                (TXO.c.txo_type != TXO_TYPES['other']) |
                (TXO.c.address.notin_(my_addresses))
                (TXI.c.address == None) |
                (TXI.c.address.notin_(my_addresses))
            )
    joins = TXO.join(TX)
    if constraints.get('is_spent', None) is False:
        s = s.where((TXO.c.is_spent == False) & (TXO.c.is_reserved == False))
    if include_is_my_input:
        joins = joins.join(TXI, (TXI.c.position == 0) & (TXI.c.tx_hash == TXO.c.tx_hash), isouter=True)
    if claim_id_not_in_claim_table:
        s = s.where(TXO.c.claim_hash.notin_(select(Claim.c.claim_hash)))
    elif txo_id_not_in_claim_table:
        s = s.where(TXO.c.txo_hash.notin_(select(Claim.c.txo_hash)))
    elif txo_id_not_in_support_table:
        s = s.where(TXO.c.txo_hash.notin_(select(Support.c.txo_hash)))
    return query([TXO, TX], s.select_from(joins), **constraints)


META_ATTRS = (
    'activation_height', 'takeover_height', 'creation_height', 'staked_amount',
    'short_url', 'canonical_url', 'staked_support_amount', 'staked_support_count',
    'signed_claim_count', 'signed_support_count', 'is_signature_valid',
)


def rows_to_txos(rows: List[dict], include_tx=True) -> List[Output]:
    txos = []
    tx_cache = {}
    for row in rows:
        if include_tx:
            if row['tx_hash'] not in tx_cache:
                tx_cache[row['tx_hash']] = Transaction(
                    row['raw'], height=row['height'], position=row['tx_position'],
                    is_verified=bool(row['is_verified']),
                )
            txo = tx_cache[row['tx_hash']].outputs[row['txo_position']]
        else:
            source = row['raw'][row['script_offset']:row['script_offset']+row['script_length']]
            txo = Output(
                amount=row['amount'],
                script=OutputScript(source),
                tx_ref=TXRefImmutable.from_hash(row['tx_hash'], row['height']),
                position=row['txo_position'],
            )
        txo.is_spent = bool(row['is_spent'])
        if 'is_my_input' in row:
            txo.is_my_input = bool(row['is_my_input'])
        if 'is_my_output' in row:
            txo.is_my_output = bool(row['is_my_output'])
        if 'is_my_input' in row and 'is_my_output' in row:
            if txo.is_my_input and txo.is_my_output and row['txo_type'] == TXO_TYPES['other']:
                txo.is_internal_transfer = True
            else:
                txo.is_internal_transfer = False
        if 'received_tips' in row:
            txo.received_tips = row['received_tips']
        for attr in META_ATTRS:
            if attr in row:
                txo.meta[attr] = row[attr]
        txos.append(txo)
    return txos


def get_txos(no_tx=False, include_total=False, **constraints) -> Tuple[List[Output], Optional[int]]:
    wallet_account_ids = constraints.pop('wallet_account_ids', [])
    include_is_spent = constraints.get('include_is_spent', False)
    include_is_my_input = constraints.get('include_is_my_input', False)
    include_is_my_output = constraints.pop('include_is_my_output', False)
    include_received_tips = constraints.pop('include_received_tips', False)

    select_columns = BASE_SELECT_TXO_COLUMNS + [
        TXO.c.claim_name
    ]

    my_accounts = None
    if wallet_account_ids:
        my_accounts = select(AccountAddress.c.address).where(in_account_ids(wallet_account_ids))

    if include_is_my_output and my_accounts is not None:
        if constraints.get('is_my_output', None) in (True, False):
            select_columns.append(text(f"{1 if constraints['is_my_output'] else 0} AS is_my_output"))
        else:
            select_columns.append(TXO.c.address.in_(my_accounts).label('is_my_output'))

    if include_is_my_input and my_accounts is not None:
        if constraints.get('is_my_input', None) in (True, False):
            select_columns.append(text(f"{1 if constraints['is_my_input'] else 0} AS is_my_input"))
        else:
            select_columns.append((
                (TXI.c.address != None) &
                (TXI.c.address.in_(my_accounts))
            ).label('is_my_input'))

    if include_received_tips:
        support = TXO.alias('support')
        select_columns.append(
            select(func.coalesce(func.sum(support.c.amount), 0))
            .select_from(support).where(
                (support.c.claim_hash == TXO.c.claim_hash) &
                (support.c.txo_type == TXO_TYPES['support']) &
                (support.c.address.in_(my_accounts)) &
                (support.c.txo_hash.notin_(select(TXI.c.txo_hash)))
            ).label('received_tips')
        )

    if 'order_by' not in constraints or constraints['order_by'] == 'height':
        constraints['order_by'] = [
            "tx.height=0 DESC", "tx.height DESC", "tx.position DESC", "txo.position"
        ]
    elif constraints.get('order_by', None) == 'none':
        del constraints['order_by']

    rows = context().fetchall(select_txos(select_columns, **constraints))
    txos = rows_to_txos(rows, not no_tx)

    channel_hashes = set()
    for txo in txos:
        if txo.is_claim and txo.can_decode_claim:
            if txo.claim.is_signed:
                channel_hashes.add(txo.claim.signing_channel_hash)

    if channel_hashes:
        channels = {
            txo.claim_hash: txo for txo in
            get_txos(
                txo_type=TXO_TYPES['channel'], is_spent=False,
                wallet_account_ids=wallet_account_ids, claim_hash__in=channel_hashes
            )[0]
        }
        for txo in txos:
            if txo.is_claim and txo.can_decode_claim:
                txo.channel = channels.get(txo.claim.signing_channel_hash, None)

    return txos, get_txo_count(**constraints) if include_total else None


def _clean_txo_constraints_for_aggregation(constraints):
    constraints.pop('include_is_spent', None)
    constraints.pop('include_is_my_input', None)
    constraints.pop('include_is_my_output', None)
    constraints.pop('include_received_tips', None)
    constraints.pop('wallet_account_ids', None)
    constraints.pop('offset', None)
    constraints.pop('limit', None)
    constraints.pop('order_by', None)


def get_txo_count(**constraints):
    _clean_txo_constraints_for_aggregation(constraints)
    count = context().fetchall(select_txos([func.count().label('total')], **constraints))
    return count[0]['total'] or 0


def get_txo_sum(**constraints):
    _clean_txo_constraints_for_aggregation(constraints)
    result = context().fetchall(select_txos([func.sum(TXO.c.amount).label('total')], **constraints))
    return result[0]['total'] or 0


def get_balance(**constraints):
    return get_txo_sum(is_spent=False, **constraints)


def get_report(account_ids):
    return


def get_txo_plot(start_day=None, days_back=0, end_day=None, days_after=None, **constraints):
    _clean_txo_constraints_for_aggregation(constraints)
    if start_day is None:
        # TODO: Fix
        current_ordinal = 0  # self.ledger.headers.estimated_date(self.ledger.headers.height).toordinal()
        constraints['day__gte'] = current_ordinal - days_back
    else:
        constraints['day__gte'] = date.fromisoformat(start_day).toordinal()
        if end_day is not None:
            constraints['day__lte'] = date.fromisoformat(end_day).toordinal()
        elif days_after is not None:
            constraints['day__lte'] = constraints['day__gte'] + days_after
    plot = context().fetchall(select_txos(
        [TX.c.day, func.sum(TXO.c.amount).label('total')],
        group_by='day', order_by='day', **constraints
    ))
    for row in plot:
        row['day'] = date.fromordinal(row['day'])
    return plot


BASE_SELECT_SUPPORT_COLUMNS = BASE_SELECT_TXO_COLUMNS + [
    Support.c.channel_hash,
    Support.c.is_signature_valid,
]


def select_supports(cols: List = None, **constraints) -> Select:
    if cols is None:
        cols = BASE_SELECT_SUPPORT_COLUMNS
    joins = Support.join(TXO, ).join(TX)
    return query([Support], select(*cols).select_from(joins), **constraints)


def search_supports(**constraints) -> Tuple[List[Output], Optional[int]]:
    total = None
    if not constraints.pop('no_totals', False):
        total = search_support_count(**constraints)
    rows = context().fetchall(select_supports(**constraints))
    txos = rows_to_txos(rows, include_tx=False)
    return txos, total


def search_support_count(**constraints) -> int:
    constraints.pop('offset', None)
    constraints.pop('limit', None)
    constraints.pop('order_by', None)
    count = context().fetchall(select_supports([func.count().label('total')], **constraints))
    return count[0]['total'] or 0


BASE_SELECT_CLAIM_COLUMNS = BASE_SELECT_TXO_COLUMNS + [
    Claim.c.activation_height,
    Claim.c.takeover_height,
    Claim.c.creation_height,
    Claim.c.is_controlling,
    Claim.c.channel_hash,
    Claim.c.reposted_claim_hash,
    Claim.c.short_url,
    Claim.c.canonical_url,
    Claim.c.signed_claim_count,
    Claim.c.signed_support_count,
    (Claim.c.amount + Claim.c.staked_support_amount).label('staked_amount'),
    Claim.c.staked_support_amount,
    Claim.c.staked_support_count,
    Claim.c.is_signature_valid,
]


def select_claims(cols: List = None, for_count=False, **constraints) -> Select:
    if cols is None:
        cols = BASE_SELECT_CLAIM_COLUMNS
    if 'order_by' in constraints:
        order_by_parts = constraints['order_by']
        if isinstance(order_by_parts, str):
            order_by_parts = [order_by_parts]
        sql_order_by = []
        for order_by in order_by_parts:
            is_asc = order_by.startswith('^')
            column = order_by[1:] if is_asc else order_by
            if column not in SEARCH_ORDER_FIELDS:
                raise NameError(f'{column} is not a valid order_by field')
            if column == 'name':
                column = 'claim_name'
            sql_order_by.append(
                f"claim.{column} ASC" if is_asc else f"claim.{column} DESC"
            )
        constraints['order_by'] = sql_order_by

    ops = {'<=': '__lte', '>=': '__gte', '<': '__lt', '>': '__gt'}
    for constraint in SEARCH_INTEGER_PARAMS:
        if constraint in constraints:
            value = constraints.pop(constraint)
            postfix = ''
            if isinstance(value, str):
                if len(value) >= 2 and value[:2] in ops:
                    postfix, value = ops[value[:2]], value[2:]
                elif len(value) >= 1 and value[0] in ops:
                    postfix, value = ops[value[0]], value[1:]
            if constraint == 'fee_amount':
                value = Decimal(value)*1000
            constraints[f'{constraint}{postfix}'] = int(value)

    if 'sequence' in constraints:
        constraints['order_by'] = 'activation_height ASC'
        constraints['offset'] = int(constraints.pop('sequence')) - 1
        constraints['limit'] = 1
    if 'amount_order' in constraints:
        constraints['order_by'] = 'effective_amount DESC'
        constraints['offset'] = int(constraints.pop('amount_order')) - 1
        constraints['limit'] = 1

    if 'claim_id' in constraints:
        claim_id = constraints.pop('claim_id')
        if len(claim_id) == 40:
            constraints['claim_id'] = claim_id
        else:
            constraints['claim_id__like'] = f'{claim_id[:40]}%'
    elif 'claim_ids' in constraints:
        constraints['claim_id__in'] = set(constraints.pop('claim_ids'))

    if 'reposted_claim_id' in constraints:
        constraints['reposted_claim_hash'] = unhexlify(constraints.pop('reposted_claim_id'))[::-1]

    if 'name' in constraints:
        constraints['claim_name'] = normalize_name(constraints.pop('name'))

    if 'public_key_id' in constraints:
        constraints['public_key_hash'] = (
            context().ledger.address_to_hash160(constraints.pop('public_key_id')))
    if 'channel_hash' in constraints:
        constraints['channel_hash'] = constraints.pop('channel_hash')
    if 'channel_ids' in constraints:
        channel_ids = constraints.pop('channel_ids')
        if channel_ids:
            constraints['channel_hash__in'] = {
                unhexlify(cid)[::-1] for cid in channel_ids
            }
    if 'not_channel_ids' in constraints:
        not_channel_ids = constraints.pop('not_channel_ids')
        if not_channel_ids:
            not_channel_ids_binary = {
                unhexlify(ncid)[::-1] for ncid in not_channel_ids
            }
            constraints['claim_hash__not_in#not_channel_ids'] = not_channel_ids_binary
            if constraints.get('has_channel_signature', False):
                constraints['channel_hash__not_in'] = not_channel_ids_binary
            else:
                constraints['null_or_not_channel__or'] = {
                    'signature_valid__is_null': True,
                    'channel_hash__not_in': not_channel_ids_binary
                }
    if 'signature_valid' in constraints:
        has_channel_signature = constraints.pop('has_channel_signature', False)
        if has_channel_signature:
            constraints['signature_valid'] = constraints.pop('signature_valid')
        else:
            constraints['null_or_signature__or'] = {
                'signature_valid__is_null': True,
                'signature_valid': constraints.pop('signature_valid')
            }
    elif constraints.pop('has_channel_signature', False):
        constraints['signature_valid__is_not_null'] = True

    if 'txid' in constraints:
        tx_hash = unhexlify(constraints.pop('txid'))[::-1]
        nout = constraints.pop('nout', 0)
        constraints['txo_hash'] = tx_hash + struct.pack('<I', nout)

    if 'claim_type' in constraints:
        claim_types = constraints.pop('claim_type')
        if isinstance(claim_types, str):
            claim_types = [claim_types]
        if claim_types:
            constraints['claim_type__in'] = {
                TXO_TYPES[claim_type] for claim_type in claim_types
            }
    if 'stream_types' in constraints:
        stream_types = constraints.pop('stream_types')
        if stream_types:
            constraints['stream_type__in'] = {
                STREAM_TYPES[stream_type] for stream_type in stream_types
            }
    if 'media_types' in constraints:
        media_types = constraints.pop('media_types')
        if media_types:
            constraints['media_type__in'] = set(media_types)

    if 'fee_currency' in constraints:
        constraints['fee_currency'] = constraints.pop('fee_currency').lower()

    _apply_constraints_for_array_attributes(constraints, 'tag', clean_tags, for_count)
    _apply_constraints_for_array_attributes(constraints, 'language', lambda _: _, for_count)
    _apply_constraints_for_array_attributes(constraints, 'location', lambda _: _, for_count)

    if 'text' in constraints:
        # TODO: fix
        constraints["search"] = constraints.pop("text")

    joins = Claim.join(TXO).join(TX)
    return query([Claim], select(*cols).select_from(joins), **constraints)


def search_claims(**constraints) -> Tuple[List[Output], Optional[int], Optional[Censor]]:
    total = None
    if not constraints.pop('no_totals', False):
        total = search_claim_count(**constraints)
    constraints['offset'] = abs(constraints.get('offset', 0))
    constraints['limit'] = min(abs(constraints.get('limit', 10)), 50)
    ctx = context()
    search_censor = ctx.get_search_censor()
    rows = context().fetchall(select_claims(**constraints))
    txos = rows_to_txos(rows, include_tx=False)
    return txos, total, search_censor


def search_claim_count(**constraints) -> int:
    constraints.pop('offset', None)
    constraints.pop('limit', None)
    constraints.pop('order_by', None)
    count = context().fetchall(select_claims([func.count().label('total')], **constraints))
    return count[0]['total'] or 0


def _get_referenced_rows(txo_rows: List[dict], censor_channels: List[bytes]):
    censor = context().get_resolve_censor()
    repost_hashes = set(filter(None, map(itemgetter('reposted_claim_hash'), txo_rows)))
    channel_hashes = set(itertools.chain(
        filter(None, map(itemgetter('channel_hash'), txo_rows)),
        censor_channels
    ))

    reposted_txos = []
    if repost_hashes:
        reposted_txos = search_claims(censor, **{'claim.claim_hash__in': repost_hashes})
        channel_hashes |= set(filter(None, map(itemgetter('channel_hash'), reposted_txos)))

    channel_txos = []
    if channel_hashes:
        channel_txos = search_claims(censor, **{'claim.claim_hash__in': channel_hashes})

    # channels must come first for client side inflation to work properly
    return channel_txos + reposted_txos


def get_purchases(**constraints) -> Tuple[List[Output], Optional[int]]:
    accounts = constraints.pop('accounts', None)
    assert accounts, "'accounts' argument required to find purchases"
    if not {'purchased_claim_hash', 'purchased_claim_hash__in'}.intersection(constraints):
        constraints['purchased_claim_hash__is_not_null'] = True
    constraints['tx_hash__in'] = (
        select(TXI.c.tx_hash).select_from(txi_join_account).where(in_account_ids(accounts))
    )
    txs, count = get_transactions(**constraints)
    return [tx.outputs[0] for tx in txs], count


def select_addresses(cols, **constraints):
    return context().fetchall(query(
        [AccountAddress, PubkeyAddress],
        select(*cols).select_from(PubkeyAddress.join(AccountAddress)),
        **constraints
    ))


def get_addresses(cols=None, include_total=False, **constraints) -> Tuple[List[dict], Optional[int]]:
    if cols is None:
        cols = (
            PubkeyAddress.c.address,
            PubkeyAddress.c.used_times,
            AccountAddress.c.account,
            AccountAddress.c.chain,
            AccountAddress.c.pubkey,
            AccountAddress.c.chain_code,
            AccountAddress.c.n,
            AccountAddress.c.depth
        )
    return (
        select_addresses(cols, **constraints),
        get_address_count(**constraints) if include_total else None
    )


def get_address_count(**constraints):
    count = select_addresses([func.count().label('total')], **constraints)
    return count[0]['total'] or 0


def get_all_addresses(self):
    return context().execute(select(PubkeyAddress.c.address))


def add_keys(account, chain, pubkeys):
    c = context()
    c.execute(
        c.insert_or_ignore(PubkeyAddress)
        .values([{'address': k.address} for k in pubkeys])
    )
    c.execute(
        c.insert_or_ignore(AccountAddress)
        .values([{
            'account': account.id,
            'address': k.address,
            'chain': chain,
            'pubkey': k.pubkey_bytes,
            'chain_code': k.chain_code,
            'n': k.n,
            'depth': k.depth
        } for k in pubkeys])
    )


def get_supports_summary(self, **constraints):
    return get_txos(
        txo_type=TXO_TYPES['support'],
        is_spent=False, is_my_output=True,
        include_is_my_input=True,
        no_tx=True,
        **constraints
    )


def resolve(*urls) -> Dict[str, Output]:
    return {url: resolve_url(url) for url in urls}
    #txo_rows = [resolve_url(raw_url) for raw_url in urls]
    #extra_txo_rows = _get_referenced_rows(
    #    [txo for txo in txo_rows if isinstance(txo, dict)],
    #    [txo.censor_hash for txo in txo_rows if isinstance(txo, ResolveCensoredError)]
    #)
    #return txo_rows, extra_txo_rows


def resolve_url(raw_url):
    censor = context().get_resolve_censor()

    try:
        url = URL.parse(raw_url)
    except ValueError as e:
        return e

    channel = None

    if url.has_channel:
        q = url.channel.to_dict()
        if set(q) == {'name'}:
            q['is_controlling'] = True
        else:
            q['order_by'] = ['^creation_height']
        #matches = search_claims(censor, **q, limit=1)
        matches = search_claims(**q, limit=1)[0]
        if matches:
            channel = matches[0]
        elif censor.censored:
            return ResolveCensoredError(raw_url, next(iter(censor.censored)))
        else:
            return LookupError(f'Could not find channel in "{raw_url}".')

    if url.has_stream:
        q = url.stream.to_dict()
        if channel is not None:
            q['order_by'] = ['^creation_height']
            q['channel_hash'] = channel.claim_hash
            q['is_signature_valid'] = 1
        elif set(q) == {'name'}:
            q['is_controlling'] = 1
        # matches = search_claims(censor, **q, limit=1)
        matches = search_claims(**q, limit=1)[0]
        if matches:
            return matches[0]
        elif censor.censored:
            return ResolveCensoredError(raw_url, next(iter(censor.censored)))
        else:
            return LookupError(f'Could not find claim at "{raw_url}".')

    return channel


CLAIM_HASH_OR_REPOST_HASH_SQL = f"""
CASE WHEN claim.claim_type = {TXO_TYPES['repost']}
    THEN claim.reposted_claim_hash
    ELSE claim.claim_hash
END
"""


def _apply_constraints_for_array_attributes(constraints, attr, cleaner, for_count=False):
    any_items = set(cleaner(constraints.pop(f'any_{attr}s', []))[:ATTRIBUTE_ARRAY_MAX_LENGTH])
    all_items = set(cleaner(constraints.pop(f'all_{attr}s', []))[:ATTRIBUTE_ARRAY_MAX_LENGTH])
    not_items = set(cleaner(constraints.pop(f'not_{attr}s', []))[:ATTRIBUTE_ARRAY_MAX_LENGTH])

    all_items = {item for item in all_items if item not in not_items}
    any_items = {item for item in any_items if item not in not_items}

    any_queries = {}

#    if attr == 'tag':
#        common_tags = any_items & COMMON_TAGS.keys()
#        if common_tags:
#            any_items -= common_tags
#        if len(common_tags) < 5:
#            for item in common_tags:
#                index_name = COMMON_TAGS[item]
#                any_queries[f'#_common_tag_{index_name}'] = f"""
#                EXISTS(
#                    SELECT 1 FROM tag INDEXED BY tag_{index_name}_idx
#                    WHERE {CLAIM_HASH_OR_REPOST_HASH_SQL}=tag.claim_hash
#                    AND tag = '{item}'
#                )
#                """
#        elif len(common_tags) >= 5:
#            constraints.update({
#                f'$any_common_tag{i}': item for i, item in enumerate(common_tags)
#            })
#            values = ', '.join(
#                f':$any_common_tag{i}' for i in range(len(common_tags))
#            )
#            any_queries[f'#_any_common_tags'] = f"""
#            EXISTS(
#                SELECT 1 FROM tag WHERE {CLAIM_HASH_OR_REPOST_HASH_SQL}=tag.claim_hash
#                AND tag IN ({values})
#            )
#            """

    if any_items:

        constraints.update({
            f'$any_{attr}{i}': item for i, item in enumerate(any_items)
        })
        values = ', '.join(
            f':$any_{attr}{i}' for i in range(len(any_items))
        )
        if for_count or attr == 'tag':
            any_queries[f'#_any_{attr}'] = f"""
            {CLAIM_HASH_OR_REPOST_HASH_SQL} IN (
                SELECT claim_hash FROM {attr} WHERE {attr} IN ({values})
            )
            """
        else:
            any_queries[f'#_any_{attr}'] = f"""
            EXISTS(
                SELECT 1 FROM {attr} WHERE
                    {CLAIM_HASH_OR_REPOST_HASH_SQL}={attr}.claim_hash
                AND {attr} IN ({values})
            )
            """

    if len(any_queries) == 1:
        constraints.update(any_queries)
    elif len(any_queries) > 1:
        constraints[f'ORed_{attr}_queries__any'] = any_queries

    if all_items:
        constraints[f'$all_{attr}_count'] = len(all_items)
        constraints.update({
            f'$all_{attr}{i}': item for i, item in enumerate(all_items)
        })
        values = ', '.join(
            f':$all_{attr}{i}' for i in range(len(all_items))
        )
        if for_count:
            constraints[f'#_all_{attr}'] = f"""
            {CLAIM_HASH_OR_REPOST_HASH_SQL} IN (
                SELECT claim_hash FROM {attr} WHERE {attr} IN ({values})
                GROUP BY claim_hash HAVING COUNT({attr}) = :$all_{attr}_count
            )
            """
        else:
            constraints[f'#_all_{attr}'] = f"""
                {len(all_items)}=(
                    SELECT count(*) FROM {attr} WHERE
                        {CLAIM_HASH_OR_REPOST_HASH_SQL}={attr}.claim_hash
                    AND {attr} IN ({values})
                )
            """

    if not_items:
        constraints.update({
            f'$not_{attr}{i}': item for i, item in enumerate(not_items)
        })
        values = ', '.join(
            f':$not_{attr}{i}' for i in range(len(not_items))
        )
        if for_count:
            constraints[f'#_not_{attr}'] = f"""
            {CLAIM_HASH_OR_REPOST_HASH_SQL} NOT IN (
                SELECT claim_hash FROM {attr} WHERE {attr} IN ({values})
            )
            """
        else:
            constraints[f'#_not_{attr}'] = f"""
                NOT EXISTS(
                    SELECT 1 FROM {attr} WHERE
                        {CLAIM_HASH_OR_REPOST_HASH_SQL}={attr}.claim_hash
                    AND {attr} IN ({values})
                )
            """
