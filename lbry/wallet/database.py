import logging
import asyncio
import sqlite3

from binascii import hexlify
from concurrent.futures.thread import ThreadPoolExecutor
from typing import Tuple, List, Union, Callable, Any, Awaitable, Iterable, Dict, Optional

from .bip32 import PubKey
from .transaction import Transaction, Output, OutputScript, TXRefImmutable
from .constants import TXO_TYPES, CLAIM_TYPES


log = logging.getLogger(__name__)
sqlite3.enable_callback_tracebacks(True)


class AIOSQLite:

    def __init__(self):
        # has to be single threaded as there is no mapping of thread:connection
        self.writer_executor = ThreadPoolExecutor(max_workers=1)
        self.writer_connection: Optional[sqlite3.Connection] = None
        self._closing = False
        self.query_count = 0

    @classmethod
    async def connect(cls, path: Union[bytes, str], *args, **kwargs):
        sqlite3.enable_callback_tracebacks(True)
        db = cls()

        def _connect_writer():
            db.writer_connection = sqlite3.connect(path, *args, **kwargs)
        await asyncio.get_event_loop().run_in_executor(db.writer_executor, _connect_writer)
        return db

    async def close(self):
        if self._closing:
            return
        self._closing = True
        await asyncio.get_event_loop().run_in_executor(self.writer_executor, self.writer_connection.close)
        self.writer_executor.shutdown(wait=True)
        self.writer_connection = None

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
            self.writer_executor, lambda: self.__run_transaction(fun, *args, **kwargs)
        )

    def __run_transaction(self, fun: Callable[[sqlite3.Connection, Any, Any], Any], *args, **kwargs):
        self.writer_connection.execute('begin')
        try:
            self.query_count += 1
            result = fun(self.writer_connection, *args, **kwargs)  # type: ignore
            self.writer_connection.commit()
            return result
        except (Exception, OSError) as e:
            log.exception('Error running transaction:', exc_info=e)
            self.writer_connection.rollback()
            log.warning("rolled back")
            raise

    def run_with_foreign_keys_disabled(self, fun, *args, **kwargs) -> Awaitable:
        return asyncio.get_event_loop().run_in_executor(
            self.writer_executor, self.__run_transaction_with_foreign_keys_disabled, fun, args, kwargs
        )

    def __run_transaction_with_foreign_keys_disabled(self,
                                                     fun: Callable[[sqlite3.Connection, Any, Any], Any],
                                                     args, kwargs):
        foreign_keys_enabled, = self.writer_connection.execute("pragma foreign_keys").fetchone()
        if not foreign_keys_enabled:
            raise sqlite3.IntegrityError("foreign keys are disabled, use `AIOSQLite.run` instead")
        try:
            self.writer_connection.execute('pragma foreign_keys=off').fetchone()
            return self.__run_transaction(fun, *args, **kwargs)
        finally:
            self.writer_connection.execute('pragma foreign_keys=on').fetchone()


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
        if key.startswith('$$'):
            col, key = col[2:], key[1:]
        elif key.startswith('$'):
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
                col, op, one_val_op = col[:-len('__in')], 'IN', '='
            else:
                col, op, one_val_op = col[:-len('__not_in')], 'NOT IN', '!='
            if constraint:
                if isinstance(constraint, (list, set, tuple)):
                    if len(constraint) == 1:
                        values[f'{key}{tag}'] = next(iter(constraint))
                        sql.append(f'{col} {one_val_op} :{key}{tag}')
                    else:
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
        if isinstance(value, bytes):
            value = f"X'{hexlify(value).decode()}'"
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


