import os
import asyncio
import logging
import multiprocessing as mp
from contextvars import ContextVar
from typing import Tuple, Optional
from concurrent.futures import Executor, ThreadPoolExecutor, ProcessPoolExecutor

from sqlalchemy import func, bindparam
from sqlalchemy.future import select

from lbry.event import EventController, BroadcastSubscription
from lbry.service.base import Service, Sync, BlockEvent
from lbry.db import queries, TXO_TYPES
from lbry.db.tables import Claim, Claimtrie, TX, TXO, TXI, Block as BlockTable

from .lbrycrd import Lbrycrd
from .block import Block, create_block_filter, get_block_filter
from .bcd_data_stream import BCDataStream
from .ledger import Ledger


log = logging.getLogger(__name__)
_context: ContextVar[Tuple[Lbrycrd, mp.Queue, mp.Event]] = ContextVar('ctx')


def ctx():
    return _context.get()


def initialize(url: str, ledger: Ledger, progress: mp.Queue, stop: mp.Event, track_metrics=False):
    chain = Lbrycrd(ledger)
    chain.db.sync_open()
    _context.set((chain, progress, stop))
    queries.initialize(url=url, ledger=ledger, track_metrics=track_metrics)


def process_block_file(block_file_number):
    chain, progress, stop = ctx()
    block_file_path = chain.get_block_file_path_from_number(block_file_number)
    num = 0
    progress.put_nowait((block_file_number, 1, num))
    best_height = queries.get_best_height()
    best_block_processed = -1
    collector = queries.RowCollector(queries.ctx())
    with open(block_file_path, 'rb') as fp:
        stream = BCDataStream(fp=fp)
        for num, block_info in enumerate(chain.db.sync_get_file_details(block_file_number), start=1):
            if stop.is_set():
                return
            if num % 100 == 0:
                progress.put_nowait((block_file_number, 1, num))
            fp.seek(block_info['data_offset'])
            block = Block.from_data_stream(stream, block_info['height'], block_file_number)
            if block.height <= best_height:
                continue
            best_block_processed = max(block.height, best_block_processed)
            collector.add_block(block)
    collector.save(lambda remaining, total: progress.put((block_file_number, 2, remaining, total)))
    return best_block_processed


def process_claimtrie():
    execute = queries.ctx().execute
    chain, progress, stop = ctx()

    execute(Claimtrie.delete())
    for record in chain.db.sync_get_claimtrie():
        execute(
            Claimtrie.insert(), {
                'normalized': record['normalized'],
                'claim_hash': record['claim_hash'],
                'last_take_over_height': record['last_take_over_height'],
            }
        )

    best_height = queries.get_best_height()

    for record in chain.db.sync_get_claims():
        execute(
            Claim.update()
            .where(Claim.c.claim_hash == record['claim_hash'])
            .values(
                activation_height=record['activation_height'],
                expiration_height=record['expiration_height']
            )
        )

    support = TXO.alias('support')
    effective_amount_update = (
        Claim.update()
        .where(Claim.c.activation_height <= best_height)
        .values(
            effective_amount=(
                select(func.coalesce(func.sum(support.c.amount), 0) + Claim.c.amount)
                .select_from(support).where(
                    (support.c.claim_hash == Claim.c.claim_hash) &
                    (support.c.txo_type == TXO_TYPES['support']) &
                    (support.c.txo_hash.notin_(select(TXI.c.txo_hash)))
                ).scalar_subquery()
            )
        )
    )
    execute(effective_amount_update)


def process_block_and_tx_filters():
    context = queries.ctx()
    execute = context.execute
    ledger = context.ledger

    blocks = []
    all_filters = []
    all_addresses = []
    for block in queries.get_blocks_without_filters():
        addresses = {
            ledger.address_to_hash160(r['address'])
            for r in queries.get_block_tx_addresses(block_hash=block['block_hash'])
        }
        all_addresses.extend(addresses)
        block_filter = create_block_filter(addresses)
        all_filters.append(block_filter)
        blocks.append({'pk': block['block_hash'], 'block_filter': block_filter})
    filters = [get_block_filter(f) for f in all_filters]
    execute(BlockTable.update().where(BlockTable.c.block_hash == bindparam('pk')), blocks)

#    txs = []
#    for tx in queries.get_transactions_without_filters():
#        tx_filter = create_block_filter(
#            {r['address'] for r in queries.get_block_tx_addresses(tx_hash=tx['tx_hash'])}
#        )
#        txs.append({'pk': tx['tx_hash'], 'tx_filter': tx_filter})
#    execute(TX.update().where(TX.c.tx_hash == bindparam('pk')), txs)


class BlockchainSync(Sync):

    def __init__(self, service: Service, chain: Lbrycrd, multiprocess=False):
        super().__init__(service)
        self.chain = chain
        self.message_queue = mp.Queue()
        self.stop_event = mp.Event()
        self.on_block_subscription: Optional[BroadcastSubscription] = None
        self.advance_loop_task: Optional[asyncio.Task] = None
        self.advance_loop_event = asyncio.Event()
        self.executor = self._create_executor(multiprocess)
        self._on_progress_controller = EventController()
        self.on_progress = self._on_progress_controller.stream

    def _create_executor(self, multiprocess) -> Executor:
        args = dict(
            initializer=initialize,
            initargs=(
                self.service.db.url, self.chain.ledger,
                self.message_queue, self.stop_event
            )
        )
        if multiprocess:
            return ProcessPoolExecutor(
                max_workers=max(os.cpu_count() - 1, 4), **args
            )
        else:
            return ThreadPoolExecutor(
                max_workers=1, **args
            )

    async def start(self):
        await self.advance()
        self.chain.subscribe()
        self.advance_loop_task = asyncio.create_task(self.advance_loop())
        self.on_block_subscription = self.chain.on_block.listen(
            lambda e: self.advance_loop_event.set()
        )

    async def stop(self):
        self.chain.unsubscribe()
        if self.on_block_subscription is not None:
            self.on_block_subscription.cancel()
        self.stop_event.set()
        self.advance_loop_task.cancel()
        self.executor.shutdown()

    async def load_blocks(self):
        tasks = []
        for file in await self.chain.db.get_block_files():
            tasks.append(asyncio.get_running_loop().run_in_executor(
                self.executor, process_block_file, file['file_number']
            ))
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_EXCEPTION
        )
        if pending:
            self.stop_event.set()
            for future in pending:
                future.cancel()
        return max(f.result() for f in done)

    async def process_claims(self):
        await asyncio.get_event_loop().run_in_executor(
            self.executor, queries.process_claims_and_supports
        )

    async def process_block_and_tx_filters(self):
        await asyncio.get_event_loop().run_in_executor(
            self.executor, process_block_and_tx_filters
        )

    async def process_claimtrie(self):
        await asyncio.get_event_loop().run_in_executor(
            self.executor, process_claimtrie
        )

    async def post_process(self):
        await self.process_claims()
        if self.service.conf.spv_address_filters:
            await self.process_block_and_tx_filters()
        await self.process_claimtrie()

    async def advance(self):
        best_height = await self.load_blocks()
        await self.post_process()
        await self._on_block_controller.add(BlockEvent(best_height))

    async def advance_loop(self):
        while True:
            await self.advance_loop_event.wait()
            self.advance_loop_event.clear()
            await self.advance()
