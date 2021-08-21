import os
import logging
import asyncio
import sqlite3
import platform
from binascii import hexlify
from collections import defaultdict
from dataclasses import dataclass
from contextvars import ContextVar
from typing import Tuple, List, Union, Callable, Any, Awaitable, Iterable, Dict, Optional
from datetime import date
from prometheus_client import Gauge, Counter, Histogram
from lbry.utils import LockWithMetrics

from .bip32 import PubKey
from .transaction import Transaction, Output, OutputScript, TXRefImmutable, Input
from .constants import TXO_TYPES, CLAIM_TYPES
from .util import date_to_julian_day

from concurrent.futures.thread import ThreadPoolExecutor  # pylint: disable=wrong-import-order
if platform.system() == 'Windows' or ({'ANDROID_ARGUMENT', 'KIVY_BUILD'} & os.environ.keys()):
    from concurrent.futures.thread import ThreadPoolExecutor as ReaderExecutorClass  # pylint: disable=reimported
else:
    from concurrent.futures.process import ProcessPoolExecutor as ReaderExecutorClass


log = logging.getLogger(__name__)
sqlite3.enable_callback_tracebacks(True)

HISTOGRAM_BUCKETS = (
    .005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0, 60.0, float('inf')
)


@dataclass
class ReaderProcessState:
    cursor: sqlite3.Cursor


reader_context: Optional[ContextVar[ReaderProcessState]] = ContextVar('reader_context')


def initializer(path):
    db = sqlite3.connect(path)
    db.row_factory = dict_row_factory
    db.executescript("pragma journal_mode=WAL;")
    reader = ReaderProcessState(db.cursor())
    reader_context.set(reader)


def run_read_only_fetchall(sql, params):
    cursor = reader_context.get().cursor
    try:
        return cursor.execute(sql, params).fetchall()
    except (Exception, OSError) as e:
        log.exception('Error running transaction:', exc_info=e)
        raise


def run_read_only_fetchone(sql, params):
    cursor = reader_context.get().cursor
    try:
        return cursor.execute(sql, params).fetchone()
    except (Exception, OSError) as e:
        log.exception('Error running transaction:', exc_info=e)
        raise


