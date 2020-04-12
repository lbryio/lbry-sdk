# pylint: disable=singleton-comparison

import logging
import asyncio
import sqlite3
from concurrent.futures.thread import ThreadPoolExecutor
from typing import List, Union, Iterable, Optional
from datetime import date

import sqlalchemy
from sqlalchemy.future import select
from sqlalchemy import text, and_, union, func, inspect
from sqlalchemy.sql.expression import Select
try:
    from sqlalchemy.dialects.postgresql import insert as pg_insert
except ImportError:
    pg_insert = None


from lbry.wallet import PubKey
from lbry.wallet.transaction import Transaction, Output, OutputScript, TXRefImmutable
from lbry.wallet.constants import TXO_TYPES, CLAIM_TYPES

from .tables import (
    metadata, Version,
    PubkeyAddress, AccountAddress,
    TX,
    TXO, txo_join_account,
    TXI, txi_join_account,
)


log = logging.getLogger(__name__)
sqlite3.enable_callback_tracebacks(True)


def insert_or_ignore(conn, table):
    if conn.dialect.name == 'sqlite':
        return table.insert().prefix_with("OR IGNORE")
    elif conn.dialect.name == 'postgresql':
        return pg_insert(table).on_conflict_do_nothing()
    else:
        raise RuntimeError(f'Unknown database dialect: {conn.dialect.name}.')


def insert_or_replace(conn, table, replace):
    if conn.dialect.name == 'sqlite':
        return table.insert().prefix_with("OR REPLACE")
    elif conn.dialect.name == 'postgresql':
        insert = pg_insert(table)
        return insert.on_conflict_do_update(
            table.primary_key, set_={col: getattr(insert.excluded, col) for col in replace}
        )
    else:
        raise RuntimeError(f'Unknown database dialect: {conn.dialect.name}.')


def constrain_single_or_list(constraints, column, value, convert=lambda x: x):
    if value is not None:
        if isinstance(value, list):
            value = [convert(v) for v in value]
            if len(value) == 1:
                constraints[column] = value[0]
            elif len(value) > 1:
                constraints[f"{column}__in"] = value
        else:
            constraints[column] = convert(value)
    return constraints


def in_account(accounts: Union[List[PubKey], PubKey]):
    if isinstance(accounts, list):
        if len(accounts) > 1:
            return AccountAddress.c.account.in_({a.public_key.address for a in accounts})
        accounts = accounts[0]
    return AccountAddress.c.account == accounts.public_key.address


def query2(table, s: Select, **constraints) -> Select:
    limit = constraints.pop('limit', None)
    if limit is not None:
        s = s.limit(limit)

    offset = constraints.pop('offset', None)
    if offset is not None:
        s = s.offset(offset)

    order_by = constraints.pop('order_by', None)
    if order_by:
        if isinstance(order_by, str):
            s = s.order_by(text(order_by))
        elif isinstance(order_by, list):
            s = s.order_by(text(', '.join(order_by)))
        else:
            raise ValueError("order_by must be string or list")

    group_by = constraints.pop('group_by', None)
    if group_by is not None:
        s = s.group_by(text(group_by))

    accounts = constraints.pop('accounts', [])
    if accounts:
        s = s.where(in_account(accounts))

    if constraints:
        s = s.where(
            constraints_to_clause2(table, constraints)
        )

    return s


