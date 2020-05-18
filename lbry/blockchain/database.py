import os.path
import asyncio
import sqlite3
from typing import Optional
from concurrent.futures import ThreadPoolExecutor


FILES = [
    'block_index',
    'claims'
]


class BlockchainDB:

    def __init__(self, directory: str):
        self.directory = directory
        self.connection: Optional[sqlite3.Connection] = None
        self.executor: Optional[ThreadPoolExecutor] = None

    async def run_in_executor(self, *args):
        return await asyncio.get_event_loop().run_in_executor(self.executor, *args)

    def sync_open(self):
        self.connection = sqlite3.connect(
            os.path.join(self.directory, FILES[0]+'.sqlite'),
            timeout=60.0 * 5
        )
        for file in FILES[1:]:
            self.connection.execute(
                f"ATTACH DATABASE '{os.path.join(self.directory, file+'.sqlite')}' AS {file}"
            )
        self.connection.row_factory = sqlite3.Row

    async def open(self):
        assert self.executor is None, "Database is already open."
        self.executor = ThreadPoolExecutor(max_workers=1)
        return await self.run_in_executor(self.sync_open)

    def sync_close(self):
        self.connection.close()
        self.connection = None

    async def close(self):
        if self.executor is not None:
            if self.connection is not None:
                await self.run_in_executor(self.sync_close)
            self.executor.shutdown()
            self.executor = None

    def sync_execute(self, sql: str, *args):
        return self.connection.execute(sql, *args)

    async def execute(self, sql, *args):
        return await self.run_in_executor(self.sync_execute, sql, *args)

    def sync_execute_fetchall(self, sql: str, *args):
        return list(self.connection.execute(sql, *args).fetchall())

    async def execute_fetchall(self, sql: str, *args):
        return await self.run_in_executor(self.sync_execute_fetchall, sql, *args)

    def sync_get_block_files(self):
        return self.sync_execute_fetchall(
            """
            SELECT file as file_number, COUNT(hash) as blocks, SUM(txcount) as txs
            FROM block_info GROUP BY file ORDER BY file ASC;
            """
        )

    async def get_block_files(self):
        return await self.run_in_executor(self.sync_get_block_files)

    def sync_get_file_details(self, block_file):
        return self.sync_execute_fetchall(
            """
            SELECT datapos as data_offset, height, hash as block_hash, txCount as txs
            FROM block_info
            WHERE file = ? and status&1 > 0
            ORDER BY datapos ASC;
            """, (block_file,)
        )

    async def get_file_details(self, block_file):
        return await self.run_in_executor(self.sync_get_file_details, block_file)

    def sync_get_claimtrie(self):
        return self.sync_execute_fetchall(
            """
            SELECT
                takeover.name AS normalized,
                takeover.claimID AS claim_hash,
                takeover.height AS last_take_over_height,
                originalHeight AS original_height,
                updateHeight AS update_height,
                validHeight AS valid_height,
                activationHeight AS activation_height,
                expirationHeight AS expiration_height
            FROM takeover JOIN claim USING (claimID)
            GROUP BY takeover.name HAVING MAX(height);
            """
        )

    async def get_claimtrie(self):
        return await self.run_in_executor(self.sync_get_claimtrie)

    def sync_get_claims(self):
        return self.sync_execute_fetchall(
            """
            SELECT
                claimID AS claim_hash,
                txID AS tx_hash,
                txN AS position,
                amount,
                originalHeight AS original_height,
                updateHeight AS update_height,
                validHeight AS valid_height,
                activationHeight AS activation_height,
                expirationHeight AS expiration_height
            FROM claims.claim
            """
        )

    async def get_claims(self):
        return await self.run_in_executor(self.sync_get_claims)
