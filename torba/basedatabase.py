import logging
import asyncio
from asyncio import wrap_future
from concurrent.futures.thread import ThreadPoolExecutor

from typing import Tuple, List, Union, Callable, Any, Awaitable, Iterable

import sqlite3

from torba.hash import TXRefImmutable
from torba.basetransaction import BaseTransaction
from torba.baseaccount import BaseAccount

log = logging.getLogger(__name__)


class AIOSQLite:

    def __init__(self):
        # has to be single threaded as there is no mapping of thread:connection
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.connection: sqlite3.Connection = None

    @classmethod
    async def connect(cls, path: Union[bytes, str], *args, **kwargs):
        db = cls()
        db.connection = await wrap_future(db.executor.submit(sqlite3.connect, path, *args, **kwargs))
        return db

    async def close(self):
        def __close(conn):
            self.executor.submit(conn.close)
            self.executor.shutdown(wait=True)
        conn = self.connection
        self.connection = None
        return asyncio.get_event_loop_policy().get_event_loop().call_later(0.01, __close, conn)

    def executescript(self, script: str) -> Awaitable:
        return wrap_future(self.executor.submit(self.connection.executescript, script))

    def execute_fetchall(self, sql: str, parameters: Iterable = None) -> Awaitable[Iterable[sqlite3.Row]]:
        parameters = parameters if parameters is not None else []
        def __fetchall(conn: sqlite3.Connection, *args, **kwargs):
            return conn.execute(*args, **kwargs).fetchall()
        return wrap_future(self.executor.submit(__fetchall, self.connection, sql, parameters))

    def execute(self, sql: str, parameters: Iterable = None) -> Awaitable[sqlite3.Cursor]:
        parameters = parameters if parameters is not None else []
        return self.run(lambda conn, sql, parameters: conn.execute(sql, parameters), sql, parameters)

    def run(self, fun: Callable[[sqlite3.Connection, Any, Any], Any], *args, **kwargs) -> Awaitable:
        return wrap_future(self.executor.submit(self.__run_transaction, fun, *args, **kwargs))

    def __run_transaction(self, fun: Callable[[sqlite3.Connection, Any, Any], Any], *args, **kwargs):
        self.connection.execute('begin')
        try:
            fun(self.connection, *args, **kwargs)  # type: ignore
        except (Exception, OSError):
            self.connection.rollback()
            raise
        else:
            self.connection.commit()


def constraints_to_sql(constraints, joiner=' AND ', prepend_key=''):
    sql, values = [], {}
    for key, constraint in constraints.items():
        col, op, key = key, '=', key.replace('.', '_')
        if key.startswith('$'):
            values[key] = constraint
            continue
        elif key.endswith('__not'):
            col, op = col[:-len('__not')], '!='
        elif key.endswith('__lt'):
            col, op = col[:-len('__lt')], '<'
        elif key.endswith('__lte'):
            col, op = col[:-len('__lte')], '<='
        elif key.endswith('__gt'):
            col, op = col[:-len('__gt')], '>'
        elif key.endswith('__like'):
            col, op = col[:-len('__like')], 'LIKE'
        elif key.endswith('__in') or key.endswith('__not_in'):
            if key.endswith('__in'):
                col, op = col[:-len('__in')], 'IN'
            else:
                col, op = col[:-len('__not_in')], 'NOT IN'
            if isinstance(constraint, (list, set)):
                items = ', '.join(
                    "'{}'".format(item) if isinstance(item, str) else str(item)
                    for item in constraint
                )
            elif isinstance(constraint, str):
                items = constraint
            else:
                raise ValueError("{} requires a list, set or string as constraint value.".format(col))
            sql.append('{} {} ({})'.format(col, op, items))
            continue
        elif key.endswith('__any'):
            where, subvalues = constraints_to_sql(constraint, ' OR ', key+'_')
            sql.append('({})'.format(where))
            values.update(subvalues)
            continue
        sql.append('{} {} :{}'.format(col, op, prepend_key+key))
        values[prepend_key+key] = constraint
    return joiner.join(sql) if sql else '', values