class AIOSQLite:
    reader_executor: ReaderExecutorClass

    waiting_writes_metric = Gauge(
        "waiting_writes_count", "Number of waiting db writes", namespace="daemon_database"
    )
    waiting_reads_metric = Gauge(
        "waiting_reads_count", "Number of waiting db writes", namespace="daemon_database"
    )
    write_count_metric = Counter(
        "write_count", "Number of database writes", namespace="daemon_database"
    )
    read_count_metric = Counter(
        "read_count", "Number of database reads", namespace="daemon_database"
    )
    acquire_write_lock_metric = Histogram(
        'write_lock_acquired', 'Time to acquire the write lock', namespace="daemon_database", buckets=HISTOGRAM_BUCKETS
    )
    held_write_lock_metric = Histogram(
        'write_lock_held', 'Length of time the write lock is held for', namespace="daemon_database",
        buckets=HISTOGRAM_BUCKETS
    )

    def __init__(self):
        # has to be single threaded as there is no mapping of thread:connection
        self.writer_executor = ThreadPoolExecutor(max_workers=1)
        self.writer_connection: Optional[sqlite3.Connection] = None
        self._closing = False
        self.query_count = 0
        self.write_lock = LockWithMetrics(self.acquire_write_lock_metric, self.held_write_lock_metric)
        self.writers = 0
        self.read_ready = asyncio.Event()
        self.urgent_read_done = asyncio.Event()

    @classmethod
    async def connect(cls, path: Union[bytes, str], *args, **kwargs):
        sqlite3.enable_callback_tracebacks(True)
        db = cls()

        def _connect_writer():
            db.writer_connection = sqlite3.connect(path, *args, **kwargs)

        readers = max(os.cpu_count() - 2, 2)
        db.reader_executor = ReaderExecutorClass(
            max_workers=readers, initializer=initializer, initargs=(path, )
        )
        await asyncio.get_event_loop().run_in_executor(db.writer_executor, _connect_writer)
        db.read_ready.set()
        db.urgent_read_done.set()
        return db

    async def close(self):
        if self._closing:
            return
        self._closing = True

        def __checkpoint_and_close(conn: sqlite3.Connection):
            conn.execute("PRAGMA WAL_CHECKPOINT(FULL);")
            log.info("DB checkpoint finished.")
            conn.close()
        await asyncio.get_event_loop().run_in_executor(
            self.writer_executor, __checkpoint_and_close, self.writer_connection)
        self.writer_executor.shutdown(wait=True)
        self.reader_executor.shutdown(wait=True)
        self.read_ready.clear()
        self.writer_connection = None

    def executemany(self, sql: str, params: Iterable):
        params = params if params is not None else []
        # this fetchall is needed to prevent SQLITE_MISUSE
        return self.run(lambda conn: conn.executemany(sql, params).fetchall())

    def executescript(self, script: str) -> Awaitable:
        return self.run(lambda conn: conn.executescript(script))

    async def _execute_fetch(self, sql: str, parameters: Iterable = None,
                             read_only=False, fetch_all: bool = False) -> List[dict]:
        read_only_fn = run_read_only_fetchall if fetch_all else run_read_only_fetchone
        parameters = parameters if parameters is not None else []
        still_waiting = False
        urgent_read = False
        if read_only:
            self.waiting_reads_metric.inc()
            self.read_count_metric.inc()
            try:
                while self.writers and not self._closing:  # more writes can come in while we are waiting for the first
                    if not urgent_read and still_waiting and self.urgent_read_done.is_set():
                        #  throttle the writes if they pile up
                        self.urgent_read_done.clear()
                        urgent_read = True
                    #  wait until the running writes have finished
                    await self.read_ready.wait()
                    still_waiting = True
                if self._closing:
                    raise asyncio.CancelledError()
                return await asyncio.get_event_loop().run_in_executor(
                    self.reader_executor, read_only_fn, sql, parameters
                )
            finally:
                if urgent_read:
                    #  unthrottle the writers if they had to be throttled
                    self.urgent_read_done.set()
                self.waiting_reads_metric.dec()
        if fetch_all:
            return await self.run(lambda conn: conn.execute(sql, parameters).fetchall())
        return await self.run(lambda conn: conn.execute(sql, parameters).fetchone())

    async def execute_fetchall(self, sql: str, parameters: Iterable = None,
                               read_only=False) -> List[dict]:
        return await self._execute_fetch(sql, parameters, read_only, fetch_all=True)

    async def execute_fetchone(self, sql: str, parameters: Iterable = None,
                               read_only=False) -> List[dict]:
        return await self._execute_fetch(sql, parameters, read_only, fetch_all=False)

    def execute(self, sql: str, parameters: Iterable = None) -> Awaitable[sqlite3.Cursor]:
        parameters = parameters if parameters is not None else []
        return self.run(lambda conn: conn.execute(sql, parameters))

    async def run(self, fun, *args, **kwargs):
        self.write_count_metric.inc()
        self.waiting_writes_metric.inc()
        # it's possible many writes are coming in one after the other, these can
        # block reader calls for a long time
        # if the reader waits for the writers to finish and then has to wait for
        # yet more, it will clear the urgent_read_done event to block more writers
        # piling on
        try:
            await self.urgent_read_done.wait()
        except Exception as e:
            self.waiting_writes_metric.dec()
            raise e
        self.writers += 1
        # block readers
        self.read_ready.clear()
        try:
            async with self.write_lock:
                if self._closing:
                    raise asyncio.CancelledError()
                return await asyncio.get_event_loop().run_in_executor(
                    self.writer_executor, lambda: self.__run_transaction(fun, *args, **kwargs)
                )
        finally:
            self.writers -= 1
            self.waiting_writes_metric.dec()
            if not self.writers:
                # unblock the readers once the last enqueued writer finishes
                self.read_ready.set()

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

    async def run_with_foreign_keys_disabled(self, fun, *args, **kwargs):
        self.write_count_metric.inc()
        self.waiting_writes_metric.inc()
        try:
            await self.urgent_read_done.wait()
        except Exception as e:
            self.waiting_writes_metric.dec()
            raise e
        self.writers += 1
        self.read_ready.clear()
        try:
            async with self.write_lock:
                if self._closing:
                    raise asyncio.CancelledError()
                return await asyncio.get_event_loop().run_in_executor(
                    self.writer_executor, self.__run_transaction_with_foreign_keys_disabled, fun, args, kwargs
                )
        finally:
            self.writers -= 1
            self.waiting_writes_metric.dec()
            if not self.writers:
                self.read_ready.set()

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
    group_by = constraints.pop('group_by', None)

    accounts = constraints.pop('accounts', [])
    if accounts:
        constraints['account__in'] = [a.public_key.address for a in accounts]

    where, values = constraints_to_sql(constraints)
    if where:
        sql.append('WHERE')
        sql.append(where)

    if group_by is not None:
        sql.append(f'GROUP BY {group_by}')

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


