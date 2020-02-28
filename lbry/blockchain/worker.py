from typing import Optional
from contextvars import ContextVar
from multiprocessing import Queue, Event
from dataclasses import dataclass
from itertools import islice

from lbry.wallet.bcd_data_stream import BCDataStream
from .db import BlockchainDB
from .block import Block


PENDING = 'pending'
RUNNING = 'running'
STOPPED = 'stopped'


def chunk(rows, step):
    it, total = iter(rows), len(rows)
    for _ in range(0, total, step):
        yield min(step, total), islice(it, step)
        total -= step


@dataclass
class WorkerContext:
    db: BlockchainDB
    progress: Queue
    stop: Event


context: ContextVar[Optional[WorkerContext]] = ContextVar('context')


def initializer(data_dir: str, progress: Queue, stop: Event):
    context.set(WorkerContext(
        db=BlockchainDB(data_dir).open(),
        progress=progress,
        stop=stop
    ))


def process_block_file(block_file_number):
    ctx: WorkerContext = context.get()
    db, progress, stop = ctx.db, ctx.progress, ctx.stop
    block_file_path = db.get_block_file_path_from_number(block_file_number)
    num = 0
    progress.put_nowait((block_file_number, 1, num))
    with open(block_file_path, 'rb') as fp:
        stream = BCDataStream(fp=fp)
        blocks, txs, claims, supports, spends = [], [], [], [], []
        for num, block_info in enumerate(db.get_blocks_not_synced(block_file_number), start=1):
            if ctx.stop.is_set():
                return
            if num % 100 == 0:
                progress.put_nowait((block_file_number, 1, num))
            fp.seek(block_info.data_offset)
            block = Block(stream)
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
            blocks.append((block.block_hash, block.prev_block_hash, block_file_number, 0 if block.is_first_block else None))

    progress.put((block_file_number, 1, num))

    queries = (
        ("insert into block values (?, ?, ?, ?)", blocks),
        ("insert into tx values (?, ?, ?)", txs),
        ("insert into txi values (?, ?, ?)", spends),
        ("insert into support values (?, ?, ?, ?, ?)", supports),
        ("insert into claim_history values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", claims),
    )
    total_txs = len(txs)
    done_txs = 0
    step = int(sum(len(q[1]) for q in queries)/total_txs)
    progress.put((block_file_number, 2, done_txs))
    for sql, rows in queries:
        for chunk_size, chunk_rows in chunk(rows, 10000):
            db.execute_many_tx(sql, chunk_rows)
            done_txs += int(chunk_size/step)
            progress.put((block_file_number, 2, done_txs))
    progress.put((block_file_number, 2, total_txs))
