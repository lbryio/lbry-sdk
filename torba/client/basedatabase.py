import logging
import asyncio
from asyncio import wrap_future
from concurrent.futures.thread import ThreadPoolExecutor

from typing import Tuple, List, Union, Callable, Any, Awaitable, Iterable

import sqlite3

from torba.client.basetransaction import BaseTransaction
from torba.client.baseaccount import BaseAccount

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

    def executemany(self, sql: str, params: Iterable):
        def __executemany_in_a_transaction(conn: sqlite3.Connection, *args, **kwargs):
            return conn.executemany(*args, **kwargs)
        return self.run(__executemany_in_a_transaction, sql, params)

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

    def run(self, fun, *args, **kwargs) -> Awaitable:
        return wrap_future(self.executor.submit(self.__run_transaction, fun, *args, **kwargs))

    def __run_transaction(self, fun: Callable[[sqlite3.Connection, Any, Any], Any], *args, **kwargs):
        self.connection.execute('begin')
        try:
            result = fun(self.connection, *args, **kwargs)  # type: ignore
            self.connection.commit()
            return result
        except (Exception, OSError): # as e:
            #log.exception('Error running transaction:', exc_info=e)
            self.connection.rollback()
            raise

    def run_with_foreign_keys_disabled(self, fun, *args, **kwargs) -> Awaitable:
        return wrap_future(
            self.executor.submit(self.__run_transaction_with_foreign_keys_disabled, fun, *args, **kwargs)
        )

    def __run_transaction_with_foreign_keys_disabled(self,
                                                     fun: Callable[[sqlite3.Connection, Any, Any], Any],
                                                     *args, **kwargs):
        foreign_keys_enabled, = self.connection.execute("pragma foreign_keys").fetchone()
        if not foreign_keys_enabled:
            raise sqlite3.IntegrityError("foreign keys are disabled, use `AIOSQLite.run` instead")
        try:
            self.connection.execute('pragma foreign_keys=off')
            return self.__run_transaction(fun, *args, **kwargs)
        finally:
            self.connection.execute('pragma foreign_keys=on')