def constrain_single_or_list(constraints, column, value, convert=lambda x: x, negate=False):
    if value is not None:
        if isinstance(value, list):
            value = [convert(v) for v in value]
            if len(value) == 1:
                if negate:
                    constraints[f"{column}__or"] = {
                        f"{column}__is_null": True,
                        f"{column}__not": value[0]
                    }
                else:
                    constraints[column] = value[0]
            elif len(value) > 1:
                if negate:
                    constraints[f"{column}__or"] = {
                        f"{column}__is_null": True,
                        f"{column}__not_in": value
                    }
                else:
                    constraints[f"{column}__in"] = value
        elif negate:
            constraints[f"{column}__or"] = {
                f"{column}__is_null": True,
                f"{column}__not": convert(value)
            }
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
                    if version == ("1.5",) and self.SCHEMA_VERSION == "1.6":
                        await self.db.execute("ALTER TABLE txo ADD COLUMN has_source bool DEFAULT 1;")
                        await self.db.execute("UPDATE version SET version = ?", (self.SCHEMA_VERSION,))
                        return
                await self.db.executescript('\n'.join(
                    f"DROP TABLE {table};" for table in tables
                ) + '\n' + 'PRAGMA WAL_CHECKPOINT(FULL);' + '\n' + 'VACUUM;')
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


def dict_row_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


SQLITE_MAX_INTEGER = 9223372036854775807


def _get_spendable_utxos(transaction: sqlite3.Connection, accounts: List, decoded_transactions: Dict[str, Transaction],
                         result: Dict[Tuple[bytes, int, bool], List[int]], reserved: List[Transaction],
                         amount_to_reserve: int, reserved_amount: int, floor: int, ceiling: int,
                         fee_per_byte: int) -> int:
    accounts_fmt = ",".join(["?"] * len(accounts))
    txo_query = """
        SELECT tx.txid, txo.txoid, tx.raw, tx.height, txo.position as nout, tx.is_verified, txo.amount FROM txo
        INNER JOIN account_address USING (address)
        LEFT JOIN txi USING (txoid)
        INNER JOIN tx USING (txid)
        WHERE txo.txo_type=0 AND txi.txoid IS NULL AND tx.txid IS NOT NULL AND NOT txo.is_reserved
        AND txo.amount >= ? AND txo.amount < ?
    """
    if accounts:
        txo_query += f"""
            AND account_address.account {'= ?' if len(accounts_fmt) == 1 else 'IN (' + accounts_fmt + ')'}
        """
    txo_query += """
        ORDER BY txo.amount ASC, tx.height DESC
    """
    # prefer confirmed, but save unconfirmed utxos from this selection in case they are needed
    unconfirmed = []
    for row in transaction.execute(txo_query, (floor, ceiling, *accounts)):
        (txid, txoid, raw, height, nout, verified, amount) = row.values()
        # verified or non verified transactions were found- reset the gap count
        # multiple txos can come from the same tx, only decode it once and cache
        if txid not in decoded_transactions:
            # cache the decoded transaction
            decoded_transactions[txid] = Transaction(raw)
        decoded_tx = decoded_transactions[txid]
        # save the unconfirmed txo for possible use later, if still needed
        if verified:
            # add the txo to the reservation, minus the fee for including it
            reserved_amount += amount
            reserved_amount -= Input.spend(decoded_tx.outputs[nout]).size * fee_per_byte
            # mark it as reserved
            result[(raw, height, verified)].append(nout)
            reserved.append(txoid)
            # if we've reserved enough, return
            if reserved_amount >= amount_to_reserve:
                return reserved_amount
        else:
            unconfirmed.append((txid, txoid, raw, height, nout, verified, amount))
    # we're popping the items, so to get them in the order they were seen they are reversed
    unconfirmed.reverse()
    # add available unconfirmed txos if any were previously found
    while unconfirmed and reserved_amount < amount_to_reserve:
        (txid, txoid, raw, height, nout, verified, amount) = unconfirmed.pop()
        # it's already decoded
        decoded_tx = decoded_transactions[txid]
        # add to the reserved amount
        reserved_amount += amount
        reserved_amount -= Input.spend(decoded_tx.outputs[nout]).size * fee_per_byte
        result[(raw, height, verified)].append(nout)
        reserved.append(txoid)
    return reserved_amount


