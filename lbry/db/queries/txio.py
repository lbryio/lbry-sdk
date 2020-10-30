import logging
from datetime import date
from typing import Tuple, List, Optional, Union

from sqlalchemy import union, func, text, between, distinct, case
from sqlalchemy.future import select, Select

from ...blockchain.transaction import (
    Transaction, Output, OutputScript, TXRefImmutable
)
from ..tables import (
    TX, TXO, TXI, txi_join_account, txo_join_account,
    Claim, Support, AccountAddress
)
from ..utils import query, in_account_ids
from ..query_context import context
from ..constants import TXO_TYPES, CLAIM_TYPE_CODES, MAX_QUERY_VARIABLES


log = logging.getLogger(__name__)


minimum_txo_columns = (
    TXO.c.amount, TXO.c.position.label('txo_position'),
    TX.c.tx_hash, TX.c.height, TX.c.timestamp,
    func.substr(TX.c.raw, TXO.c.script_offset + 1, TXO.c.script_length).label('src'),
)


def row_to_txo(row):
    return Output(
        amount=row.amount,
        script=OutputScript(row.src),
        tx_ref=TXRefImmutable.from_hash(row.tx_hash, row.height, row.timestamp),
        position=row.txo_position,
    )


def where_txo_type_in(txo_type: Optional[Union[tuple, int]] = None):
    if txo_type is not None:
        if isinstance(txo_type, int):
            return TXO.c.txo_type == txo_type
        assert len(txo_type) > 0
        if len(txo_type) == 1:
            return TXO.c.txo_type == txo_type[0]
        else:
            return TXO.c.txo_type.in_(txo_type)
    return TXO.c.txo_type.in_(CLAIM_TYPE_CODES)


def where_unspent_txos(
    txo_types: Tuple[int, ...],
    blocks: Tuple[int, int] = None,
    missing_in_supports_table: bool = False,
    missing_in_claims_table: bool = False,
    missing_or_stale_in_claims_table: bool = False,
):
    condition = where_txo_type_in(txo_types) & (TXO.c.spent_height == 0)
    if blocks is not None:
        condition &= between(TXO.c.height, *blocks)
    if missing_in_supports_table:
        condition &= TXO.c.txo_hash.notin_(select(Support.c.txo_hash))
    elif missing_or_stale_in_claims_table:
        condition &= TXO.c.txo_hash.notin_(select(Claim.c.txo_hash))
    elif missing_in_claims_table:
        condition &= TXO.c.claim_hash.notin_(select(Claim.c.claim_hash))
    return condition


def where_abandoned_claims():
    return Claim.c.claim_hash.notin_(
        select(TXO.c.claim_hash).where(where_unspent_txos(CLAIM_TYPE_CODES))
    )


def count_abandoned_claims():
    return context().fetchtotal(where_abandoned_claims())


def where_abandoned_supports():
    return Support.c.txo_hash.notin_(
        select(TXO.c.txo_hash).where(where_unspent_txos(TXO_TYPES['support']))
    )


def count_abandoned_supports():
    return context().fetchtotal(where_abandoned_supports())


def count_unspent_txos(
    txo_types: Tuple[int, ...],
    blocks: Tuple[int, int] = None,
    missing_in_supports_table: bool = False,
    missing_in_claims_table: bool = False,
    missing_or_stale_in_claims_table: bool = False,
):
    return context().fetchtotal(
        where_unspent_txos(
            txo_types, blocks,
            missing_in_supports_table,
            missing_in_claims_table,
            missing_or_stale_in_claims_table,
        )
    )


def distribute_unspent_txos(
    txo_types: Tuple[int, ...],
    blocks: Tuple[int, int] = None,
    missing_in_supports_table: bool = False,
    missing_in_claims_table: bool = False,
    missing_or_stale_in_claims_table: bool = False,
    number_of_buckets: int = 10
) -> Tuple[int, List[Tuple[int, int]]]:
    chunks = (
        select(func.ntile(number_of_buckets).over(order_by=TXO.c.height).label('chunk'), TXO.c.height)
        .where(
            where_unspent_txos(
                txo_types, blocks,
                missing_in_supports_table,
                missing_in_claims_table,
                missing_or_stale_in_claims_table,
            )
        ).cte('chunks')
    )
    sql = (
        select(
            func.count('*').label('items'),
            func.min(chunks.c.height).label('start_height'),
            func.max(chunks.c.height).label('end_height'),
        ).group_by(chunks.c.chunk).order_by(chunks.c.chunk)
    )
    total = 0
    buckets = []
    for bucket in context().fetchall(sql):
        total += bucket['items']
        if len(buckets) > 0:
            if buckets[-1][-1] == bucket['start_height']:
                if bucket['start_height'] == bucket['end_height']:
                    continue
                bucket['start_height'] += 1
        buckets.append((bucket['start_height'], bucket['end_height']))
    return total, buckets


