import os
import time
from glob import glob
import sqlite3
import asyncio
import struct
from contextvars import ContextVar
from concurrent.futures import ProcessPoolExecutor
from torba.client.bcd_data_stream import BCDataStream
from torba.client.hash import double_sha256
from lbry.wallet.transaction import Transaction
from binascii import hexlify


db = ContextVar('db')


def initializer(_path):
    _db = sqlite3.connect(_path, isolation_level=None, uri=True, timeout=60.0*5)
    _db.row_factory = sqlite3.Row
    _db.executescript("""
    pragma journal_mode=wal;
    """)
    db.set(_db)


def read_block(block: bytes):
    reader = BCDataStream()
    reader.data = block


ZERO_BLOCK = bytes((0,)*32)


def parse_header(header):
    version, = struct.unpack('<I', header[:4])
    timestamp, bits, nonce = struct.unpack('<III', header[100:112])
    return {
        'version': version,
        'block_hash': double_sha256(header),
        'prev_block_hash': header[4:36],
        'merkle_root': header[36:68],
        'claim_trie_root': header[68:100][::-1],
        'timestamp': timestamp,
        'bits': bits,
        'nonce': nonce,
    }


def parse_txs(stream):
    tx_count = stream.read_compact_size()
    return [Transaction.from_stream(i, stream) for i in range(tx_count)]


def process_file(file_path):
    sql = db.get()
    stream = BCDataStream()
    stream.data = open(file_path, 'rb')
    blocks, txs, claims, supports, spends = [], [], [], [], []
    while stream.read_uint32() == 4054508794:
        block_size = stream.read_uint32()
        header = parse_header(stream.data.read(112))
        is_first_block = header['prev_block_hash'] == ZERO_BLOCK
        for tx in parse_txs(stream):
            txs.append((header['block_hash'], tx.position, tx.hash))
            for txi in tx.inputs:
                if not txi.is_coinbase:
                    spends.append((header['block_hash'], tx.hash, txi.txo_ref.hash))
            for output in tx.outputs:
                try:
                    if output.is_support:
                        supports.append((
                            header['block_hash'], tx.hash, output.ref.hash, output.claim_hash, output.amount
                        ))
                    elif output.script.is_claim_name:
                        claims.append((
                            header['block_hash'], tx.hash, tx.position, output.ref.hash, output.claim_hash,
                            output.claim_name, 1, output.amount, None, None
                        ))
                    elif output.script.is_update_claim:
                        claims.append((
                            header['block_hash'], tx.hash, tx.position, output.ref.hash, output.claim_hash,
                            output.claim_name, 2, output.amount, None, None
                        ))
                except:
                    pass
        blocks.append((header['block_hash'], header['prev_block_hash'], 0 if is_first_block else None))

    sql.execute('begin;')
    sql.executemany("insert into block values (?, ?, ?)", blocks)
    sql.execute('commit;')

    sql.execute('begin;')
    sql.executemany("insert into tx values (?, ?, ?)", txs)
    sql.execute('commit;')

    sql.execute('begin;')
    sql.executemany("insert into txi values (?, ?, ?)", spends)
    sql.execute('commit;')

    sql.execute('begin;')
    sql.executemany("insert into support values (?, ?, ?, ?, ?)", supports)
    sql.execute('commit;')

    sql.execute('begin;')
    sql.executemany("insert into claim_history values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", claims)
    sql.execute('commit;')

    return len(blocks), len(txs)


def create_db():
    sql = db.get()
    sql.executescript("""
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
    """)