def get_and_reserve_spendable_utxos(transaction: sqlite3.Connection, accounts: List, amount_to_reserve: int, floor: int,
                                    fee_per_byte: int, set_reserved: bool, return_insufficient_funds: bool,
                                    base_multiplier: int = 100):
    txs = defaultdict(list)
    decoded_transactions = {}
    reserved = []

    reserved_dewies = 0
    multiplier = base_multiplier
    gap_count = 0

    while reserved_dewies < amount_to_reserve and gap_count < 5 and floor * multiplier < SQLITE_MAX_INTEGER:
        previous_reserved_dewies = reserved_dewies
        reserved_dewies = _get_spendable_utxos(
            transaction, accounts, decoded_transactions, txs, reserved, amount_to_reserve, reserved_dewies,
            floor, floor * multiplier, fee_per_byte
        )
        floor *= multiplier
        if previous_reserved_dewies == reserved_dewies:
            gap_count += 1
            multiplier **= 2
        else:
            gap_count = 0
            multiplier = base_multiplier

    # reserve the accumulated txos if enough were found
    if reserved_dewies >= amount_to_reserve:
        if set_reserved:
            transaction.executemany("UPDATE txo SET is_reserved = ? WHERE txoid = ?",
                                    [(True, txoid) for txoid in reserved]).fetchall()
        return txs
    # return_insufficient_funds and set_reserved are used for testing
    return txs if return_insufficient_funds else {}