def constraints_to_clause2(tables, constraints):
    clause = []
    for key, constraint in constraints.items():
        if key.endswith('__not'):
            col, op = key[:-len('__not')], '__ne__'
        elif key.endswith('__is_null'):
            col = key[:-len('__is_null')]
            op = '__eq__'
            constraint = None
        elif key.endswith('__is_not_null'):
            col = key[:-len('__is_not_null')]
            op = '__ne__'
            constraint = None
        elif key.endswith('__lt'):
            col, op = key[:-len('__lt')], '__lt__'
        elif key.endswith('__lte'):
            col, op = key[:-len('__lte')], '__le__'
        elif key.endswith('__gt'):
            col, op = key[:-len('__gt')], '__gt__'
        elif key.endswith('__gte'):
            col, op = key[:-len('__gte')], '__ge__'
        elif key.endswith('__like'):
            col, op = key[:-len('__like')], 'like'
        elif key.endswith('__not_like'):
            col, op = key[:-len('__not_like')], 'notlike'
        elif key.endswith('__in') or key.endswith('__not_in'):
            if key.endswith('__in'):
                col, op, one_val_op = key[:-len('__in')], 'in_', '__eq__'
            else:
                col, op, one_val_op = key[:-len('__not_in')], 'notin_', '__ne__'
            if isinstance(constraint, sqlalchemy.sql.expression.Select):
                pass
            elif constraint:
                if isinstance(constraint, (list, set, tuple)):
                    if len(constraint) == 1:
                        op = one_val_op
                        constraint = next(iter(constraint))
                elif isinstance(constraint, str):
                    constraint = text(constraint)
                else:
                    raise ValueError(f"{col} requires a list, set or string as constraint value.")
            else:
                continue
        else:
            col, op = key, '__eq__'
        attr = None
        for table in tables:
            attr = getattr(table.c, col, None)
            if attr is not None:
                clause.append(getattr(attr, op)(constraint))
                break
        if attr is None:
            raise ValueError(f"Attribute '{col}' not found on tables: {', '.join([t.name for t in tables])}.")
    return and_(*clause)