def query(select, **constraints):
    sql = [select]
    limit = constraints.pop('limit', None)
    offset = constraints.pop('offset', None)
    order_by = constraints.pop('order_by', None)

    constraints.pop('my_account', None)
    account = constraints.pop('account', None)
    if account is not None:
        if not isinstance(account, list):
            account = [account]
        constraints['account__in'] = [
            (a.public_key.address if isinstance(a, BaseAccount) else a) for a in account
        ]

    where, values = constraints_to_sql(constraints)
    if where:
        sql.append('WHERE')
        sql.append(where)

    if order_by is not None:
        sql.append('ORDER BY')
        if isinstance(order_by, str):
            sql.append(order_by)
        elif isinstance(order_by, list):
            sql.append(', '.join(order_by))
        else:
            raise ValueError("order_by must be string or list")

    if limit is not None:
        sql.append('LIMIT {}'.format(limit))

    if offset is not None:
        sql.append('OFFSET {}'.format(offset))

    return ' '.join(sql), values


def rows_to_dict(rows, fields):
    if rows:
        return [dict(zip(fields, r)) for r in rows]
    else:
        return []


class SQLiteMixin:

    CREATE_TABLES_QUERY: str

    def __init__(self, path):
        self._db_path = path
        self.db: AIOSQLite = None
        self.ledger = None

    async def open(self):
        log.info("connecting to database: %s", self._db_path)
        self.db = await AIOSQLite.connect(self._db_path)
        await self.db.executescript(self.CREATE_TABLES_QUERY)

    async def close(self):
        await self.db.close()

    @staticmethod
    def _insert_sql(table: str, data: dict) -> Tuple[str, List]:
        columns, values = [], []
        for column, value in data.items():
            columns.append(column)
            values.append(value)
        sql = "INSERT INTO {} ({}) VALUES ({})".format(
            table, ', '.join(columns), ', '.join(['?'] * len(values))
        )
        return sql, values

    @staticmethod
    def _update_sql(table: str, data: dict, where: str,
                    constraints: Union[list, tuple]) -> Tuple[str, list]:
        columns, values = [], []
        for column, value in data.items():
            columns.append("{} = ?".format(column))
            values.append(value)
        values.extend(constraints)
        sql = "UPDATE {} SET {} WHERE {}".format(
            table, ', '.join(columns), where
        )
        return sql, values