def where_changed_support_txos(blocks: Optional[Tuple[int, int]]):
    return (
        (TXO.c.txo_type == TXO_TYPES['support']) & (
            between(TXO.c.height, blocks[0], blocks[-1]) |
            between(TXO.c.spent_height, blocks[0], blocks[-1])
        )
    )


def where_claims_with_changed_supports(blocks: Optional[Tuple[int, int]]):
    return Claim.c.claim_hash.in_(
        select(TXO.c.claim_hash).where(
            where_changed_support_txos(blocks)
        )
    )


def count_claims_with_changed_supports(blocks: Optional[Tuple[int, int]]) -> int:
    sql = (
        select(func.count(distinct(TXO.c.claim_hash)).label('total'))
        .where(where_changed_support_txos(blocks))
    )
    return context().fetchone(sql)['total']


def where_changed_content_txos(blocks: Optional[Tuple[int, int]]):
    return (
        (TXO.c.channel_hash.isnot(None)) & (
            between(TXO.c.height, blocks[0], blocks[-1]) |
            between(TXO.c.spent_height, blocks[0], blocks[-1])
        )
    )


def where_channels_with_changed_content(blocks: Optional[Tuple[int, int]]):
    return Claim.c.claim_hash.in_(
        select(TXO.c.channel_hash).where(
            where_changed_content_txos(blocks)
        )
    )


def count_channels_with_changed_content(blocks: Optional[Tuple[int, int]]):
    sql = (
        select(func.count(distinct(TXO.c.channel_hash)).label('total'))
        .where(where_changed_content_txos(blocks))
    )
    return context().fetchone(sql)['total']


def where_changed_repost_txos(blocks: Optional[Tuple[int, int]]):
    return (
        (TXO.c.txo_type == TXO_TYPES['repost']) & (
            between(TXO.c.height, blocks[0], blocks[-1]) |
            between(TXO.c.spent_height, blocks[0], blocks[-1])
        )
    )


def where_claims_with_changed_reposts(blocks: Optional[Tuple[int, int]]):
    return Claim.c.claim_hash.in_(
        select(TXO.c.reposted_claim_hash).where(
            where_changed_repost_txos(blocks)
        )
    )


def count_claims_with_changed_reposts(blocks: Optional[Tuple[int, int]]):
    sql = (
        select(func.count(distinct(TXO.c.reposted_claim_hash)).label('total'))
        .where(where_changed_repost_txos(blocks))
    )
    return context().fetchone(sql)['total']


def select_transactions(cols, account_ids=None, **constraints):
    s: Select = select(*cols).select_from(TX)
    if not {'tx_hash', 'tx_hash__in'}.intersection(constraints):
        assert account_ids, (
            "'accounts' argument required when "
            "no 'tx_hash' constraint is present"
        )
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


def _get_transactions(
    wallet=None, include_total=False, **constraints
) -> Tuple[List[Transaction], Optional[int]]:
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
    TXO.c.txo_type, TXO.c.position.label('txo_position'), TXO.c.amount, TXO.c.spent_height,
    TXO.c.script_offset, TXO.c.script_length,
]


def select_txos(
    cols=None, account_ids=None, is_my_input=None,
    is_my_output=True, is_my_input_or_output=None, exclude_internal_transfers=False,
    include_is_my_input=False, claim_id_not_in_claim_table=None,
    txo_id_not_in_claim_table=None, txo_id_not_in_support_table=None,
    **constraints
) -> Select:
    if cols is None:
        cols = BASE_SELECT_TXO_COLUMNS
    s: Select = select(*cols)
    if account_ids:
        my_addresses = select(AccountAddress.c.address).where(in_account_ids(account_ids))
        if is_my_input_or_output:
            include_is_my_input = True
            s = s.where(
                TXO.c.address.in_(my_addresses) | (
                    (TXI.c.address.isnot(None)) &
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
                    (TXI.c.address.isnot(None)) &
                    (TXI.c.address.in_(my_addresses))
                )
            elif is_my_input is False:
                include_is_my_input = True
                s = s.where(
                    (TXI.c.address.is_(None)) |
                    (TXI.c.address.notin_(my_addresses))
                )
        if exclude_internal_transfers:
            include_is_my_input = True
            s = s.where(
                (TXO.c.txo_type != TXO_TYPES['other']) |
                (TXO.c.address.notin_(my_addresses))
                (TXI.c.address.is_(None)) |
                (TXI.c.address.notin_(my_addresses))
            )
    joins = TXO.join(TX)
    if constraints.pop('is_spent', None) is False:
        s = s.where((TXO.c.spent_height == 0) & (TXO.c.is_reserved == False))
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
    'reposted_count', 'expiration_height'
)


