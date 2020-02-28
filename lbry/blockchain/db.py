import os
import asyncio
from concurrent import futures
from collections import namedtuple, deque

import sqlite3
import apsw


DDL = """
pragma journal_mode=WAL;

create table if not exists block (
    block_hash bytes not null primary key,
    previous_hash bytes not null,
    file_number integer not null,
    height int
);
create table if not exists tx (
    block_hash integer not null,
    position integer not null,
    tx_hash bytes not null
);
create table if not exists txi (
    block_hash bytes not null,
    tx_hash bytes not null,
    txo_hash bytes not null
);
create table if not exists claim (
    txo_hash bytes not null,
    claim_hash bytes not null,
    claim_name text not null,
    amount integer not null,
    height integer
);
create table if not exists claim_history (
    block_hash bytes not null,
    tx_hash bytes not null,
    tx_position integer not null,
    txo_hash bytes not null,
    claim_hash bytes not null,
    claim_name text not null,
    action integer not null,
    amount integer not null,
    height integer,
    is_spent bool
);
create table if not exists support (
    block_hash bytes not null,
    tx_hash bytes not null,
    txo_hash bytes not null,
    claim_hash bytes not null,
    amount integer not null
);
"""


class BlockchainDB:

    __slots__ = 'db', 'directory'

    def __init__(self, path: str):
        self.db = None
        self.directory = path

    @property
    def db_file_path(self):
        return os.path.join(self.directory, 'blockchain.db')

    def open(self):
        self.db = sqlite3.connect(self.db_file_path, isolation_level=None, uri=True, timeout=60.0 * 5)
        self.db.executescript("""
        pragma journal_mode=wal;
        """)
#        self.db = apsw.Connection(
#            self.db_file_path,
#            flags=(
#                apsw.SQLITE_OPEN_READWRITE |
#                apsw.SQLITE_OPEN_CREATE |
#                apsw.SQLITE_OPEN_URI
#            )
#        )
        self.execute_ddl(DDL)
        self.execute(f"ATTACH ? AS block_index", ('file:'+os.path.join(self.directory, 'block_index.sqlite')+'?mode=ro',))
        #def exec_factory(cursor, statement, bindings):
        #    tpl = namedtuple('row', (d[0] for d in cursor.getdescription()))
        #    cursor.setrowtrace(lambda cursor, row: tpl(*row))
        #    return True
        #self.db.setexectrace(exec_factory)
        def row_factory(cursor, row):
            tpl = namedtuple('row', (d[0] for d in cursor.description))
            return tpl(*row)
        self.db.row_factory = row_factory
        return self

    def close(self):
        if self.db is not None:
            self.db.close()

    def execute(self, *args):
        return self.db.cursor().execute(*args)

    def execute_many(self, *args):
        return self.db.cursor().executemany(*args)

    def execute_many_tx(self, *args):
        cursor = self.db.cursor()
        cursor.execute('begin;')
        result = cursor.executemany(*args)
        cursor.execute('commit;')
        return result

    def execute_ddl(self, *args):
        self.db.executescript(*args)
        #deque(self.execute(*args), maxlen=0)

    def begin(self):
        self.execute('begin;')

    def commit(self):
        self.execute('commit;')

    def get_block_file_path_from_number(self, block_file_number):
        return os.path.join(self.directory, 'blocks', f'blk{block_file_number:05}.dat')

    def get_block_files_not_synced(self):
        return list(self.execute(
            """
            SELECT file as file_number, COUNT(hash) as blocks, SUM(txcount) as txs
            FROM block_index.block_info
            WHERE hash NOT IN (SELECT block_hash FROM block)
            GROUP BY file ORDER BY file ASC;
            """
        ))

    def get_blocks_not_synced(self, block_file):
        return self.execute(
            """
            SELECT datapos as data_offset, height, hash as block_hash, txCount as txs
            FROM block_index.block_info
            WHERE file = ? AND hash NOT IN (SELECT block_hash FROM block)
            ORDER BY datapos ASC;
            """, (block_file,)
        )


class AsyncBlockchainDB:

    def __init__(self, db: BlockchainDB):
        self.sync_db = db
        self.executor = futures.ThreadPoolExecutor(max_workers=1)

    @classmethod
    def from_path(cls, path: str) -> 'AsyncBlockchainDB':
        return cls(BlockchainDB(path))

    def get_block_file_path_from_number(self, block_file_number):
        return self.sync_db.get_block_file_path_from_number(block_file_number)

    async def run_in_executor(self, func, *args):
        return await asyncio.get_running_loop().run_in_executor(
            self.executor, func, *args
        )

    async def open(self):
        return await self.run_in_executor(self.sync_db.open)

    async def close(self):
        return await self.run_in_executor(self.sync_db.close)

    async def get_block_files_not_synced(self):
        return await self.run_in_executor(self.sync_db.get_block_files_not_synced)
