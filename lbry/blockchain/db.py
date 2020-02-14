import os
import asyncio
from collections import namedtuple

import apsw


DDL = """
pragma journal_mode=WAL;

create table block (
    block_hash bytes not null,
    previous_hash bytes not null,
    height int
);
create table tx (
    block_hash integer not null,
    position integer not null,
    tx_hash bytes not null
);
create table txi (
    block_hash bytes not null,
    tx_hash bytes not null,
    txo_hash bytes not null
);
create table claim (
    txo_hash bytes not null,
    claim_hash bytes not null,
    claim_name text not null,
    amount integer not null,
    height integer
);
create table claim_history (
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
create table support (
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

    def open(self):
        self.db = apsw.Connection(
            os.path.join(self.directory, 'blockchain.db'),
            flags=(
                apsw.SQLITE_OPEN_READWRITE |
                apsw.SQLITE_OPEN_CREATE |
                apsw.SQLITE_OPEN_URI
            )
        )
        def exec_factory(cursor, statement, bindings):
            tpl = namedtuple('row', (d[0] for d in cursor.getdescription()))
            cursor.setrowtrace(lambda cursor, row: tpl(*row))
            return True
        self.db.setexectrace(exec_factory)
        self.execute(DDL)
        self.execute(f"ATTACH {os.path.join(self._db_path, 'block_index.sqlite')} AS block_index")

    def close(self):
        if self.db is not None:
            self.db.close()

    def execute(self, *args):
        return self.db.cursor().execute(*args)

    def executemany(self, *args):
        return self.db.cursor().executemany(*args)

    def begin(self):
        self.execute('begin;')

    def commit(self):
        self.execute('commit;')

    def get_blocks(self):
        pass


class AsyncBlockchainDB:

    __slots__ = 'db',

    def __init__(self, db: BlockchainDB):
        self.db = db

    @classmethod
    def from_path(cls, path: str):
        return cls(BlockchainDB(path))

    @staticmethod
    async def run_in_executor(func, *args):
        return await asyncio.get_running_loop().run_in_executor(
            None, func, *args
        )

    async def open(self):
        return await self.run_in_executor(self.db.open)

    async def close(self):
        return await self.run_in_executor(self.db.close)

    async def get_blocks(self):
        return await self.run_in_executor(self.db.get_blocks)
