import os
import asyncio
import logging
import multiprocessing as mp
from contextvars import ContextVar
from typing import Tuple, Optional
from concurrent.futures import Executor, ThreadPoolExecutor, ProcessPoolExecutor

from sqlalchemy import func, bindparam
from sqlalchemy.future import select

from lbry.event import EventController, BroadcastSubscription, EventQueuePublisher
from lbry.service.base import Sync, BlockEvent
from lbry.db import Database, queries, TXO_TYPES
from lbry.db.tables import Claim, Claimtrie, TX, TXO, TXI, Block as BlockTable

from .lbrycrd import Lbrycrd
from .block import Block, create_block_filter, get_block_filter
from .bcd_data_stream import BCDataStream
from .ledger import Ledger


log = logging.getLogger(__name__)
_context: ContextVar[Tuple[Lbrycrd, mp.Queue, mp.Event, int]] = ContextVar('ctx')


def ctx():
    return _context.get()


def initialize(url: str, ledger: Ledger, progress: mp.Queue, stop: mp.Event, track_metrics: bool):
    chain = Lbrycrd(ledger)
    chain.db.sync_open()
    _context.set((chain, progress, stop, os.getpid()))
    queries.initialize(url=url, ledger=ledger, track_metrics=track_metrics)


PARSING = 1
SAVING = 2
PROCESSED = 3
FINISHED = 4


def process_block_file(block_file_number):
    chain, progress, stop, pid = ctx()
    block_file_path = chain.get_block_file_path_from_number(block_file_number)
    current_height = queries.get_best_height()
    new_blocks = chain.db.sync_get_blocks_in_file(block_file_number, current_height)
    if not new_blocks:
        return -1
    num = 0
    total = len(new_blocks)
    progress.put_nowait((PARSING, pid, block_file_number, num, total))
    collector = queries.RowCollector(queries.ctx())
    last_block_processed = -1
    with open(block_file_path, 'rb') as fp:
        stream = BCDataStream(fp=fp)
        for num, block_info in enumerate(new_blocks, start=1):
            if stop.is_set():
                return -1
            block_height = block_info['height']
            fp.seek(block_info['data_offset'])
            block = Block.from_data_stream(stream, block_height, block_file_number)
            collector.add_block(block)
            last_block_processed = block_height
            if num % 100 == 0:
                progress.put_nowait((PARSING, pid, block_file_number, num, total))
    progress.put_nowait((PARSING, pid, block_file_number, num, total))
    collector.save(
        lambda remaining, total: progress.put_nowait(
            (SAVING, pid, block_file_number, remaining, total)
        )
    )
    progress.put((PROCESSED, pid, block_file_number))
    return last_block_processed


def process_claimtrie():
    execute = queries.ctx().execute
    chain, progress, stop, _ = ctx()

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


class SyncMessageToEvent(EventQueuePublisher):

    def message_to_event(self, message):
        if message[0] == PARSING:
            event = "blockchain.sync.parsing"
        elif message[0] == SAVING:
            event = "blockchain.sync.saving"
        elif message[0] == PROCESSED:
            return {
                "event": "blockchain.sync.processed",
                "data": {"pid": message[1], "block_file": message[2]}
            }
        elif message[0] == FINISHED:
            return {
                'event': 'blockchain.sync.finish',
                'data': {'finished_height': message[1]}
            }
        else:
            raise ValueError("Unknown message type.")
        return {
            "event": event,
            "data": {
                "pid": message[1],
                "block_file": message[2],
                "step": message[3],
                "total": message[4]
            }
        }


class BlockchainSync(Sync):

    def __init__(self, chain: Lbrycrd, db: Database, processes=-1):
        super().__init__(chain.ledger, db)
        self.chain = chain
        self.message_queue = mp.Queue()
        self.stop_event = mp.Event()
        self.on_block_subscription: Optional[BroadcastSubscription] = None
        self.advance_loop_task: Optional[asyncio.Task] = None
        self.advance_loop_event = asyncio.Event()
        self._on_progress_controller = EventController()
        self.on_progress = self._on_progress_controller.stream
        self.progress_publisher = SyncMessageToEvent(
            self.message_queue, self._on_progress_controller
        )
        self.track_metrics = False
        self.processes = self._normalize_processes(processes)
        self.executor = self._create_executor()

    @staticmethod
    def _normalize_processes(processes):
        if processes == 0:
            return os.cpu_count()
        elif processes > 0:
            return processes
        return 1

    def _create_executor(self) -> Executor:
        args = dict(
            initializer=initialize,
            initargs=(
                self.db.url, self.chain.ledger,
                self.message_queue, self.stop_event,
                self.track_metrics
            )
        )
        if self.processes > 1:
            return ProcessPoolExecutor(max_workers=self.processes, **args)
        else:
            return ThreadPoolExecutor(max_workers=1, **args)

    async def start(self):
        self.progress_publisher.start()
        self.advance_loop_task = asyncio.create_task(self.advance())
        await self.advance_loop_task
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
        self.progress_publisher.stop()
        self.executor.shutdown()

    async def load_blocks(self):
        tasks = []
        best_height = await self.db.get_best_height()
        tx_count = block_count = ending_height = 0
        #for file in (await self.chain.db.get_block_files(best_height))[:1]:
        for file in await self.chain.db.get_block_files(best_height):
            tx_count += file['txs']
            block_count += file['blocks']
            ending_height = max(ending_height, file['max_height'])
            tasks.append(asyncio.get_running_loop().run_in_executor(
                self.executor, process_block_file, file['file_number']
            ))
        await self._on_progress_controller.add({
            'event': 'blockchain.sync.start',
            'data': {
                'starting_height': best_height,
                'ending_height': ending_height,
                'files': len(tasks),
                'blocks': block_count,
                'txs': tx_count
            }
        })
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_EXCEPTION
        )
        if pending:
            self.stop_event.set()
            for future in pending:
                future.cancel()
        best_height_processed = max(f.result() for f in done)
        # putting event in queue instead of add to progress_controller because
        # we want this message to appear after all of the queued messages from workers
        self.message_queue.put((FINISHED, best_height_processed))
        return best_height_processed

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
        if self.conf.spv_address_filters:
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