class Database:

    SCHEMA_VERSION = "1.3"
    MAX_QUERY_VARIABLES = 900

    def __init__(self, url):
        self.url = url
        self.ledger = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.engine = None
        self.db: Optional[sqlalchemy.engine.Connection] = None

    def sync_execute_fetchall(self, sql, params=None):
        if params:
            result = self.db.execute(sql, params)
        else:
            result = self.db.execute(sql)
        if result.returns_rows:
            return [dict(r._mapping) for r in result.fetchall()]
        return []

    async def execute_fetchall(self, sql, params=None) -> List[dict]:
        return await asyncio.get_event_loop().run_in_executor(
            self.executor, self.sync_execute_fetchall, sql, params
        )

    def sync_executemany(self, sql, parameters):
        self.db.execute(sql, parameters)

    async def executemany(self, sql: str, parameters: Iterable = None):
        return await asyncio.get_event_loop().run_in_executor(
            self.executor, self.sync_executemany, sql, parameters
        )

    def sync_open(self):
        log.info("connecting to database: %s", self.url)
        self.engine = sqlalchemy.create_engine(self.url)
        self.db = self.engine.connect()
        if self.SCHEMA_VERSION:
            if inspect(self.engine).has_table('version'):
                version = self.db.execute(Version.select().limit(1)).fetchone()
                if version and version.version == self.SCHEMA_VERSION:
                    return
            metadata.drop_all(self.engine)
            metadata.create_all(self.engine)
            self.db.execute(Version.insert().values(version=self.SCHEMA_VERSION))
        else:
            metadata.create_all(self.engine)
        return self

    async def open(self):
        return await asyncio.get_event_loop().run_in_executor(
            self.executor, self.sync_open
        )

    def sync_close(self):
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None
            self.db = None

    async def close(self):
        await asyncio.get_event_loop().run_in_executor(
            self.executor, self.sync_close
        )

    def sync_create(self, name):
        engine = sqlalchemy.create_engine(self.url)
        db = engine.connect()
        db.execute(text('commit'))
        db.execute(text(f'create database {name}'))

    async def create(self, name):
        await asyncio.get_event_loop().run_in_executor(
            self.executor, self.sync_create, name
        )

    def sync_drop(self, name):
        engine = sqlalchemy.create_engine(self.url)
        db = engine.connect()
        db.execute(text('commit'))
        db.execute(text(f'drop database if exists {name}'))

    async def drop(self, name):
        await asyncio.get_event_loop().run_in_executor(
            self.executor, self.sync_drop, name
        )

    def txo_to_row(self, tx, txo):
        row = {
            'tx_hash': tx.hash,
            'txo_hash': txo.hash,
            'address': txo.get_address(self.ledger),
            'position': txo.position,
            'amount': txo.amount,
            'script': txo.script.source
        }
        if txo.is_claim:
            if txo.can_decode_claim:
                claim = txo.claim
                row['txo_type'] = TXO_TYPES.get(claim.claim_type, TXO_TYPES['stream'])
                if claim.is_repost:
                    row['reposted_claim_hash'] = claim.repost.reference.claim_hash
                if claim.is_signed:
                    row['channel_hash'] = claim.signing_channel_hash
            else:
                row['txo_type'] = TXO_TYPES['stream']
        elif txo.is_support:
            row['txo_type'] = TXO_TYPES['support']
        elif txo.purchase is not None:
            row['txo_type'] = TXO_TYPES['purchase']
            row['claim_id'] = txo.purchased_claim_id
            row['claim_hash'] = txo.purchased_claim_hash
        if txo.script.is_claim_involved:
            row['claim_id'] = txo.claim_id
            row['claim_hash'] = txo.claim_hash
            row['claim_name'] = txo.claim_name
        return row

    def tx_to_row(self, tx):
        row = {
            'tx_hash': tx.hash,
            'raw': tx.raw,
            'height': tx.height,
            'position': tx.position,
            'is_verified': tx.is_verified,
            'day': tx.get_ordinal_day(self.ledger),
        }
        txos = tx.outputs
        if len(txos) >= 2 and txos[1].can_decode_purchase_data:
            txos[0].purchase = txos[1]
            row['purchased_claim_hash'] = txos[1].purchase_data.claim_hash
        return row

    async def insert_transaction(self, tx):
        await self.execute_fetchall(TX.insert().values(self.tx_to_row(tx)))

    def _transaction_io(self, conn: sqlite3.Connection, tx: Transaction, address, txhash):
        conn.execute(
            insert_or_replace(conn, TX, ('block_hash', 'height', 'position', 'is_verified', 'day')).values(
                self.tx_to_row(tx)
            )
        )

        is_my_input = False

        for txi in tx.inputs:
            if txi.txo_ref.txo is not None:
                txo = txi.txo_ref.txo
                if txo.has_address and txo.get_address(self.ledger) == address:
                    is_my_input = True
                    conn.execute(
                        insert_or_ignore(conn, TXI).values({
                            'tx_hash': tx.hash,
                            'txo_hash': txo.hash,
                            'address': address,
                            'position': txi.position
                        })
                    )

        for txo in tx.outputs:
            if txo.script.is_pay_pubkey_hash and (txo.pubkey_hash == txhash or is_my_input):
                conn.execute(insert_or_ignore(conn, TXO).values(self.txo_to_row(tx, txo)))
            elif txo.script.is_pay_script_hash:
                # TODO: implement script hash payments
                log.warning('Database.save_transaction_io: pay script hash is not implemented!')

    def save_transaction_io(self, tx: Transaction, address, txhash, history):
        return self.save_transaction_io_batch([tx], address, txhash, history)

    def save_transaction_io_batch(self, txs: Iterable[Transaction], address, txhash, history):
        history_count = history.count(':') // 2

        def __many():
            for tx in txs:
                self._transaction_io(self.db, tx, address, txhash)
            self.db.execute(
                PubkeyAddress.update()
                .values(history=history, used_times=history_count)
                .where(PubkeyAddress.c.address == address)
            )

        return asyncio.get_event_loop().run_in_executor(self.executor, __many)

    async def reserve_outputs(self, txos, is_reserved=True):
        txo_hashes = [txo.hash for txo in txos]
        if txo_hashes:
            await self.execute_fetchall(
                TXO.update().values(is_reserved=is_reserved).where(TXO.c.txo_hash.in_(txo_hashes))
            )

    async def release_outputs(self, txos):
        await self.reserve_outputs(txos, is_reserved=False)

    async def rewind_blockchain(self, above_height):  # pylint: disable=no-self-use
        # TODO:
        # 1. delete transactions above_height
        # 2. update address histories removing deleted TXs
        return True

    async def select_transactions(self, cols, accounts=None, **constraints):
        s: Select = select(*cols).select_from(TX)
        if not {'tx_hash', 'tx_hash__in'}.intersection(constraints):
            assert accounts, "'accounts' argument required when no 'tx_hash' constraint is present"
            where = in_account(accounts)
            tx_hashes = union(
                select(TXO.c.tx_hash).select_from(txo_join_account).where(where),
                select(TXI.c.tx_hash).select_from(txi_join_account).where(where)
            )
            s = s.where(TX.c.tx_hash.in_(tx_hashes))
        return await self.execute_fetchall(query2([TX], s, **constraints))

    TXO_NOT_MINE = Output(None, None, is_my_output=False)

    async def get_transactions(self, wallet=None, **constraints):
        include_is_spent = constraints.pop('include_is_spent', False)
        include_is_my_input = constraints.pop('include_is_my_input', False)
        include_is_my_output = constraints.pop('include_is_my_output', False)

        tx_rows = await self.select_transactions(
            [TX.c.tx_hash, TX.c.raw, TX.c.height, TX.c.position, TX.c.is_verified],
            order_by=constraints.pop('order_by', ["height=0 DESC", "height DESC", "position DESC"]),
            **constraints
        )

        if not tx_rows:
            return []

        txids, txs, txi_txoids = [], [], []
        for row in tx_rows:
            txids.append(row['tx_hash'])
            txs.append(Transaction(
                raw=row['raw'], height=row['height'], position=row['position'],
                is_verified=bool(row['is_verified'])
            ))
            for txi in txs[-1].inputs:
                txi_txoids.append(txi.txo_ref.hash)

        step = self.MAX_QUERY_VARIABLES
        annotated_txos = {}
        for offset in range(0, len(txids), step):
            annotated_txos.update({
                txo.id: txo for txo in
                (await self.get_txos(
                    wallet=wallet,
                    tx_hash__in=txids[offset:offset+step], order_by='txo.tx_hash',
                    include_is_spent=include_is_spent,
                    include_is_my_input=include_is_my_input,
                    include_is_my_output=include_is_my_output,
                ))
            })

        referenced_txos = {}
        for offset in range(0, len(txi_txoids), step):
            referenced_txos.update({
                txo.id: txo for txo in
                (await self.get_txos(
                    wallet=wallet,
                    txo_hash__in=txi_txoids[offset:offset+step], order_by='txo.txo_hash',
                    include_is_my_output=include_is_my_output,
                ))
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
                    txo.update_annotations(self.TXO_NOT_MINE)

        for tx in txs:
            txos = tx.outputs
            if len(txos) >= 2 and txos[1].can_decode_purchase_data:
                txos[0].purchase = txos[1]

        return txs

    async def get_transaction_count(self, **constraints):
        constraints.pop('wallet', None)
        constraints.pop('offset', None)
        constraints.pop('limit', None)
        constraints.pop('order_by', None)
        count = await self.select_transactions([func.count().label('total')], **constraints)
        return count[0]['total'] or 0

    async def get_transaction(self, **constraints):
        txs = await self.get_transactions(limit=1, **constraints)
        if txs:
            return txs[0]

    async def select_txos(
            self, cols, accounts=None, is_my_input=None, is_my_output=True,
            is_my_input_or_output=None, exclude_internal_transfers=False,
            include_is_spent=False, include_is_my_input=False,
            is_spent=None, spent=None, **constraints):
        s: Select = select(*cols)
        if accounts:
            my_addresses = select(AccountAddress.c.address).where(in_account(accounts))
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
                    (TXI.c.address == None) |
                    (TXI.c.address.notin_(my_addresses))
                )
        joins = TXO.join(TX)
        if spent is None:
            spent = TXI.alias('spent')
        if is_spent:
            s = s.where(spent.c.txo_hash != None)
        elif is_spent is False:
            s = s.where((spent.c.txo_hash == None) & (TXO.c.is_reserved == False))
        if include_is_spent or is_spent is not None:
            joins = joins.join(spent, spent.c.txo_hash == TXO.c.txo_hash, isouter=True)
        if include_is_my_input:
            joins = joins.join(TXI, (TXI.c.position == 0) & (TXI.c.tx_hash == TXO.c.tx_hash), isouter=True)
        s = s.select_from(joins)
        return await self.execute_fetchall(query2([TXO, TX], s, **constraints))

    async def get_txos(self, wallet=None, no_tx=False, **constraints):
        include_is_spent = constraints.get('include_is_spent', False)
        include_is_my_input = constraints.get('include_is_my_input', False)
        include_is_my_output = constraints.pop('include_is_my_output', False)
        include_received_tips = constraints.pop('include_received_tips', False)

        select_columns = [
            TX.c.tx_hash, TX.c.raw, TX.c.height, TX.c.position.label('tx_position'), TX.c.is_verified,
            TXO.c.txo_type, TXO.c.position.label('txo_position'), TXO.c.amount, TXO.c.script
        ]

        my_accounts = None
        if wallet is not None:
            my_accounts = select(AccountAddress.c.address).where(in_account(wallet.accounts))

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

        spent = TXI.alias('spent')
        if include_is_spent:
            select_columns.append((spent.c.txo_hash != None).label('is_spent'))

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

        rows = await self.select_txos(select_columns, spent=spent, **constraints)

        txos = []
        txs = {}
        for row in rows:
            if no_tx:
                txo = Output(
                    amount=row['amount'],
                    script=OutputScript(row['script']),
                    tx_ref=TXRefImmutable.from_hash(row['tx_hash'], row['height']),
                    position=row['txo_position']
                )
            else:
                if row['tx_hash'] not in txs:
                    txs[row['tx_hash']] = Transaction(
                        row['raw'], height=row['height'], position=row['tx_position'],
                        is_verified=bool(row['is_verified'])
                    )
                txo = txs[row['tx_hash']].outputs[row['txo_position']]
            if include_is_spent:
                txo.is_spent = bool(row['is_spent'])
            if include_is_my_input:
                txo.is_my_input = bool(row['is_my_input'])
            if include_is_my_output:
                txo.is_my_output = bool(row['is_my_output'])
            if include_is_my_input and include_is_my_output:
                if txo.is_my_input and txo.is_my_output and row['txo_type'] == TXO_TYPES['other']:
                    txo.is_internal_transfer = True
                else:
                    txo.is_internal_transfer = False
            if include_received_tips:
                txo.received_tips = row['received_tips']
            txos.append(txo)

        channel_hashes = set()
        for txo in txos:
            if txo.is_claim and txo.can_decode_claim:
                if txo.claim.is_signed:
                    channel_hashes.add(txo.claim.signing_channel_hash)
                if txo.claim.is_channel and wallet:
                    for account in wallet.accounts:
                        private_key = account.get_channel_private_key(
                            txo.claim.channel.public_key_bytes
                        )
                        if private_key:
                            txo.private_key = private_key
                            break

        if channel_hashes:
            channels = {
                txo.claim_hash: txo for txo in
                (await self.get_channels(
                    wallet=wallet,
                    claim_hash__in=channel_hashes,
                ))
            }
            for txo in txos:
                if txo.is_claim and txo.can_decode_claim:
                    txo.channel = channels.get(txo.claim.signing_channel_hash, None)

        return txos

    @staticmethod
    def _clean_txo_constraints_for_aggregation(constraints):
        constraints.pop('include_is_spent', None)
        constraints.pop('include_is_my_input', None)
        constraints.pop('include_is_my_output', None)
        constraints.pop('include_received_tips', None)
        constraints.pop('wallet', None)
        constraints.pop('resolve', None)
        constraints.pop('offset', None)
        constraints.pop('limit', None)
        constraints.pop('order_by', None)

    async def get_txo_count(self, **constraints):
        self._clean_txo_constraints_for_aggregation(constraints)
        count = await self.select_txos([func.count().label('total')], **constraints)
        return count[0]['total'] or 0

    async def get_txo_sum(self, **constraints):
        self._clean_txo_constraints_for_aggregation(constraints)
        result = await self.select_txos([func.sum(TXO.c.amount).label('total')], **constraints)
        return result[0]['total'] or 0

    async def get_txo_plot(self, start_day=None, days_back=0, end_day=None, days_after=None, **constraints):
        self._clean_txo_constraints_for_aggregation(constraints)
        if start_day is None:
            current_ordinal = self.ledger.headers.estimated_date(self.ledger.headers.height).toordinal()
            constraints['day__gte'] = current_ordinal - days_back
        else:
            constraints['day__gte'] = date.fromisoformat(start_day).toordinal()
            if end_day is not None:
                constraints['day__lte'] = date.fromisoformat(end_day).toordinal()
            elif days_after is not None:
                constraints['day__lte'] = constraints['day__gte'] + days_after
        plot = await self.select_txos(
            [TX.c.day, func.sum(TXO.c.amount).label('total')],
            group_by='day', order_by='day', **constraints
        )
        for row in plot:
            row['day'] = date.fromordinal(row['day'])
        return plot

    def get_utxos(self, **constraints):
        return self.get_txos(is_spent=False, **constraints)

    def get_utxo_count(self, **constraints):
        return self.get_txo_count(is_spent=False, **constraints)

    async def get_balance(self, wallet=None, accounts=None, **constraints):
        assert wallet or accounts, \
            "'wallet' or 'accounts' constraints required to calculate balance"
        constraints['accounts'] = accounts or wallet.accounts
        balance = await self.select_txos(
            [func.sum(TXO.c.amount).label('total')], is_spent=False, **constraints
        )
        return balance[0]['total'] or 0

    async def select_addresses(self, cols, **constraints):
        return await self.execute_fetchall(query2(
            [AccountAddress, PubkeyAddress],
            select(*cols).select_from(PubkeyAddress.join(AccountAddress)),
            **constraints
        ))

    async def get_addresses(self, cols=None, **constraints):
        if cols is None:
            cols = (
                PubkeyAddress.c.address,
                PubkeyAddress.c.history,
                PubkeyAddress.c.used_times,
                AccountAddress.c.account,
                AccountAddress.c.chain,
                AccountAddress.c.pubkey,
                AccountAddress.c.chain_code,
                AccountAddress.c.n,
                AccountAddress.c.depth
            )
        addresses = await self.select_addresses(cols, **constraints)
        if AccountAddress.c.pubkey in cols:
            for address in addresses:
                address['pubkey'] = PubKey(
                    self.ledger, bytes(address.pop('pubkey')), bytes(address.pop('chain_code')),
                    address.pop('n'), address.pop('depth')
                )
        return addresses

    async def get_address_count(self, cols=None, **constraints):
        count = await self.select_addresses([func.count().label('total')], **constraints)
        return count[0]['total'] or 0

    async def get_address(self, **constraints):
        addresses = await self.get_addresses(limit=1, **constraints)
        if addresses:
            return addresses[0]

    async def add_keys(self, account, chain, pubkeys):
        await self.execute_fetchall(
            insert_or_ignore(self.db, PubkeyAddress).values([{
                'address': k.address
            } for k in pubkeys])
        )
        await self.execute_fetchall(
            insert_or_ignore(self.db, AccountAddress).values([{
                'account': account.id,
                'address': k.address,
                'chain': chain,
                'pubkey': k.pubkey_bytes,
                'chain_code': k.chain_code,
                'n': k.n,
                'depth': k.depth
            } for k in pubkeys])
        )

    async def _set_address_history(self, address, history):
        await self.execute_fetchall(
            PubkeyAddress.update()
            .values(history=history, used_times=history.count(':')//2)
            .where(PubkeyAddress.c.address == address)
        )

    async def set_address_history(self, address, history):
        await self._set_address_history(address, history)

    @staticmethod
    def constrain_purchases(constraints):
        accounts = constraints.pop('accounts', None)
        assert accounts, "'accounts' argument required to find purchases"
        if not {'purchased_claim_hash', 'purchased_claim_hash__in'}.intersection(constraints):
            constraints['purchased_claim_hash__is_not_null'] = True
        constraints['tx_hash__in'] = (
            select(TXI.c.tx_hash).select_from(txi_join_account).where(in_account(accounts))
        )

    async def get_purchases(self, **constraints):
        self.constrain_purchases(constraints)
        return [tx.outputs[0] for tx in await self.get_transactions(**constraints)]

    def get_purchase_count(self, **constraints):
        self.constrain_purchases(constraints)
        return self.get_transaction_count(**constraints)

    @staticmethod
    def constrain_claims(constraints):
        if {'txo_type', 'txo_type__in'}.intersection(constraints):
            return
        claim_types = constraints.pop('claim_type', None)
        if claim_types:
            constrain_single_or_list(
                constraints, 'txo_type', claim_types, lambda x: TXO_TYPES[x]
            )
        else:
            constraints['txo_type__in'] = CLAIM_TYPES

    async def get_claims(self, **constraints) -> List[Output]:
        self.constrain_claims(constraints)
        return await self.get_utxos(**constraints)

    def get_claim_count(self, **constraints):
        self.constrain_claims(constraints)
        return self.get_utxo_count(**constraints)

    @staticmethod
    def constrain_streams(constraints):
        constraints['txo_type'] = TXO_TYPES['stream']

    def get_streams(self, **constraints):
        self.constrain_streams(constraints)
        return self.get_claims(**constraints)

    def get_stream_count(self, **constraints):
        self.constrain_streams(constraints)
        return self.get_claim_count(**constraints)

    @staticmethod
    def constrain_channels(constraints):
        constraints['txo_type'] = TXO_TYPES['channel']

    def get_channels(self, **constraints):
        self.constrain_channels(constraints)
        return self.get_claims(**constraints)

    def get_channel_count(self, **constraints):
        self.constrain_channels(constraints)
        return self.get_claim_count(**constraints)

    @staticmethod
    def constrain_supports(constraints):
        constraints['txo_type'] = TXO_TYPES['support']

    def get_supports(self, **constraints):
        self.constrain_supports(constraints)
        return self.get_utxos(**constraints)

    def get_support_count(self, **constraints):
        self.constrain_supports(constraints)
        return self.get_utxo_count(**constraints)

    @staticmethod
    def constrain_collections(constraints):
        constraints['txo_type'] = TXO_TYPES['collection']

    def get_collections(self, **constraints):
        self.constrain_collections(constraints)
        return self.get_utxos(**constraints)

    def get_collection_count(self, **constraints):
        self.constrain_collections(constraints)
        return self.get_utxo_count(**constraints)

    async def release_all_outputs(self, account):
        await self.execute_fetchall(
            TXO.update().values(is_reserved=False).where(
                (TXO.c.is_reserved == True) &
                (TXO.c.address.in_(select(AccountAddress.c.address).where(in_account(account))))
            )
        )

    def get_supports_summary(self, **constraints):
        return self.get_txos(
            txo_type=TXO_TYPES['support'],
            is_spent=False, is_my_output=True,
            include_is_my_input=True,
            no_tx=True,
            **constraints
        )
