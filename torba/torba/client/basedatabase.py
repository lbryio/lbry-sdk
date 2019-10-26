import logging
import asyncio
from binascii import hexlify
from concurrent.futures.thread import ThreadPoolExecutor

from typing import Tuple, List, Union, Callable, Any, Awaitable, Iterable, Dict, Optional

import sqlite3

from torba.client.basetransaction import BaseTransaction, TXRefImmutable
from torba.client.bip32 import PubKey

log = logging.getLogger(__name__)


class AIOSQLite:

    def __init__(self):
        # has to be single threaded as there is no mapping of thread:connection
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.connection: sqlite3.Connection = None
        self._closing = False

    @classmethod
    async def connect(cls, path: Union[bytes, str], *args, **kwargs):
        def _connect():
            return sqlite3.connect(path, *args, **kwargs)
        db = cls()
        db.connection = await asyncio.get_event_loop().run_in_executor(db.executor, _connect)
        return db

    async def close(self):
        if self._closing:
            return
        self._closing = True
        await asyncio.get_event_loop().run_in_executor(self.executor, self.connection.close)
        self.executor.shutdown(wait=True)
        self.connection = None

    def executemany(self, sql: str, params: Iterable):
        params = params if params is not None else []
        # this fetchall is needed to prevent SQLITE_MISUSE
        return self.run(lambda conn: conn.executemany(sql, params).fetchall())

    def executescript(self, script: str) -> Awaitable:
        return self.run(lambda conn: conn.executescript(script))

    def execute_fetchall(self, sql: str, parameters: Iterable = None) -> Awaitable[Iterable[sqlite3.Row]]:
        parameters = parameters if parameters is not None else []
        return self.run(lambda conn: conn.execute(sql, parameters).fetchall())

    def execute_fetchone(self, sql: str, parameters: Iterable = None) -> Awaitable[Iterable[sqlite3.Row]]:
        parameters = parameters if parameters is not None else []
        return self.run(lambda conn: conn.execute(sql, parameters).fetchone())

    def execute(self, sql: str, parameters: Iterable = None) -> Awaitable[sqlite3.Cursor]:
        parameters = parameters if parameters is not None else []
        return self.run(lambda conn: conn.execute(sql, parameters))

    def run(self, fun, *args, **kwargs) -> Awaitable:
        return asyncio.get_event_loop().run_in_executor(
            self.executor, lambda: self.__run_transaction(fun, *args, **kwargs)
        )

    def __run_transaction(self, fun: Callable[[sqlite3.Connection, Any, Any], Any], *args, **kwargs):
        self.connection.execute('begin')
        try:
            result = fun(self.connection, *args, **kwargs)  # type: ignore
            self.connection.commit()
            return result
        except (Exception, OSError) as e:
            log.exception('Error running transaction:', exc_info=e)
            self.connection.rollback()
            log.warning("rolled back")
            raise

    def run_with_foreign_keys_disabled(self, fun, *args, **kwargs) -> Awaitable:
        return asyncio.get_event_loop().run_in_executor(
            self.executor, self.__run_transaction_with_foreign_keys_disabled, fun, args, kwargs
        )

    def __run_transaction_with_foreign_keys_disabled(self,
                                                     fun: Callable[[sqlite3.Connection, Any, Any], Any],
                                                     args, kwargs):
        foreign_keys_enabled, = self.connection.execute("pragma foreign_keys").fetchone()
        if not foreign_keys_enabled:
            raise sqlite3.IntegrityError("foreign keys are disabled, use `AIOSQLite.run` instead")
        try:
            self.connection.execute('pragma foreign_keys=off').fetchone()
            return self.__run_transaction(fun, *args, **kwargs)
        finally:
            self.connection.execute('pragma foreign_keys=on').fetchone()


