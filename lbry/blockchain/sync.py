import os
import time
import logging
from glob import glob
from concurrent.futures import ProcessPoolExecutor

from .lbrycrd import Lbrycrd
from .block import read_blocks
from .db import AsyncBlockchainDB


log = logging.getLogger(__name__)


class BlockSync:

    def __init__(self, chain: Lbrycrd):
        self.chain = chain
        self.db = AsyncBlockchainDB.from_path(os.path.join(self.chain.data_path, 'regtest'))

    async def start(self):
        await self.db.open()

    async def stop(self):
        await self.db.close()

    async def cleanup(self):
        pass


def process_file(block_file):
    blocks, txs, claims, supports, spends = [], [], [], [], []
    for block in read_blocks(block_file):
        for tx in block.txs:
            txs.append((block.block_hash, tx.position, tx.hash))
            for txi in tx.inputs:
                if not txi.is_coinbase:
                    spends.append((block.block_hash, tx.hash, txi.txo_ref.hash))
            for output in tx.outputs:
                try:
                    if output.is_support:
                        supports.append((
                            block.block_hash, tx.hash, output.ref.hash, output.claim_hash, output.amount
                        ))
                    elif output.script.is_claim_name:
                        claims.append((
                            block.block_hash, tx.hash, tx.position, output.ref.hash, output.claim_hash,
                            output.claim_name, 1, output.amount, None, None
                        ))
                    elif output.script.is_update_claim:
                        claims.append((
                            block.block_hash, tx.hash, tx.position, output.ref.hash, output.claim_hash,
                            output.claim_name, 2, output.amount, None, None
                        ))
                except:
                    pass
        blocks.append((block.block_hash, block.prev_block_hash, 0 if block.is_first_block else None))

    sql = db.get()

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


async def main():

    #lbrycrd = os.path.expanduser('~/.lbrycrd/')

    output_db = '/tmp/fast_sync.db'
    if os.path.exists(output_db):
        os.remove(output_db)
    initializer(output_db)
    create_db()
    executor = ProcessPoolExecutor(
        6, initializer=initializer, initargs=(output_db,)
    )
    file_paths = glob(os.path.join(lbrycrd, 'regtest', 'blocks', 'blk*.dat'))
    file_paths.sort()
    total_blocks, total_txs = 0, 0
    start = time.perf_counter()
    for file_path, (blocks, txs) in zip(file_paths, executor.map(process_file, file_paths)):
        print(f"{file_path} {blocks}")
        total_blocks += blocks
        total_txs += txs
    print(f'blocks: {total_blocks} (txs: {total_txs}) in {time.perf_counter()-start}s')
    print('cleaning chain: set block heights and delete forks')
    #clean_chain()
    print(f'done in {time.perf_counter()-start}s')

    await blockchain.stop()