class BaseDatabase(SQLiteMixin):

    PRAGMAS = """
        pragma journal_mode=WAL;
    """

    CREATE_PUBKEY_ADDRESS_TABLE = """
        create table if not exists pubkey_address (
            address text primary key,
            account text not null,
            chain integer not null,
            position integer not null,
            pubkey blob not null,
            history text,
            used_times integer not null default 0
        );
    """
    CREATE_PUBKEY_ADDRESS_INDEX = """
        create index if not exists pubkey_address_account_idx on pubkey_address (account);
    """

    CREATE_TX_TABLE = """
        create table if not exists tx (
            txid text primary key,
            raw blob not null,
            height integer not null,
            position integer not null,
            is_verified boolean not null default 0
        );
    """

    CREATE_TXO_TABLE = """
        create table if not exists txo (
            txid text references tx,
            txoid text primary key,
            address text references pubkey_address,
            position integer not null,
            amount integer not null,
            script blob not null,
            is_reserved boolean not null default 0
        );
    """
    CREATE_TXO_INDEX = """
        create index if not exists txo_address_idx on txo (address);
    """

    CREATE_TXI_TABLE = """
        create table if not exists txi (
            txid text references tx,
            txoid text references txo,
            address text references pubkey_address
        );
    """
    CREATE_TXI_INDEX = """
        create index if not exists txi_address_idx on txi (address);
        create index if not exists txi_txoid_idx on txi (txoid);
    """

    CREATE_TABLES_QUERY = (
        PRAGMAS +
        CREATE_TX_TABLE +
        CREATE_PUBKEY_ADDRESS_TABLE +
        CREATE_PUBKEY_ADDRESS_INDEX +
        CREATE_TXO_TABLE +
        CREATE_TXO_INDEX +
        CREATE_TXI_TABLE +
        CREATE_TXI_INDEX
    )

    @staticmethod
    def txo_to_row(tx, address, txo):
        return {
            'txid': tx.id,
            'txoid': txo.id,
            'address': address,
            'position': txo.position,
            'amount': txo.amount,
            'script': sqlite3.Binary(txo.script.source)
        }

    async def save_transaction_io(self, save_tx, tx: BaseTransaction, address, txhash, history):

        if save_tx == 'insert':
            await self.db.execute(*self._insert_sql('tx', {
                'txid': tx.id,
                'raw': sqlite3.Binary(tx.raw),
                'height': tx.height,
                'position': tx.position,
                'is_verified': tx.is_verified
            }))
        elif save_tx == 'update':
            await self.db.execute(*self._update_sql("tx", {
                'height': tx.height, 'position': tx.position, 'is_verified': tx.is_verified
            }, 'txid = ?', (tx.id,)))

        existing_txos = [r[0] for r in await self.db.execute_fetchall(*query(
            "SELECT position FROM txo", txid=tx.id
        ))]

        for txo in tx.outputs:
            if txo.position in existing_txos:
                continue
            if txo.script.is_pay_pubkey_hash and txo.script.values['pubkey_hash'] == txhash:
                await self.db.execute(*self._insert_sql("txo", self.txo_to_row(tx, address, txo)))
            elif txo.script.is_pay_script_hash:
                # TODO: implement script hash payments
                log.warning('Database.save_transaction_io: pay script hash is not implemented!')

        # lookup the address associated with each TXI (via its TXO)
        txoid_to_address = {r[0]: r[1] for r in await self.db.execute_fetchall(*query(
            "SELECT txoid, address FROM txo", txoid__in=[txi.txo_ref.id for txi in tx.inputs]
        ))}

        # list of TXIs that have already been added
        existing_txis = [r[0] for r in await self.db.execute_fetchall(*query(
            "SELECT txoid FROM txi", txid=tx.id
        ))]

        for txi in tx.inputs:
            txoid = txi.txo_ref.id
            new_txi = txoid not in existing_txis
            address_matches = txoid_to_address.get(txoid) == address
            if new_txi and address_matches:
                await self.db.execute(*self._insert_sql("txi", {
                    'txid': tx.id,
                    'txoid': txoid,
                    'address': address,
                }))

        await self._set_address_history(address, history)

    async def reserve_outputs(self, txos, is_reserved=True):
        txoids = [txo.id for txo in txos]
        await self.db.execute(
            "UPDATE txo SET is_reserved = ? WHERE txoid IN ({})".format(
                ', '.join(['?']*len(txoids))
            ), [is_reserved]+txoids
        )

    async def release_outputs(self, txos):
        await self.reserve_outputs(txos, is_reserved=False)

    async def rewind_blockchain(self, above_height):  # pylint: disable=no-self-use
        # TODO:
        # 1. delete transactions above_height
        # 2. update address histories removing deleted TXs
        return True

    async def select_transactions(self, cols, account=None, **constraints):
        if 'txid' not in constraints and account is not None:
            constraints['$account'] = account.public_key.address
            constraints['txid__in'] = """
                SELECT txo.txid FROM txo
                JOIN pubkey_address USING (address) WHERE pubkey_address.account = :$account
              UNION
                SELECT txi.txid FROM txi
                JOIN pubkey_address USING (address) WHERE pubkey_address.account = :$account
            """
        return await self.db.execute_fetchall(
            *query("SELECT {} FROM tx".format(cols), **constraints)
        )

    async def get_transactions(self, my_account=None, **constraints):
        my_account = my_account or constraints.get('account', None)

        tx_rows = await self.select_transactions(
            'txid, raw, height, position, is_verified',
            order_by=["height DESC", "position DESC"],
            **constraints
        )

        if not tx_rows:
            return []

        txids, txs = [], []
        for row in tx_rows:
            txids.append(row[0])
            txs.append(self.ledger.transaction_class(
                raw=row[1], height=row[2], position=row[3], is_verified=bool(row[4])
            ))

        annotated_txos = {
            txo.id: txo for txo in
            (await self.get_txos(
                my_account=my_account,
                txid__in=txids
            ))
        }

        referenced_txos = {
            txo.id: txo for txo in
            (await self.get_txos(
                my_account=my_account,
                txoid__in=query("SELECT txoid FROM txi", **{'txid__in': txids})[0]
            ))
        }

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
                    txo.update_annotations(None)

        return txs

    async def get_transaction_count(self, **constraints):
        constraints.pop('offset', None)
        constraints.pop('limit', None)
        constraints.pop('order_by', None)
        count = await self.select_transactions('count(*)', **constraints)
        return count[0][0]

    async def get_transaction(self, **constraints):
        txs = await self.get_transactions(limit=1, **constraints)
        if txs:
            return txs[0]

    async def select_txos(self, cols, **constraints):
        return await self.db.execute_fetchall(*query(
            "SELECT {} FROM txo"
            " JOIN pubkey_address USING (address)"
            " JOIN tx USING (txid)".format(cols), **constraints
        ))

    async def get_txos(self, my_account=None, **constraints):
        my_account = my_account or constraints.get('account', None)
        if isinstance(my_account, BaseAccount):
            my_account = my_account.public_key.address
        rows = await self.select_txos(
            "amount, script, txid, tx.height, txo.position, chain, account", **constraints
        )
        output_class = self.ledger.transaction_class.output_class
        return [
            output_class(
                amount=row[0],
                script=output_class.script_class(row[1]),
                tx_ref=TXRefImmutable.from_id(row[2], row[3]),
                position=row[4],
                is_change=row[5] == 1,
                is_my_account=row[6] == my_account
            ) for row in rows
        ]

    async def get_txo_count(self, **constraints):
        constraints.pop('offset', None)
        constraints.pop('limit', None)
        constraints.pop('order_by', None)
        count = await self.select_txos('count(*)', **constraints)
        return count[0][0]

    @staticmethod
    def constrain_utxo(constraints):
        constraints['is_reserved'] = False
        constraints['txoid__not_in'] = "SELECT txoid FROM txi"

    def get_utxos(self, **constraints):
        self.constrain_utxo(constraints)
        return self.get_txos(**constraints)

    def get_utxo_count(self, **constraints):
        self.constrain_utxo(constraints)
        return self.get_txo_count(**constraints)

    async def get_balance(self, **constraints):
        self.constrain_utxo(constraints)
        balance = await self.select_txos('SUM(amount)', **constraints)
        return balance[0][0] or 0

    async def select_addresses(self, cols, **constraints):
        return await self.db.execute_fetchall(*query(
            "SELECT {} FROM pubkey_address".format(cols), **constraints
        ))

    async def get_addresses(self, cols=('address', 'account', 'chain', 'position', 'used_times'),
                            **constraints):
        addresses = await self.select_addresses(', '.join(cols), **constraints)
        return rows_to_dict(addresses, cols)

    async def get_address_count(self, **constraints):
        count = await self.select_addresses('count(*)', **constraints)
        return count[0][0]

    async def get_address(self, **constraints):
        addresses = await self.get_addresses(
            cols=('address', 'account', 'chain', 'position', 'pubkey', 'history', 'used_times'),
            limit=1, **constraints
        )
        if addresses:
            return addresses[0]

    async def add_keys(self, account, chain, keys):
        sql = (
            "insert into pubkey_address "
            "(address, account, chain, position, pubkey) "
            "values "
        ) + ', '.join(['(?, ?, ?, ?, ?)'] * len(keys))
        values = []
        for position, pubkey in keys:
            values.extend((
                pubkey.address, account.public_key.address, chain, position,
                sqlite3.Binary(pubkey.pubkey_bytes)
            ))
        await self.db.execute(sql, values)

    async def _set_address_history(self, address, history):
        await self.db.execute(
            "UPDATE pubkey_address SET history = ?, used_times = ? WHERE address = ?",
            (history, history.count(':')//2, address)
        )

    async def set_address_history(self, address, history):
        await self._set_address_history(address, history)
