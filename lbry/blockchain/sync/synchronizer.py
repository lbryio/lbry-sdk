import os
import asyncio
import logging
from typing import Optional, Tuple

from lbry.db import Database
from lbry.db.query_context import Event
from lbry.event import BroadcastSubscription
from lbry.service.base import Sync, BlockEvent
from lbry.blockchain.lbrycrd import Lbrycrd

from .steps import (
    SYNC_STEPS,
    process_block_file,
    process_block_filters,
    process_metadata,
)


log = logging.getLogger(__name__)


class BlockchainSync(Sync):

    def __init__(self, chain: Lbrycrd, db: Database):
        super().__init__(chain.ledger, db)
        self.chain = chain
        self.on_block_subscription: Optional[BroadcastSubscription] = None
        self.advance_loop_task: Optional[asyncio.Task] = None
        self.advance_loop_event = asyncio.Event()

    async def start(self):
        for _ in range(1):  # range(2):
            # initial sync can take a long time, new blocks may have been
            # created while sync was running; therefore, run a second sync
            # after first one finishes to possibly sync those new blocks.
            # run advance as a task so that it can be stop()'ed if necessary.
            self.advance_loop_task = asyncio.create_task(
                self.advance(await self.db.needs_initial_sync())
            )
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
        self.db.stop_event.set()
        if self.advance_loop_task is not None:
            self.advance_loop_task.cancel()

    async def run(self, f, *args):
        return await asyncio.get_running_loop().run_in_executor(
            self.db.executor, f, *args
        )

    async def load_blocks(self, sync_steps: int, initial_sync: bool) -> Optional[Tuple[int, int]]:
        tasks = []
        starting_height, ending_height = None, await self.chain.db.get_best_height()
        tx_count = block_count = 0
        for chain_file in await self.chain.db.get_block_files():
            # block files may be read and saved out of order, need to check
            # each file individually to see if we have missing blocks
            our_best_file_height = await self.db.get_best_block_height_for_file(chain_file['file_number'])
            if our_best_file_height == chain_file['best_height']:
                # we have all blocks in this file, skipping
                continue
            if -1 < our_best_file_height < chain_file['best_height']:
                # we have some blocks, need to figure out what we're missing
                # call get_block_files again limited to this file and current_height
                chain_file = (await self.chain.db.get_block_files(
                    file_number=chain_file['file_number'], start_height=our_best_file_height+1
                ))[0]
            tx_count += chain_file['txs']
            block_count += chain_file['blocks']
            starting_height = min(
                our_best_file_height+1 if starting_height is None else starting_height, our_best_file_height+1
            )
            tasks.append(self.run(
                process_block_file, chain_file['file_number'], our_best_file_height+1, initial_sync
            ))
        if not tasks:
            return
        await self._on_progress_controller.add({
            "event": Event.START.label,
            "data": {
                "starting_height": starting_height,
                "ending_height": ending_height,
                "sync_steps": sync_steps,
                "files": len(tasks),
                "blocks": block_count,
                "txs": tx_count,
                "claims": await self.chain.db.get_claim_metadata_count(starting_height, ending_height),
                "supports": await self.chain.db.get_support_metadata_count(starting_height, ending_height),
            }
        })
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_EXCEPTION
        )
        if pending:
            self.db.stop_event.set()
            for future in pending:
                future.cancel()
            for future in done:
                future.result()
            return
        best_height_processed = max(f.result() for f in done)
        return starting_height, best_height_processed

    def count_steps(self, initial_sync: bool):
        if initial_sync:
            sync_steps = SYNC_STEPS['initial_sync']
        else:
            sync_steps = SYNC_STEPS['ongoing_sync']
        if not self.conf.spv_address_filters:
            sync_steps -= 1
        return sync_steps

    async def advance(self, initial_sync=False):
        sync_steps = self.count_steps(initial_sync)
        heights = await self.load_blocks(sync_steps, initial_sync)
        if heights:
            starting_height, ending_height = heights
            await self.run(process_metadata, starting_height, ending_height, initial_sync)
            if self.conf.spv_address_filters:
                await self.run(process_block_filters)
            await self._on_block_controller.add(BlockEvent(ending_height))
            self.db.message_queue.put((Event.COMPLETE.value, os.getpid(), sync_steps, sync_steps))

    async def advance_loop(self):
        while True:
            await self.advance_loop_event.wait()
            self.advance_loop_event.clear()
            try:
                await self.advance()
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.exception(e)
                await self.stop()