class Database(SQLiteMixin):

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
            is_verified boolean not null default 0,
            purchased_claim_id text
        );
        create index if not exists tx_purchased_claim_id_idx on tx (purchased_claim_id);
    """

    CREATE_TXO_TABLE = """
        create table if not exists txo (
            txid text references tx,
            txoid text primary key,
            address text references pubkey_address,
            position integer not null,
            amount integer not null,
            script blob not null,
            is_reserved boolean not null default 0,

            txo_type integer not null default 0,
            claim_id text,
            claim_name text
        );
        create index if not exists txo_txid_idx on txo (txid);
        create index if not exists txo_address_idx on txo (address);
        create index if not exists txo_claim_id_idx on txo (claim_id);
        create index if not exists txo_claim_name_idx on txo (claim_name);
        create index if not exists txo_txo_type_idx on txo (txo_type);
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
        row = {
            'txid': tx.id,
            'txoid': txo.id,
            'address': address,
            'position': txo.position,
            'amount': txo.amount,
            'script': sqlite3.Binary(txo.script.source)
        }
        if txo.is_claim:
            if txo.can_decode_claim:
                row['txo_type'] = TXO_TYPES.get(txo.claim.claim_type, TXO_TYPES['stream'])
            else:
                row['txo_type'] = TXO_TYPES['stream']
        elif txo.is_support:
            row['txo_type'] = TXO_TYPES['support']
        elif txo.purchase is not None:
            row['txo_type'] = TXO_TYPES['purchase']
            row['claim_id'] = txo.purchased_claim_id
        if txo.script.is_claim_involved:
            row['claim_id'] = txo.claim_id
            row['claim_name'] = txo.claim_name
        return row

    @staticmethod
    def tx_to_row(tx):
        row = {
            'txid': tx.id,
            'raw': sqlite3.Binary(tx.raw),
            'height': tx.height,
            'position': tx.position,
            'is_verified': tx.is_verified
        }
        txos = tx.outputs
        if len(txos) >= 2 and txos[1].can_decode_purchase_data:
            txos[0].purchase = txos[1]
            row['purchased_claim_id'] = txos[1].purchase_data.claim_id
        return row

    async def insert_transaction(self, tx):
        await self.db.execute_fetchall(*self._insert_sql('tx', self.tx_to_row(tx)))

    async def update_transaction(self, tx):
        await self.db.execute_fetchall(*self._update_sql("tx", {
            'height': tx.height, 'position': tx.position, 'is_verified': tx.is_verified
        }, 'txid = ?', (tx.id,)))

    def _transaction_io(self, conn: sqlite3.Connection, tx: Transaction, address, txhash):
        conn.execute(*self._insert_sql('tx', self.tx_to_row(tx), replace=True)).fetchall()

        for txo in tx.outputs:
            if txo.script.is_pay_pubkey_hash and txo.pubkey_hash == txhash:
                conn.execute(*self._insert_sql(
                    "txo", self.txo_to_row(tx, address, txo), ignore_duplicate=True
                )).fetchall()
            elif txo.script.is_pay_script_hash:
                # TODO: implement script hash payments
                log.warning('Database.save_transaction_io: pay script hash is not implemented!')

        for txi in tx.inputs:
            if txi.txo_ref.txo is not None:
                txo = txi.txo_ref.txo
                if txo.has_address and txo.get_address(self.ledger) == address:
                    conn.execute(*self._insert_sql("txi", {
                        'txid': tx.id,
                        'txoid': txo.id,
                        'address': address,
                    }, ignore_duplicate=True)).fetchall()

    def save_transaction_io(self, tx: Transaction, address, txhash, history):
        return self.save_transaction_io_batch([tx], address, txhash, history)

    def save_transaction_io_batch(self, txs: Iterable[Transaction], address, txhash, history):
        history_count = history.count(':') // 2

        def __many(conn):
            for tx in txs:
                self._transaction_io(conn, tx, address, txhash)
            conn.execute(
                "UPDATE pubkey_address SET history = ?, used_times = ? WHERE address = ?",
                (history, history_count, address)
            ).fetchall()

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
        if not {'txid', 'txid__in'}.intersection(constraints):
            assert accounts, "'accounts' argument required when no 'txid' constraint is present"
            where, values = constraints_to_sql({
                '$$account_address.account__in': [a.public_key.address for a in accounts]
            })
            constraints['txid__in'] = f"""
                SELECT txo.txid FROM txo JOIN account_address USING (address) WHERE {where}
              UNION
                SELECT txi.txid FROM txi JOIN account_address USING (address) WHERE {where}
            """
            constraints.update(values)
        return await self.db.execute_fetchall(
            *query(f"SELECT {cols} FROM tx", **constraints)
        )

    TXO_NOT_MINE = Output(None, None, is_my_account=False)

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
            txs.append(Transaction(
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
        count = await self.select_transactions('count(*)', **constraints)
        return count[0][0]

    async def get_transaction(self, **constraints):
        txs = await self.get_transactions(limit=1, **constraints)
        if txs:
            return txs[0]

    async def select_txos(self, cols, wallet=None, include_is_received=False, **constraints):
        if include_is_received:
            assert wallet is not None, 'cannot use is_recieved filter without wallet argument'
            account_in_wallet, values = constraints_to_sql({
                '$$account__in#is_received': [a.public_key.address for a in wallet.accounts]
            })
            cols += f""",
            NOT EXISTS(
                SELECT 1 FROM txi JOIN account_address USING (address)
                WHERE txi.txid=txo.txid AND {account_in_wallet}
            ) as is_received
            """
            constraints.update(values)
        sql = f"SELECT {cols} FROM txo JOIN tx USING (txid)"
        if 'accounts' in constraints:
            sql += " JOIN account_address USING (address)"
        return await self.db.execute_fetchall(*query(sql, **constraints))

    @staticmethod
    def constrain_unspent(constraints):
        constraints['is_reserved'] = False
        constraints['txoid__not_in'] = "SELECT txoid FROM txi"

    async def get_txos(self, wallet=None, no_tx=False, unspent=False, include_is_received=False, **constraints):
        include_is_received = include_is_received or 'is_received' in constraints
        if unspent:
            self.constrain_unspent(constraints)
        my_accounts = {a.public_key.address for a in wallet.accounts} if wallet else set()
        if 'order_by' not in constraints:
            constraints['order_by'] = [
                "tx.height=0 DESC", "tx.height DESC", "tx.position DESC", "txo.position"
            ]
        rows = await self.select_txos(
            """
            tx.txid, raw, tx.height, tx.position, tx.is_verified, txo.position, amount, script, (
                select group_concat(account||"|"||chain) from account_address
                where account_address.address=txo.address
            ), exists(select 1 from txi where txi.txoid=txo.txoid)
            """,
            wallet=wallet, include_is_received=include_is_received, **constraints
        )
        txos = []
        txs = {}
        for row in rows:
            if no_tx:
                txo = Output(
                    amount=row[6],
                    script=OutputScript(row[7]),
                    tx_ref=TXRefImmutable.from_id(row[0], row[2]),
                    position=row[5]
                )
            else:
                if row[0] not in txs:
                    txs[row[0]] = Transaction(
                        row[1], height=row[2], position=row[3], is_verified=row[4]
                    )
                txo = txs[row[0]].outputs[row[5]]
            row_accounts = dict(a.split('|') for a in row[8].split(','))
            account_match = set(row_accounts) & my_accounts
            txo.is_spent = bool(row[9])
            if include_is_received:
                txo.is_received = bool(row[10])
            if account_match:
                txo.is_my_account = True
                txo.is_change = row_accounts[account_match.pop()] == '1'
            else:
                txo.is_change = txo.is_my_account = False
            txos.append(txo)

        channel_ids = set()
        for txo in txos:
            if txo.is_claim and txo.can_decode_claim:
                if txo.claim.is_signed:
                    channel_ids.add(txo.claim.signing_channel_id)
                if txo.claim.is_channel and wallet:
                    for account in wallet.accounts:
                        private_key = account.get_channel_private_key(
                            txo.claim.channel.public_key_bytes
                        )
                        if private_key:
                            txo.private_key = private_key
                            break

        if channel_ids:
            channels = {
                txo.claim_id: txo for txo in
                (await self.get_channels(
                    wallet=wallet,
                    claim_id__in=channel_ids
                ))
            }
            for txo in txos:
                if txo.is_claim and txo.can_decode_claim:
                    txo.channel = channels.get(txo.claim.signing_channel_id, None)

        return txos

    async def get_txo_count(self, unspent=False, **constraints):
        constraints['include_is_received'] = 'is_received' in constraints
        constraints.pop('resolve', None)
        constraints.pop('offset', None)
        constraints.pop('limit', None)
        constraints.pop('order_by', None)
        if unspent:
            self.constrain_unspent(constraints)
        count = await self.select_txos('count(*)', **constraints)
        return count[0][0]

    def get_utxos(self, **constraints):
        return self.get_txos(unspent=True, **constraints)

    def get_utxo_count(self, **constraints):
        return self.get_txo_count(unspent=True, **constraints)

    async def get_balance(self, wallet=None, accounts=None, **constraints):
        assert wallet or accounts, \
            "'wallet' or 'accounts' constraints required to calculate balance"
        constraints['accounts'] = accounts or wallet.accounts
        self.constrain_unspent(constraints)
        balance = await self.select_txos('SUM(amount)', **constraints)
        return balance[0][0] or 0

    async def select_addresses(self, cols, **constraints):
        return await self.db.execute_fetchall(*query(
            f"SELECT {cols} FROM pubkey_address JOIN account_address USING (address)",
            **constraints
        ))

    async def get_addresses(self, cols=None, **constraints):
        cols = cols or (
            'address', 'account', 'chain', 'history', 'used_times',
            'pubkey', 'chain_code', 'n', 'depth'
        )
        addresses = rows_to_dict(await self.select_addresses(', '.join(cols), **constraints), cols)
        if 'pubkey' in cols:
            for address in addresses:
                address['pubkey'] = PubKey(
                    self.ledger, address.pop('pubkey'), address.pop('chain_code'),
                    address.pop('n'), address.pop('depth')
                )
        return addresses

    async def get_address_count(self, cols=None, **constraints):
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

    @staticmethod
    def constrain_purchases(constraints):
        accounts = constraints.pop('accounts', None)
        assert accounts, "'accounts' argument required to find purchases"
        if not {'purchased_claim_id', 'purchased_claim_id__in'}.intersection(constraints):
            constraints['purchased_claim_id__is_not_null'] = True
        constraints.update({
            f'$account{i}': a.public_key.address for i, a in enumerate(accounts)
        })
        account_values = ', '.join([f':$account{i}' for i in range(len(accounts))])
        constraints['txid__in'] = f"""
            SELECT txid FROM txi JOIN account_address USING (address)
            WHERE account_address.account IN ({account_values})
        """

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
        await self.db.execute_fetchall(
            "UPDATE txo SET is_reserved = 0 WHERE"
            "  is_reserved = 1 AND txo.address IN ("
            "    SELECT address from account_address WHERE account = ?"
            "  )", (account.public_key.address, )
        )

    def get_supports_summary(self, account_id):
        return self.db.execute_fetchall(f"""
            select txo.amount, exists(select * from txi where txi.txoid=txo.txoid) as spent,
                (txo.txid in
                (select txi.txid from txi join account_address a on txi.address = a.address
                    where a.account = ?)) as from_me,
                (txo.address in (select address from account_address where account=?)) as to_me,
                tx.height
            from txo join tx using (txid) where txo_type={TXO_TYPES['support']}
        """, (account_id, account_id))
