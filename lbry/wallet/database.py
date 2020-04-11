import os
import logging
import asyncio
import sqlite3
import platform
from binascii import hexlify
from dataclasses import dataclass
from contextvars import ContextVar
from concurrent.futures.thread import ThreadPoolExecutor
from concurrent.futures.process import ProcessPoolExecutor
from typing import Tuple, List, Union, Callable, Any, Awaitable, Iterable, Dict, Optional


log = logging.getLogger(__name__)
sqlite3.enable_callback_tracebacks(True)


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


if platform.system() == 'Windows' or 'ANDROID_ARGUMENT' in os.environ:
    ReaderExecutorClass = ThreadPoolExecutor
else:
    ReaderExecutorClass = ProcessPoolExecutor


class AIOSQLite:
    reader_executor: ReaderExecutorClass

    def __init__(self):
        # has to be single threaded as there is no mapping of thread:connection
        self.writer_executor = ThreadPoolExecutor(max_workers=1)
        self.writer_connection: Optional[sqlite3.Connection] = None
        self._closing = False
        self.query_count = 0
        self.write_lock = asyncio.Lock()
        self.writers = 0
        self.read_ready = asyncio.Event()

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
        return db

    async def close(self):
        if self._closing:
            return
        self._closing = True
        await asyncio.get_event_loop().run_in_executor(self.writer_executor, self.writer_connection.close)
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
        if read_only:
            while self.writers:
                await self.read_ready.wait()
            return await asyncio.get_event_loop().run_in_executor(
                self.reader_executor, read_only_fn, sql, parameters
            )
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
        self.writers += 1
        self.read_ready.clear()
        async with self.write_lock:
            try:
                return await asyncio.get_event_loop().run_in_executor(
                    self.writer_executor, lambda: self.__run_transaction(fun, *args, **kwargs)
                )
            finally:
                self.writers -= 1
                if not self.writers:
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


def dict_row_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d
