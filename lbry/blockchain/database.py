import os.path
import sqlite3
from typing import Optional


class BlockchainDB:

    __slots__ = 'file_path', 'db'

    def __init__(self, directory: str):
        self.file_path = f"file:{os.path.join(directory, 'block_index.sqlite')}?mode=ro"
        self.db: Optional[sqlite3.Connection] = None

    def open(self):
        self.db = sqlite3.connect(self.file_path, uri=True, timeout=60.0 * 5)
        self.db.row_factory = sqlite3.Row

    def execute(self, *args, **kwargs):
        if self.db is None:
            self.open()
        return list(self.db.execute(*args, **kwargs).fetchall())

    def get_block_files(self):
        return self.execute(
            """
            SELECT file as file_number, COUNT(hash) as blocks, SUM(txcount) as txs
            FROM block_info GROUP BY file ORDER BY file ASC;
            """
        )

    def get_file_details(self, block_file):
        return self.execute(
            """
            SELECT datapos as data_offset, height, hash as block_hash, txCount as txs
            FROM block_info WHERE file = ? ORDER BY datapos ASC;
            """, (block_file,)
        )