def constraints_to_sql(constraints, joiner=' AND ', prepend_key=''):
    sql, values = [], {}
    for key, constraint in constraints.items():
        tag = '0'
        if '#' in key:
            key, tag = key[:key.index('#')], key[key.index('#')+1:]
        col, op, key = key, '=', key.replace('.', '_')
        if key.startswith('$'):
            values[key] = constraint
            continue
        elif key.endswith('__not'):
            col, op = col[:-len('__not')], '!='
        elif key.endswith('__is_null'):
            col = col[:-len('__is_null')]
            sql.append(f'{col} IS NULL')
            continue
        elif key.endswith('__is_not_null'):
            col = col[:-len('__is_not_null')]
            sql.append(f'{col} IS NOT NULL')
            continue
        elif key.endswith('__lt'):
            col, op = col[:-len('__lt')], '<'
        elif key.endswith('__lte'):
            col, op = col[:-len('__lte')], '<='
        elif key.endswith('__gt'):
            col, op = col[:-len('__gt')], '>'
        elif key.endswith('__gte'):
            col, op = col[:-len('__gte')], '>='
        elif key.endswith('__like'):
            col, op = col[:-len('__like')], 'LIKE'
        elif key.endswith('__not_like'):
            col, op = col[:-len('__not_like')], 'NOT LIKE'
        elif key.endswith('__in') or key.endswith('__not_in'):
            if key.endswith('__in'):
                col, op = col[:-len('__in')], 'IN'
            else:
                col, op = col[:-len('__not_in')], 'NOT IN'
            if constraint:
                if isinstance(constraint, (list, set, tuple)):
                    keys = []
                    for i, val in enumerate(constraint):
                        keys.append(f':{key}{tag}_{i}')
                        values[f'{key}{tag}_{i}'] = val
                    sql.append(f'{col} {op} ({", ".join(keys)})')
                elif isinstance(constraint, str):
                    sql.append(f'{col} {op} ({constraint})')
                else:
                    raise ValueError(f"{col} requires a list, set or string as constraint value.")
            continue
        elif key.endswith('__any') or key.endswith('__or'):
            where, subvalues = constraints_to_sql(constraint, ' OR ', key+tag+'_')
            sql.append(f'({where})')
            values.update(subvalues)
            continue
        elif key.endswith('__and'):
            where, subvalues = constraints_to_sql(constraint, ' AND ', key+tag+'_')
            sql.append(f'({where})')
            values.update(subvalues)
            continue
        sql.append(f'{col} {op} :{prepend_key}{key}{tag}')
        values[prepend_key+key+tag] = constraint
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

    if order_by:
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
    def _insert_sql(table: str, data: dict, ignore_duplicate: bool = False) -> Tuple[str, List]:
        columns, values = [], []
        for column, value in data.items():
            columns.append(column)
            values.append(value)
        or_ignore = ""
        if ignore_duplicate:
            or_ignore = " OR IGNORE"
        sql = "INSERT{} INTO {} ({}) VALUES ({})".format(
            or_ignore, table, ', '.join(columns), ', '.join(['?'] * len(values))
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

    async def insert_transaction(self, tx):
        await self.db.execute(*self._insert_sql('tx', {
            'txid': tx.id,
            'raw': sqlite3.Binary(tx.raw),
            'height': tx.height,
            'position': tx.position,
            'is_verified': tx.is_verified
        }))

    async def update_transaction(self, tx):
        await self.db.execute(*self._update_sql("tx", {
            'height': tx.height, 'position': tx.position, 'is_verified': tx.is_verified
        }, 'txid = ?', (tx.id,)))

    def save_transaction_io(self, tx: BaseTransaction, address, txhash, history):

        def _transaction(conn: sqlite3.Connection, tx: BaseTransaction, address, txhash, history):

            for txo in tx.outputs:
                if txo.script.is_pay_pubkey_hash and txo.script.values['pubkey_hash'] == txhash:
                    conn.execute(*self._insert_sql(
                        "txo", self.txo_to_row(tx, address, txo), ignore_duplicate=True
                    ))
                elif txo.script.is_pay_script_hash:
                    # TODO: implement script hash payments
                    log.warning('Database.save_transaction_io: pay script hash is not implemented!')

            for txi in tx.inputs:
                if txi.txo_ref.txo is not None:
                    txo = txi.txo_ref.txo
                    if txo.get_address(self.ledger) == address:
                        conn.execute(*self._insert_sql("txi", {
                            'txid': tx.id,
                            'txoid': txo.id,
                            'address': address,
                        }, ignore_duplicate=True))

            conn.execute(
                "UPDATE pubkey_address SET history = ?, used_times = ? WHERE address = ?",
                (history, history.count(':')//2, address)
            )

        return self.db.run(_transaction, tx, address, txhash, history)

    async def reserve_outputs(self, txos, is_reserved=True):
        txoids = ((is_reserved, txo.id) for txo in txos)
        await self.db.executemany("UPDATE txo SET is_reserved = ? WHERE txoid = ?", txoids)

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
            order_by=["height=0 DESC", "height DESC", "position DESC"],
            **constraints
        )

        if not tx_rows:
            return []

        txids, txs, txi_txoids = [], [], []
        for row in tx_rows:
            txids.append(row[0])
            txs.append(self.ledger.transaction_class(
                raw=row[1], height=row[2], position=row[3], is_verified=bool(row[4])
            ))
            for txi in txs[-1].inputs:
                txi_txoids.append(txi.txo_ref.id)

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
                txoid__in=txi_txoids
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
        if 'order_by' not in constraints:
            constraints['order_by'] = ["tx.height=0 DESC", "tx.height DESC", "tx.position DESC"]
        rows = await self.select_txos(
            "tx.txid, raw, tx.height, tx.position, tx.is_verified, txo.position, chain, account",
            **constraints
        )
        txos = []
        txs = {}
        for row in rows:
            if row[0] not in txs:
                txs[row[0]] = self.ledger.transaction_class(
                    row[1], height=row[2], position=row[3], is_verified=row[4]
                )
            txo = txs[row[0]].outputs[row[5]]
            txo.is_change = row[6] == 1
            txo.is_my_account = row[7] == my_account
            txos.append(txo)
        return txos

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
        await self.db.executemany(
            "insert into pubkey_address (address, account, chain, position, pubkey) values (?, ?, ?, ?, ?)",
            ((pubkey.address, account.public_key.address, chain,
              position, sqlite3.Binary(pubkey.pubkey_bytes))
             for position, pubkey in keys)
        )

    async def _set_address_history(self, address, history):
        await self.db.execute(
            "UPDATE pubkey_address SET history = ?, used_times = ? WHERE address = ?",
            (history, history.count(':')//2, address)
        )

    async def set_address_history(self, address, history):
        await self._set_address_history(address, history)