def constraints_to_sql(constraints, joiner=' AND ', prepend_key=''):
    sql, values = [], {}
    for key, constraint in constraints.items():
        tag = '0'
        if '#' in key:
            key, tag = key[:key.index('#')], key[key.index('#')+1:]
        col, op, key = key, '=', key.replace('.', '_')
        if not key:
            sql.append(constraint)
            continue
        if key.startswith('$'):
            values[key] = constraint
            continue
        if key.endswith('__not'):
            col, op = col[:-len('__not')], '!='
        elif key.endswith('__is_null'):
            col = col[:-len('__is_null')]
            sql.append(f'{col} IS NULL')
            continue
        if key.endswith('__is_not_null'):
            col = col[:-len('__is_not_null')]
            sql.append(f'{col} IS NOT NULL')
            continue
        if key.endswith('__lt'):
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
        if key.endswith('__and'):
            where, subvalues = constraints_to_sql(constraint, ' AND ', key+tag+'_')
            sql.append(f'({where})')
            values.update(subvalues)
            continue
        sql.append(f'{col} {op} :{prepend_key}{key}{tag}')
        values[prepend_key+key+tag] = constraint
    return joiner.join(sql) if sql else '', values


def query(select, **constraints) -> Tuple[str, Dict[str, Any]]:
    sql = [select]
    limit = constraints.pop('limit', None)
    offset = constraints.pop('offset', None)
    order_by = constraints.pop('order_by', None)

    accounts = constraints.pop('accounts', [])
    if accounts:
        constraints['account__in'] = [a.public_key.address for a in accounts]

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
        sql.append(f'LIMIT {limit}')

    if offset is not None:
        sql.append(f'OFFSET {offset}')

    return ' '.join(sql), values


def interpolate(sql, values):
    for k in sorted(values.keys(), reverse=True):
        value = values[k]
        if isinstance(value, memoryview):
            value = f"X'{hexlify(bytes(value)).decode()}'"
        elif isinstance(value, str):
            value = f"'{value}'"
        else:
            value = str(value)
        sql = sql.replace(f":{k}", value)
    return sql


def rows_to_dict(rows, fields):
    if rows:
        return [dict(zip(fields, r)) for r in rows]
    else:
        return []


class SQLiteMixin:

    SCHEMA_VERSION: Optional[str] = None
    CREATE_TABLES_QUERY: str
    MAX_QUERY_VARIABLES = 900

    CREATE_VERSION_TABLE = """
        create table if not exists version (
            version text
        );
    """

    def __init__(self, path):
        self._db_path = path
        self.db: AIOSQLite = None
        self.ledger = None

    async def open(self):
        log.info("connecting to database: %s", self._db_path)
        self.db = await AIOSQLite.connect(self._db_path, isolation_level=None)
        if self.SCHEMA_VERSION:
            tables = [t[0] for t in await self.db.execute_fetchall(
                "SELECT name FROM sqlite_master WHERE type='table';"
            )]
            if tables:
                if 'version' in tables:
                    version = await self.db.execute_fetchone("SELECT version FROM version LIMIT 1;")
                    if version == (self.SCHEMA_VERSION,):
                        return
                await self.db.executescript('\n'.join(
                    f"DROP TABLE {table};" for table in tables
                ))
            await self.db.execute(self.CREATE_VERSION_TABLE)
            await self.db.execute("INSERT INTO version VALUES (?)", (self.SCHEMA_VERSION,))
        await self.db.executescript(self.CREATE_TABLES_QUERY)

    async def close(self):
        await self.db.close()

    @staticmethod
    def _insert_sql(table: str, data: dict, ignore_duplicate: bool = False,
                    replace: bool = False) -> Tuple[str, List]:
        columns, values = [], []
        for column, value in data.items():
            columns.append(column)
            values.append(value)
        policy = ""
        if ignore_duplicate:
            policy = " OR IGNORE"
        if replace:
            policy = " OR REPLACE"
        sql = "INSERT{} INTO {} ({}) VALUES ({})".format(
            policy, table, ', '.join(columns), ', '.join(['?'] * len(values))
        )
        return sql, values

    @staticmethod
    def _update_sql(table: str, data: dict, where: str,
                    constraints: Union[list, tuple]) -> Tuple[str, list]:
        columns, values = [], []
        for column, value in data.items():
            columns.append(f"{column} = ?")
            values.append(value)
        values.extend(constraints)
        sql = "UPDATE {} SET {} WHERE {}".format(
            table, ', '.join(columns), where
        )
        return sql, values


