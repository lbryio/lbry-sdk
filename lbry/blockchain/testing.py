import os
import sqlite3
import asyncio
from typing import List

from .block import Block
from .lbrycrd import Lbrycrd


def sync_create_lbrycrd_databases(dir_path: str):
    for file_name, ddl in DDL.items():
        connection = sqlite3.connect(os.path.join(dir_path, file_name))
        connection.executescript(ddl)
        connection.close()


async def create_lbrycrd_databases(dir_path: str):
    await asyncio.get_running_loop().run_in_executor(
        None, sync_create_lbrycrd_databases, dir_path
    )


async def add_block_to_lbrycrd(chain: Lbrycrd, block: Block, takeovers: List[str]):
    for tx in block.txs:
        for txo in tx.outputs:
            if txo.is_claim:
                await insert_claim(chain, block, tx, txo)
                if txo.id in takeovers:
                    await insert_takeover(chain, block, tx, txo)


async def insert_claim(chain, block, tx, txo):
    await chain.db.execute(
        """
        INSERT OR REPLACE INTO claim (
            claimID, name, nodeName, txID, txN, originalHeight, updateHeight, validHeight,
            activationHeight, expirationHeight, amount
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 10000, ?)
        """, (
            txo.claim_hash, txo.claim_name, txo.claim_name, tx.hash, txo.position,
            block.height, block.height, block.height, block.height, txo.amount
        )
    )


async def insert_takeover(chain, block, tx, txo):
    await chain.db.execute(
        "INSERT INTO takeover (name) VALUES (?)",
        (txo.claim_name,)
    )


# These are extracted by opening each of lbrycrd latest sqlite databases and
# running '.schema' command.
DDL = {
    'claims.sqlite': """
    CREATE TABLE node (name BLOB NOT NULL PRIMARY KEY, parent BLOB REFERENCES node(name) DEFERRABLE INITIALLY DEFERRED, hash BLOB);
    CREATE TABLE claim (claimID BLOB NOT NULL PRIMARY KEY, name BLOB NOT NULL, nodeName BLOB NOT NULL REFERENCES node(name) DEFERRABLE INITIALLY DEFERRED, txID BLOB NOT NULL, txN INTEGER NOT NULL, originalHeight INTEGER NOT NULL, updateHeight INTEGER NOT NULL, validHeight INTEGER NOT NULL, activationHeight INTEGER NOT NULL, expirationHeight INTEGER NOT NULL, amount INTEGER NOT NULL);
    CREATE TABLE support (txID BLOB NOT NULL, txN INTEGER NOT NULL, supportedClaimID BLOB NOT NULL, name BLOB NOT NULL, nodeName BLOB NOT NULL, blockHeight INTEGER NOT NULL, validHeight INTEGER NOT NULL, activationHeight INTEGER NOT NULL, expirationHeight INTEGER NOT NULL, amount INTEGER NOT NULL, PRIMARY KEY(txID, txN));
    CREATE TABLE takeover (name BLOB NOT NULL, height INTEGER NOT NULL, claimID BLOB, PRIMARY KEY(name, height DESC));
    CREATE INDEX node_hash_len_name ON node (hash, LENGTH(name) DESC);
    CREATE INDEX node_parent ON node (parent);
    CREATE INDEX takeover_height ON takeover (height);
    CREATE INDEX claim_activationHeight ON claim (activationHeight);
    CREATE INDEX claim_expirationHeight ON claim (expirationHeight);
    CREATE INDEX claim_nodeName ON claim (nodeName);
    CREATE INDEX support_supportedClaimID ON support (supportedClaimID);
    CREATE INDEX support_activationHeight ON support (activationHeight);
    CREATE INDEX support_expirationHeight ON support (expirationHeight);
    CREATE INDEX support_nodeName ON support (nodeName);
    """,
    'block_index.sqlite': """
    CREATE TABLE block_file (file INTEGER NOT NULL PRIMARY KEY, blocks INTEGER NOT NULL, size INTEGER NOT NULL, undoSize INTEGER NOT NULL, heightFirst INTEGER NOT NULL, heightLast INTEGER NOT NULL, timeFirst INTEGER NOT NULL, timeLast INTEGER NOT NULL );
    CREATE TABLE block_info (hash BLOB NOT NULL PRIMARY KEY, prevHash BLOB NOT NULL, height INTEGER NOT NULL, file INTEGER NOT NULL, dataPos INTEGER NOT NULL, undoPos INTEGER NOT NULL, txCount INTEGER NOT NULL, status INTEGER NOT NULL, version INTEGER NOT NULL, rootTxHash BLOB NOT NULL, rootTrieHash BLOB NOT NULL, time INTEGER NOT NULL, bits INTEGER NOT NULL, nonce INTEGER NOT NULL );
    CREATE TABLE tx_to_block (txID BLOB NOT NULL PRIMARY KEY, file INTEGER NOT NULL, blockPos INTEGER NOT NULL, txPos INTEGER NOT NULL);
    CREATE TABLE flag (name TEXT NOT NULL PRIMARY KEY, value INTEGER NOT NULL);
    CREATE INDEX block_info_height ON block_info (height);
    """,
}