class Database(SQLiteMixin):

    SCHEMA_VERSION = "1.6"

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
            purchased_claim_id text,
            day integer
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
            claim_name text,
            has_source bool,

            channel_id text,
            reposted_claim_id text
        );
        create index if not exists txo_txid_idx on txo (txid);
        create index if not exists txo_address_idx on txo (address);
        create index if not exists txo_claim_id_idx on txo (claim_id, txo_type);
        create index if not exists txo_claim_name_idx on txo (claim_name);
        create index if not exists txo_txo_type_idx on txo (txo_type);
        create index if not exists txo_channel_id_idx on txo (channel_id);
        create index if not exists txo_reposted_claim_idx on txo (reposted_claim_id);
    """

    CREATE_TXI_TABLE = """
        create table if not exists txi (
            txid text references tx,
            txoid text references txo primary key,
            address text references pubkey_address,
            position integer not null
        );
        create index if not exists txi_address_idx on txi (address);
        create index if not exists first_input_idx on txi (txid, address) where position=0;
    """

    CREATE_TABLES_QUERY = (
        PRAGMAS +
        CREATE_ACCOUNT_TABLE +
        CREATE_PUBKEY_ADDRESS_TABLE +
        CREATE_TX_TABLE +
        CREATE_TXO_TABLE +
        CREATE_TXI_TABLE
    )

    async def open(self):
        await super().open()
        self.db.writer_connection.row_factory = dict_row_factory

    def txo_to_row(self, tx, txo):
        row = {
            'txid': tx.id,
            'txoid': txo.id,
            'address': txo.get_address(self.ledger),
            'position': txo.position,
            'amount': txo.amount,
            'script': sqlite3.Binary(txo.script.source),
            'has_source': False,
        }
        if txo.is_claim:
            if txo.can_decode_claim:
                claim = txo.claim
                row['txo_type'] = TXO_TYPES.get(claim.claim_type, TXO_TYPES['stream'])
                if claim.is_repost:
                    row['reposted_claim_id'] = claim.repost.reference.claim_id
                    row['has_source'] = True
                if claim.is_signed:
                    row['channel_id'] = claim.signing_channel_id
                if claim.is_stream:
                    row['has_source'] = claim.stream.has_source
            else:
                row['txo_type'] = TXO_TYPES['stream']
        elif txo.is_support:
            row['txo_type'] = TXO_TYPES['support']
            support = txo.can_decode_support
            if support and support.is_signed:
                row['channel_id'] = support.signing_channel_id
        elif txo.purchase is not None:
            row['txo_type'] = TXO_TYPES['purchase']
            row['claim_id'] = txo.purchased_claim_id
        if txo.script.is_claim_involved:
            row['claim_id'] = txo.claim_id
            row['claim_name'] = txo.claim_name
        return row

    def tx_to_row(self, tx):
        row = {
            'txid': tx.id,
            'raw': sqlite3.Binary(tx.raw),
            'height': tx.height,
            'position': tx.position,
            'is_verified': tx.is_verified,
            'day': tx.get_julian_day(self.ledger),
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

        is_my_input = False

        for txi in tx.inputs:
            if txi.txo_ref.txo is not None:
                txo = txi.txo_ref.txo
                if txo.has_address and txo.get_address(self.ledger) == address:
                    is_my_input = True
                    conn.execute(*self._insert_sql("txi", {
                        'txid': tx.id,
                        'txoid': txo.id,
                        'address': address,
                        'position': txi.position
                    }, ignore_duplicate=True)).fetchall()

        for txo in tx.outputs:
            if txo.script.is_pay_pubkey_hash and (txo.pubkey_hash == txhash or is_my_input):
                conn.execute(*self._insert_sql(
                    "txo", self.txo_to_row(tx, txo), ignore_duplicate=True
                )).fetchall()
            elif txo.script.is_pay_script_hash and is_my_input:
                conn.execute(*self._insert_sql(
                    "txo", self.txo_to_row(tx, txo), ignore_duplicate=True
                )).fetchall()

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
        txoids = [(is_reserved, txo.id) for txo in txos]
        await self.db.executemany("UPDATE txo SET is_reserved = ? WHERE txoid = ?", txoids)

    async def release_outputs(self, txos):
        await self.reserve_outputs(txos, is_reserved=False)

    async def rewind_blockchain(self, above_height):  # pylint: disable=no-self-use
        # TODO:
        # 1. delete transactions above_height
        # 2. update address histories removing deleted TXs
        return True

    async def get_spendable_utxos(self, ledger, reserve_amount, accounts: Optional[Iterable], min_amount: int = 1,
                                  fee_per_byte: int = 50, set_reserved: bool = True,
                                  return_insufficient_funds: bool = False) -> List:
        to_spend = await self.db.run(
            get_and_reserve_spendable_utxos, tuple(account.id for account in accounts), reserve_amount, min_amount,
            fee_per_byte, set_reserved, return_insufficient_funds
        )
        txos = []
        for (raw, height, verified), positions in to_spend.items():
            tx = Transaction(raw, height=height, is_verified=verified)
            for nout in positions:
                txos.append(tx.outputs[nout].get_estimator(ledger))
        return txos

    async def select_transactions(self, cols, accounts=None, read_only=False, **constraints):
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
            *query(f"SELECT {cols} FROM tx", **constraints), read_only=read_only
        )

    TXO_NOT_MINE = Output(None, None, is_my_output=False)

    async def get_transactions(self, wallet=None, **constraints):
        include_is_spent = constraints.pop('include_is_spent', False)
        include_is_my_input = constraints.pop('include_is_my_input', False)
        include_is_my_output = constraints.pop('include_is_my_output', False)

        tx_rows = await self.select_transactions(
            'txid, raw, height, position, is_verified',
            order_by=constraints.pop('order_by', ["height=0 DESC", "height DESC", "position DESC"]),
            **constraints
        )

        if not tx_rows:
            return []

        txids, txs, txi_txoids = [], [], []
        for row in tx_rows:
            txids.append(row['txid'])
            txs.append(Transaction(
                raw=row['raw'], height=row['height'], position=row['position'],
                is_verified=bool(row['is_verified'])
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
                    txid__in=txids[offset:offset+step], order_by='txo.txid',
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
                    txoid__in=txi_txoids[offset:offset+step], order_by='txo.txoid',
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
        count = await self.select_transactions('COUNT(*) as total', **constraints)
        return count[0]['total'] or 0

    async def get_transaction(self, **constraints):
        txs = await self.get_transactions(limit=1, **constraints)
        if txs:
            return txs[0]

    async def select_txos(
            self, cols, accounts=None, is_my_input=None, is_my_output=True,
            is_my_input_or_output=None, exclude_internal_transfers=False,
            include_is_spent=False, include_is_my_input=False,
            is_spent=None, read_only=False, **constraints):
        for rename_col in ('txid', 'txoid'):
            for rename_constraint in (rename_col, rename_col+'__in', rename_col+'__not_in'):
                if rename_constraint in constraints:
                    constraints['txo.'+rename_constraint] = constraints.pop(rename_constraint)
        if accounts:
            account_in_sql, values = constraints_to_sql({
                '$$account__in': [a.public_key.address for a in accounts]
            })
            my_addresses = f"SELECT address FROM account_address WHERE {account_in_sql}"
            constraints.update(values)
            if is_my_input_or_output:
                include_is_my_input = True
                constraints['received_or_sent__or'] = {
                    'txo.address__in': my_addresses,
                    'sent__and': {
                        'txi.address__is_not_null': True,
                        'txi.address__in': my_addresses
                    }
                }
            else:
                if is_my_output:
                    constraints['txo.address__in'] = my_addresses
                elif is_my_output is False:
                    constraints['txo.address__not_in'] = my_addresses
                if is_my_input:
                    include_is_my_input = True
                    constraints['txi.address__is_not_null'] = True
                    constraints['txi.address__in'] = my_addresses
                elif is_my_input is False:
                    include_is_my_input = True
                    constraints['is_my_input_false__or'] = {
                        'txi.address__is_null': True,
                        'txi.address__not_in': my_addresses
                    }
            if exclude_internal_transfers:
                include_is_my_input = True
                constraints['exclude_internal_payments__or'] = {
                    'txo.txo_type__not': TXO_TYPES['other'],
                    'txo.address__not_in': my_addresses,
                    'txi.address__is_null': True,
                    'txi.address__not_in': my_addresses,
                }
        sql = [f"SELECT {cols} FROM txo JOIN tx ON (tx.txid=txo.txid)"]
        if is_spent:
            constraints['spent.txoid__is_not_null'] = True
        elif is_spent is False:
            constraints['is_reserved'] = False
            constraints['spent.txoid__is_null'] = True
        if include_is_spent or is_spent is not None:
            sql.append("LEFT JOIN txi AS spent ON (spent.txoid=txo.txoid)")
        if include_is_my_input:
            sql.append("LEFT JOIN txi ON (txi.position=0 AND txi.txid=txo.txid)")
        return await self.db.execute_fetchall(*query(' '.join(sql), **constraints), read_only=read_only)

    async def get_txos(self, wallet=None, no_tx=False, no_channel_info=False, read_only=False, **constraints):
        include_is_spent = constraints.get('include_is_spent', False)
        include_is_my_input = constraints.get('include_is_my_input', False)
        include_is_my_output = constraints.pop('include_is_my_output', False)
        include_received_tips = constraints.pop('include_received_tips', False)

        select_columns = [
            "tx.txid, tx.height, tx.position as tx_position, tx.is_verified, "
            "txo_type, txo.position as txo_position, amount, script"
        ]
        if not no_tx:
            select_columns.append("raw")

        my_accounts = {a.public_key.address for a in wallet.accounts} if wallet else set()
        my_accounts_sql = ""
        if include_is_my_output or include_is_my_input:
            my_accounts_sql, values = constraints_to_sql({'$$account__in#_wallet': my_accounts})
            constraints.update(values)

        if include_is_my_output and my_accounts:
            if constraints.get('is_my_output', None) in (True, False):
                select_columns.append(f"{1 if constraints['is_my_output'] else 0} AS is_my_output")
            else:
                select_columns.append(f"""(
                    txo.address IN (SELECT address FROM account_address WHERE {my_accounts_sql})
                ) AS is_my_output""")

        if include_is_my_input and my_accounts:
            if constraints.get('is_my_input', None) in (True, False):
                select_columns.append(f"{1 if constraints['is_my_input'] else 0} AS is_my_input")
            else:
                select_columns.append(f"""(
                    txi.address IS NOT NULL AND
                    txi.address IN (SELECT address FROM account_address WHERE {my_accounts_sql})
                ) AS is_my_input""")

        if include_is_spent:
            select_columns.append("spent.txoid IS NOT NULL AS is_spent")

        if include_received_tips:
            select_columns.append(f"""(
            SELECT COALESCE(SUM(support.amount), 0) FROM txo AS support WHERE
                support.claim_id = txo.claim_id AND
                support.txo_type = {TXO_TYPES['support']} AND
                support.address IN (SELECT address FROM account_address WHERE {my_accounts_sql}) AND
                support.txoid NOT IN (SELECT txoid FROM txi)
            ) AS received_tips""")

        if 'order_by' not in constraints or constraints['order_by'] == 'height':
            constraints['order_by'] = [
                "tx.height in (0, -1) DESC", "tx.height DESC", "tx.position DESC", "txo.position"
            ]
        elif constraints.get('order_by', None) == 'none':
            del constraints['order_by']

        rows = await self.select_txos(', '.join(select_columns), read_only=read_only, **constraints)

        txos = []
        txs = {}
        for row in rows:
            if no_tx:
                txo = Output(
                    amount=row['amount'],
                    script=OutputScript(row['script']),
                    tx_ref=TXRefImmutable.from_id(row['txid'], row['height']),
                    position=row['txo_position']
                )
            else:
                if row['txid'] not in txs:
                    txs[row['txid']] = Transaction(
                        row['raw'], height=row['height'], position=row['tx_position'],
                        is_verified=bool(row['is_verified'])
                    )
                txo = txs[row['txid']].outputs[row['txo_position']]
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

        if not no_channel_info:
            channel_ids = set()
            for txo in txos:
                if txo.is_claim and txo.can_decode_claim:
                    if txo.claim.is_signed:
                        channel_ids.add(txo.claim.signing_channel_id)
                    if txo.claim.is_channel and wallet:
                        for account in wallet.accounts:
                            private_key = await account.get_channel_private_key(
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
                        claim_id__in=channel_ids,
                        read_only=read_only
                    ))
                }
                for txo in txos:
                    if txo.is_claim and txo.can_decode_claim:
                        txo.channel = channels.get(txo.claim.signing_channel_id, None)

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
        count = await self.select_txos('COUNT(*) AS total', **constraints)
        return count[0]['total'] or 0

    async def get_txo_sum(self, **constraints):
        self._clean_txo_constraints_for_aggregation(constraints)
        result = await self.select_txos('SUM(amount) AS total', **constraints)
        return result[0]['total'] or 0

    async def get_txo_plot(self, start_day=None, days_back=0, end_day=None, days_after=None, **constraints):
        self._clean_txo_constraints_for_aggregation(constraints)
        if start_day is None:
            constraints['day__gte'] = self.ledger.headers.estimated_julian_day(
                self.ledger.headers.height
            ) - days_back
        else:
            constraints['day__gte'] = date_to_julian_day(
                date.fromisoformat(start_day)
            )
            if end_day is not None:
                constraints['day__lte'] = date_to_julian_day(
                    date.fromisoformat(end_day)
                )
            elif days_after is not None:
                constraints['day__lte'] = constraints['day__gte'] + days_after
        return await self.select_txos(
            "DATE(day) AS day, SUM(amount) AS total",
            group_by='day', order_by='day', **constraints
        )

    def get_utxos(self, read_only=False, **constraints):
        return self.get_txos(is_spent=False, read_only=read_only, **constraints)

    def get_utxo_count(self, **constraints):
        return self.get_txo_count(is_spent=False, **constraints)

    async def get_balance(self, wallet=None, accounts=None, read_only=False, **constraints):
        assert wallet or accounts, \
            "'wallet' or 'accounts' constraints required to calculate balance"
        constraints['accounts'] = accounts or wallet.accounts
        balance = await self.select_txos(
            'SUM(amount) as total', is_spent=False, read_only=read_only, **constraints
        )
        return balance[0]['total'] or 0

    async def get_detailed_balance(self, accounts, read_only=False, **constraints):
        constraints['accounts'] = accounts
        result = (await self.select_txos(
            f"COALESCE(SUM(amount), 0) AS total,"
            f"COALESCE(SUM("
            f"  CASE WHEN"
            f"    txo_type NOT IN ({TXO_TYPES['other']}, {TXO_TYPES['purchase']})"
            f"  THEN amount ELSE 0 END), 0) AS reserved,"
            f"COALESCE(SUM("
            f"  CASE WHEN"
            f"    txo_type IN ({','.join(map(str, CLAIM_TYPES))})"
            f"  THEN amount ELSE 0 END), 0) AS claims,"
            f"COALESCE(SUM(CASE WHEN txo_type = {TXO_TYPES['support']} THEN amount ELSE 0 END), 0) AS supports,"
            f"COALESCE(SUM("
            f"  CASE WHEN"
            f"    txo_type = {TXO_TYPES['support']} AND"
            f"    TXI.address IS NOT NULL AND"
            f"    TXI.address IN (SELECT address FROM account_address WHERE account = :$account__in0)"
            f"  THEN amount ELSE 0 END), 0) AS my_supports",
            is_spent=False,
            include_is_my_input=True,
            read_only=read_only,
            **constraints
        ))[0]
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

    async def select_addresses(self, cols, read_only=False, **constraints):
        return await self.db.execute_fetchall(*query(
            f"SELECT {cols} FROM pubkey_address JOIN account_address USING (address)",
            **constraints
        ), read_only=read_only)

    async def get_addresses(self, cols=None, read_only=False, **constraints):
        cols = cols or (
            'address', 'account', 'chain', 'history', 'used_times',
            'pubkey', 'chain_code', 'n', 'depth'
        )
        addresses = await self.select_addresses(', '.join(cols), read_only=read_only, **constraints)
        if 'pubkey' in cols:
            for address in addresses:
                address['pubkey'] = PubKey(
                    self.ledger, address.pop('pubkey'), address.pop('chain_code'),
                    address.pop('n'), address.pop('depth')
                )
        return addresses

    async def get_address_count(self, cols=None, read_only=False, **constraints):
        count = await self.select_addresses('COUNT(*) as total', read_only=read_only, **constraints)
        return count[0]['total'] or 0

    async def get_address(self, read_only=False, **constraints):
        addresses = await self.get_addresses(read_only=read_only, limit=1, **constraints)
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

    async def get_claims(self, read_only=False, **constraints) -> List[Output]:
        self.constrain_claims(constraints)
        return await self.get_utxos(read_only=read_only, **constraints)

    def get_claim_count(self, **constraints):
        self.constrain_claims(constraints)
        return self.get_utxo_count(**constraints)

    @staticmethod
    def constrain_streams(constraints):
        constraints['txo_type'] = TXO_TYPES['stream']

    def get_streams(self, read_only=False, **constraints):
        self.constrain_streams(constraints)
        return self.get_claims(read_only=read_only, **constraints)

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

    async def release_all_outputs(self, account=None):
        if account is None:
            await self.db.execute_fetchall("UPDATE txo SET is_reserved = 0 WHERE is_reserved = 1")
        else:
            await self.db.execute_fetchall(
                "UPDATE txo SET is_reserved = 0 WHERE"
                "  is_reserved = 1 AND txo.address IN ("
                "    SELECT address from account_address WHERE account = ?"
                "  )", (account.public_key.address, )
            )

    def get_supports_summary(self, read_only=False, **constraints):
        return self.get_txos(
            txo_type=TXO_TYPES['support'],
            is_spent=False, is_my_output=True,
            include_is_my_input=True,
            no_tx=True, read_only=read_only,
            **constraints
        )