class BaseDatabase(SQLiteMixin):

    SCHEMA_VERSION = "1.1"

    PRAGMAS = """
        pragma journal_mode=WAL;
    """

    CREATE_ACCOUNT_TABLE = """
        create table if not exists account_address (
            account text not null,
            address text not null,
            chain integer not null,
            pubkey blob not null,
            chain_code blob not null,
            n integer not null,
            depth integer not null,
            primary key (account, address)
        );
        create index if not exists address_account_idx on account_address (address, account);
    """

    CREATE_PUBKEY_ADDRESS_TABLE = """
        create table if not exists pubkey_address (
            address text primary key,
            history text,
            used_times integer not null default 0
        );
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
        create index if not exists txo_address_idx on txo (address);
    """

    CREATE_TXI_TABLE = """
        create table if not exists txi (
            txid text references tx,
            txoid text references txo,
            address text references pubkey_address
        );
        create index if not exists txi_address_idx on txi (address);
        create index if not exists txi_txoid_idx on txi (txoid);
    """

    CREATE_TABLES_QUERY = (
        PRAGMAS +
        CREATE_ACCOUNT_TABLE +
        CREATE_PUBKEY_ADDRESS_TABLE +
        CREATE_TX_TABLE +
        CREATE_TXO_TABLE +
        CREATE_TXI_TABLE
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

    @staticmethod
    def tx_to_row(tx):
        return {
            'txid': tx.id,
            'raw': sqlite3.Binary(tx.raw),
            'height': tx.height,
            'position': tx.position,
            'is_verified': tx.is_verified
        }

    async def insert_transaction(self, tx):
        await self.db.execute_fetchall(*self._insert_sql('tx', self.tx_to_row(tx)))

    async def update_transaction(self, tx):
        await self.db.execute_fetchall(*self._update_sql("tx", {
            'height': tx.height, 'position': tx.position, 'is_verified': tx.is_verified
        }, 'txid = ?', (tx.id,)))

    def _transaction_io(self, conn: sqlite3.Connection, tx: BaseTransaction, address, txhash, history):
        conn.execute(*self._insert_sql('tx', self.tx_to_row(tx), replace=True))

        for txo in tx.outputs:
            if txo.script.is_pay_pubkey_hash and txo.script.values['pubkey_hash'] == txhash:
                conn.execute(*self._insert_sql(
                    "txo", self.txo_to_row(tx, address, txo), ignore_duplicate=True
                )).fetchall()
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
                    }, ignore_duplicate=True)).fetchall()

        conn.execute(
            "UPDATE pubkey_address SET history = ?, used_times = ? WHERE address = ?",
            (history, history.count(':') // 2, address)
        )

    def save_transaction_io(self, tx: BaseTransaction, address, txhash, history):
        return self.db.run(self._transaction_io, tx, address, txhash, history)

    def save_transaction_io_batch(self, txs: Iterable[BaseTransaction], address, txhash, history):
        def __many(conn):
            for tx in txs:
                self._transaction_io(conn, tx, address, txhash, history)
        return self.db.run(__many)

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

    async def select_transactions(self, cols, accounts=None, **constraints):
        if not set(constraints) & {'txid', 'txid__in'}:
            assert accounts, "'accounts' argument required when no 'txid' constraint is present"
            constraints.update({
                f'$account{i}': a.public_key.address for i, a in enumerate(accounts)
            })
            account_values = ', '.join([f':$account{i}' for i in range(len(accounts))])
            where = f" WHERE account_address.account IN ({account_values})"
            constraints['txid__in'] = f"""
                SELECT txo.txid FROM txo JOIN account_address USING (address) {where}
              UNION
                SELECT txi.txid FROM txi JOIN account_address USING (address) {where}
            """
        return await self.db.execute_fetchall(
            *query("SELECT {} FROM tx".format(cols), **constraints)
        )

    async def get_transactions(self, wallet=None, **constraints):
        tx_rows = await self.select_transactions(
            'txid, raw, height, position, is_verified',
            order_by=constraints.pop('order_by', ["height=0 DESC", "height DESC", "position DESC"]),
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

        step = self.MAX_QUERY_VARIABLES
        annotated_txos = {}
        for offset in range(0, len(txids), step):
            annotated_txos.update({
                txo.id: txo for txo in
                (await self.get_txos(
                    wallet=wallet,
                    txid__in=txids[offset:offset+step],
                ))
            })

        referenced_txos = {}
        for offset in range(0, len(txi_txoids), step):
            referenced_txos.update({
                txo.id: txo for txo in
                (await self.get_txos(
                    wallet=wallet,
                    txoid__in=txi_txoids[offset:offset+step],
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
                    txo.update_annotations(None)

        return txs

    async def get_transaction_count(self, **constraints):
        constraints.pop('wallet', None)
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
        sql = "SELECT {} FROM txo JOIN tx USING (txid)"
        if 'accounts' in constraints:
            sql += " JOIN account_address USING (address)"
        return await self.db.execute_fetchall(*query(sql.format(cols), **constraints))

    async def get_txos(self, wallet=None, no_tx=False, **constraints):
        my_accounts = set(a.public_key.address for a in wallet.accounts) if wallet else set()
        if 'order_by' not in constraints:
            constraints['order_by'] = [
                "tx.height=0 DESC", "tx.height DESC", "tx.position DESC", "txo.position"
            ]
        rows = await self.select_txos(
            """
            tx.txid, raw, tx.height, tx.position, tx.is_verified, txo.position, amount, script, (
                select group_concat(account||"|"||chain) from account_address
                where account_address.address=txo.address
            )
            """,
            **constraints
        )
        txos = []
        txs = {}
        output_class = self.ledger.transaction_class.output_class
        for row in rows:
            if no_tx:
                txo = output_class(
                    amount=row[6],
                    script=output_class.script_class(row[7]),
                    tx_ref=TXRefImmutable.from_id(row[0], row[2]),
                    position=row[5]
                )
            else:
                if row[0] not in txs:
                    txs[row[0]] = self.ledger.transaction_class(
                        row[1], height=row[2], position=row[3], is_verified=row[4]
                    )
                txo = txs[row[0]].outputs[row[5]]
            row_accounts = dict(a.split('|') for a in row[8].split(','))
            account_match = set(row_accounts) & my_accounts
            if account_match:
                txo.is_my_account = True
                txo.is_change = row_accounts[account_match.pop()] == '1'
            else:
                txo.is_change = txo.is_my_account = False
            txos.append(txo)
        return txos

    async def get_txo_count(self, **constraints):
        constraints.pop('wallet', None)
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

    async def get_balance(self, wallet=None, accounts=None, **constraints):
        assert wallet or accounts, \
            "'wallet' or 'accounts' constraints required to calculate balance"
        constraints['accounts'] = accounts or wallet.accounts
        self.constrain_utxo(constraints)
        balance = await self.select_txos('SUM(amount)', **constraints)
        return balance[0][0] or 0

    async def select_addresses(self, cols, **constraints):
        return await self.db.execute_fetchall(*query(
            "SELECT {} FROM pubkey_address JOIN account_address USING (address)".format(cols),
            **constraints
        ))

    async def get_addresses(self, cols=None, **constraints):
        cols = cols or (
            'address', 'account', 'chain', 'history', 'used_times',
            'pubkey', 'chain_code', 'n', 'depth'
        )
        addresses = rows_to_dict(await self.select_addresses(', '.join(cols), **constraints), cols)
        for address in addresses:
            address['pubkey'] = PubKey(
                self.ledger, address.pop('pubkey'), address.pop('chain_code'),
                address.pop('n'), address.pop('depth')
            )
        return addresses

    async def get_address_count(self, **constraints):
        count = await self.select_addresses('count(*)', **constraints)
        return count[0][0]

    async def get_address(self, **constraints):
        addresses = await self.get_addresses(limit=1, **constraints)
        if addresses:
            return addresses[0]

    async def add_keys(self, account, chain, pubkeys):
        await self.db.executemany(
            "insert or ignore into account_address "
            "(account, address, chain, pubkey, chain_code, n, depth) values "
            "(?, ?, ?, ?, ?, ?, ?)", ((
                account.id, k.address, chain,
                sqlite3.Binary(k.pubkey_bytes),
                sqlite3.Binary(k.chain_code),
                k.n, k.depth
            ) for k in pubkeys)
        )
        await self.db.executemany(
            "insert or ignore into pubkey_address (address) values (?)",
            ((pubkey.address,) for pubkey in pubkeys)
        )

    async def _set_address_history(self, address, history):
        await self.db.execute_fetchall(
            "UPDATE pubkey_address SET history = ?, used_times = ? WHERE address = ?",
            (history, history.count(':')//2, address)
        )

    async def set_address_history(self, address, history):
        await self._set_address_history(address, history)