def rows_to_txos(rows: List[dict], include_tx=True) -> List[Output]:
    txos = []
    tx_cache = {}
    for row in rows:
        if include_tx:
            if row['tx_hash'] not in tx_cache:
                tx_cache[row['tx_hash']] = Transaction(
                    row['raw'], height=row['height'], position=row['tx_position'],
                    timestamp=row['timestamp'],
                    is_verified=bool(row['is_verified']),
                )
            txo = tx_cache[row['tx_hash']].outputs[row['txo_position']]
        else:
            source = row['raw'][row['script_offset']:row['script_offset']+row['script_length']]
            txo = Output(
                amount=row['amount'],
                script=OutputScript(source),
                tx_ref=TXRefImmutable.from_hash(row['tx_hash'], row['height'], row['timestamp']),
                position=row['txo_position'],
            )
        txo.spent_height = row['spent_height']
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
                (TXI.c.address.isnot(None)) &
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
                txo_type=TXO_TYPES['channel'], spent_height=0,
                wallet_account_ids=wallet_account_ids, claim_hash__in=channel_hashes
            )[0]
        }
        for txo in txos:
            if txo.is_claim and txo.can_decode_claim:
                txo.channel = channels.get(txo.claim.signing_channel_hash, None)

    return txos, get_txo_count(**constraints) if include_total else None


def _clean_txo_constraints_for_aggregation(constraints):
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


def get_balance(account_ids):
    ctx = context()
    my_addresses = select(AccountAddress.c.address).where(in_account_ids(account_ids))
    if ctx.is_postgres:
        txo_address_check = TXO.c.address == func.any(func.array(my_addresses))
        txi_address_check = TXI.c.address == func.any(func.array(my_addresses))
    else:
        txo_address_check = TXO.c.address.in_(my_addresses)
        txi_address_check = TXI.c.address.in_(my_addresses)
    query = (
        select(
            func.coalesce(func.sum(TXO.c.amount), 0).label("total"),
            func.coalesce(func.sum(case(
                [(TXO.c.txo_type != TXO_TYPES["other"], TXO.c.amount)],
            )), 0).label("reserved"),
            func.coalesce(func.sum(case(
                [(where_txo_type_in(CLAIM_TYPE_CODES), TXO.c.amount)],
            )), 0).label("claims"),
            func.coalesce(func.sum(case(
                [(where_txo_type_in(TXO_TYPES["support"]), TXO.c.amount)],
            )), 0).label("supports"),
            func.coalesce(func.sum(case(
                [(where_txo_type_in(TXO_TYPES["support"]) & (
                   (TXI.c.address.isnot(None)) & txi_address_check
                ), TXO.c.amount)],
            )), 0).label("my_supports"),
        )
        .where((TXO.c.spent_height == 0) & txo_address_check)
        .select_from(
            TXO.join(TXI, (TXI.c.position == 0) & (TXI.c.tx_hash == TXO.c.tx_hash), isouter=True)
        )
    )
    result = ctx.fetchone(query)
    return {
        "total": result["total"],
        "available": result["total"] - result["reserved"],
        "reserved": result["reserved"],
        "reserved_subtotals": {
            "claims": result["claims"],
            "supports": result["my_supports"],
            "tips": result["supports"] - result["my_supports"]
        }
    }


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


def get_supports_summary(self, **constraints):
    return get_txos(
        txo_type=TXO_TYPES['support'],
        spent_height=0, is_my_output=True,
        include_is_my_input=True,
        no_tx=True,
        **constraints
    )


def reserve_outputs(txo_hashes, is_reserved=True):
    context().execute(
        TXO.update()
        .values(is_reserved=is_reserved)
        .where(TXO.c.txo_hash.in_(txo_hashes))
    )


def release_all_outputs(account_id):
    context().execute(
        TXO.update().values(is_reserved=False).where(
            TXO.c.is_reserved & TXO.c.address.in_(
                select(AccountAddress.c.address).where(in_account_ids(account_id))
            )
        )
    )