def clean_chain():
    sql = db.get()

    print('traversing chain and setting height')
    sql.execute('begin;')

    print(' + adding unique block (block_hash) index')
    sql.execute("create unique index block_hash_idx on block (block_hash)")

    print(' + adding block (previous_hash) index')
    sql.execute("create index block_previous_block_hash_idx on block (previous_hash)")

    print(' * setting block.height')
    sql.execute("""
    WITH RECURSIVE blocks(block_hash, previous_hash, height) AS (
        SELECT block_hash, previous_hash, height from block WHERE height = 0
        UNION
        SELECT block.block_hash, block.previous_hash, blocks.height+1
            FROM block, blocks
            WHERE block.previous_hash=blocks.block_hash
    )
    UPDATE block SET height=(SELECT height FROM blocks WHERE block.block_hash=blocks.block_hash)
    """)

    print(' + adding block (height) index')
    sql.execute("create index block_height_idx on block (height)")

    for table in ('tx', 'txi', 'claim_history', 'support'):
        print(f' + adding {table} (block_hash) index')
        sql.execute(f"create index {table}_block_hash_idx on {table} (block_hash)")

    sql.execute('commit;')
    sql.execute('begin;')

    print(' - deleting forks:')
    forks = sql.execute("""
    WITH RECURSIVE blocks(block_hash, previous_hash) AS (
        SELECT block_hash, previous_hash FROM block WHERE
            block_hash NOT IN (SELECT previous_hash FROM block) AND
            height != (SELECT MAX(height) FROM block)
        UNION
        SELECT block.block_hash, block.previous_hash FROM block, blocks WHERE
            block.block_hash=blocks.previous_hash AND
            (SELECT COUNT(*) FROM block forks WHERE forks.height=block.height) > 1
    )
    SELECT block_hash FROM blocks;
    """)
    for i, fork in enumerate(forks):
        sql.execute('DELETE FROM block WHERE block_hash = ?', (fork[0],))
        print(f'  - block (fork:{i+1}): {hexlify(fork[0][::-1]).decode()}')
        deleted_stats = {}
        for table in ('tx', 'txi', 'claim_history', 'support'):
            deleted = sql.execute(f"DELETE FROM {table} WHERE block_hash = ?", (fork[0],)).rowcount
            if deleted > 0:
                deleted_stats[table] = deleted
        print(f'   - {deleted_stats}')

    sql.execute('commit;')
    sql.execute('begin;')

    print(' + adding unique tx (tx_hash, block_hash) index')
    sql.execute("create unique index tx_hash_idx on tx (tx_hash, block_hash)")
    print(' + adding unique txi (txo_hash) index')
    sql.execute("create unique index txi_txo_hash_idx on txi (txo_hash)")

    print('processing claim history & populating claim table')

    print(' * setting claim_history.height and claim_history.is_spent')
    sql.execute("""
    UPDATE claim_history SET
    height = (SELECT height FROM tx JOIN block USING (block_hash) WHERE tx.tx_hash=claim_history.tx_hash),
    is_spent = COALESCE((SELECT 1 FROM txi WHERE txo_hash=claim_history.txo_hash), 0)
    """)

    print(' + adding claim_history (claim_hash) index')
    sql.execute("create index claim_history_hash_idx on claim_history (claim_hash)")

    print(' * populating claim table')
    sql.execute("""
    INSERT INTO claim
    SELECT txo_hash, claim_history.claim_hash, claim_name, amount, height FROM (
        SELECT claim_hash, is_spent FROM claim_history
        GROUP BY claim_hash HAVING MAX(height) AND MAX(tx_position)
    ) AS latest_claim_state JOIN claim_history USING (claim_hash)
    WHERE latest_claim_state.is_spent=0;
    """)

    sql.execute('commit;')


async def main():
    db_file = '/tmp/fast_sync.db'
    if os.path.exists(db_file):
        os.remove(db_file)
    initializer(db_file)
    create_db()
    executor = ProcessPoolExecutor(
        4, initializer=initializer, initargs=(db_file,)
    )
    file_paths = glob(os.path.join(os.path.expanduser('~/.lbrycrd/blocks/'), 'blk*.dat'))
    file_paths.sort()
    total_blocks, total_txs = 0, 0
    start = time.perf_counter()
    for file_path, (blocks, txs) in zip(file_paths, executor.map(process_file, file_paths)):
        print(f"{file_path} {blocks}")
        total_blocks += blocks
        total_txs += txs
    print(f'blocks: {total_blocks} (txs: {total_txs}) in {time.perf_counter()-start}s')
    print('cleaning chain: set block heights and delete forks')
    clean_chain()
    print(f'done in {time.perf_counter()-start}s')
    executor.shutdown(True)

if __name__ == '__main__':
    asyncio.run(main())
