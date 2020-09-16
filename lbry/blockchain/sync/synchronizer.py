import os
import asyncio
import logging
from typing import Optional, Tuple, Set, List, Coroutine
from concurrent.futures import ThreadPoolExecutor

from lbry.db import Database
from lbry.db import queries as q
from lbry.db.constants import TXO_TYPES, CLAIM_TYPE_CODES
from lbry.db.query_context import Event, Progress
from lbry.event import BroadcastSubscription, EventController
from lbry.service.base import Sync, BlockEvent
from lbry.blockchain.lbrycrd import Lbrycrd
from lbry.error import LbrycrdEventSubscriptionError

from . import blocks as block_phase, claims as claim_phase, supports as support_phase
from .context import uninitialize
from .filter_builder import split_range_into_10k_batches

log = logging.getLogger(__name__)

BLOCKS_INIT_EVENT = Event.add("blockchain.sync.blocks.init", "steps")
BLOCKS_MAIN_EVENT = Event.add("blockchain.sync.blocks.main", "blocks", "txs")
FILTER_INIT_EVENT = Event.add("blockchain.sync.filters.init", "steps")
FILTER_MAIN_EVENT = Event.add("blockchain.sync.filters.main", "blocks")
CLAIMS_INIT_EVENT = Event.add("blockchain.sync.claims.init", "steps")
CLAIMS_MAIN_EVENT = Event.add("blockchain.sync.claims.main", "claims")
TRENDS_INIT_EVENT = Event.add("blockchain.sync.trends.init", "steps")
TRENDS_MAIN_EVENT = Event.add("blockchain.sync.trends.main", "blocks")
SUPPORTS_INIT_EVENT = Event.add("blockchain.sync.supports.init", "steps")
SUPPORTS_MAIN_EVENT = Event.add("blockchain.sync.supports.main", "supports")


class BlockchainSync(Sync):

    TX_FLUSH_SIZE = 25_000  # flush to db after processing this many TXs and update progress
    CLAIM_FLUSH_SIZE = 25_000  # flush to db after processing this many claims and update progress
    SUPPORT_FLUSH_SIZE = 25_000  # flush to db after processing this many supports and update progress
    FILTER_FLUSH_SIZE = 10_000  # flush to db after processing this many filters and update progress

    def __init__(self, chain: Lbrycrd, db: Database):
        super().__init__(chain.ledger, db)
        self.chain = chain
        self.pid = os.getpid()
        self.on_block_hash_subscription: Optional[BroadcastSubscription] = None
        self.on_tx_hash_subscription: Optional[BroadcastSubscription] = None
        self.advance_loop_task: Optional[asyncio.Task] = None
        self.block_hash_event = asyncio.Event()
        self.tx_hash_event = asyncio.Event()
        self._on_mempool_controller = EventController()
        self.on_mempool = self._on_mempool_controller.stream

    async def wait_for_chain_ready(self):
        while True:
            try:
                return await self.chain.ensure_subscribable()
            except asyncio.CancelledError:
                raise
            except LbrycrdEventSubscriptionError as e:
                log.warning(
                    "Lbrycrd is misconfigured. Please double check if"
                    " zmqpubhashblock is properly set on lbrycrd.conf"
                )
                raise
            except Exception as e:
                log.warning("Blockchain not ready, waiting for it: %s", str(e))
                await asyncio.sleep(1)

    async def start(self):
        self.db.stop_event.clear()
        await self.wait_for_chain_ready()
        self.advance_loop_task = asyncio.create_task(self.advance())
        await self.advance_loop_task
        await self.chain.subscribe()
        self.advance_loop_task = asyncio.create_task(self.advance_loop())
        self.on_block_hash_subscription = self.chain.on_block_hash.listen(
            lambda e: self.block_hash_event.set()
        )
        self.on_tx_hash_subscription = self.chain.on_tx_hash.listen(
            lambda e: self.tx_hash_event.set()
        )

    async def stop(self):
        self.chain.unsubscribe()
        self.db.stop_event.set()
        for subscription in (
            self.on_block_hash_subscription,
            self.on_tx_hash_subscription,
            self.advance_loop_task
        ):
            if subscription is not None:
                subscription.cancel()
        if isinstance(self.db.executor, ThreadPoolExecutor):
            await self.db.run(uninitialize)

    async def run_tasks(self, tasks: List[Coroutine]) -> Optional[Set[asyncio.Future]]:
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
        return done

    async def get_best_block_height_for_file(self, file_number) -> int:
        return await self.db.run(
            block_phase.get_best_block_height_for_file, file_number
        )

    async def sync_blocks(self) -> Optional[Tuple[int, int]]:
        tasks = []
        starting_height = None
        tx_count = block_count = 0
        with Progress(self.db.message_queue, BLOCKS_INIT_EVENT) as p:
            ending_height = await self.chain.db.get_best_height()
            for chain_file in p.iter(await self.chain.db.get_block_files()):
                # block files may be read and saved out of order, need to check
                # each file individually to see if we have missing blocks
                our_best_file_height = await self.get_best_block_height_for_file(
                    chain_file['file_number']
                )
                if our_best_file_height == chain_file['best_height']:
                    # we have all blocks in this file, skipping
                    continue
                if -1 < our_best_file_height < chain_file['best_height']:
                    # we have some blocks, need to figure out what we're missing
                    # call get_block_files again limited to this file and current_height
                    chain_file = (await self.chain.db.get_block_files(
                        file_number=chain_file['file_number'], start_height=our_best_file_height+1,
                    ))[0]
                tx_count += chain_file['txs']
                block_count += chain_file['blocks']
                file_start_height = chain_file['start_height']
                starting_height = min(
                    file_start_height if starting_height is None else starting_height,
                    file_start_height
                )
                tasks.append(self.db.run(
                    block_phase.sync_block_file, chain_file['file_number'], file_start_height,
                    chain_file['txs'], self.TX_FLUSH_SIZE
                ))
        with Progress(self.db.message_queue, BLOCKS_MAIN_EVENT) as p:
            p.start(block_count, tx_count, extra={
                "starting_height": starting_height,
                "ending_height": ending_height,
                "files": len(tasks),
                "claims": await self.chain.db.get_claim_metadata_count(starting_height, ending_height),
                "supports": await self.chain.db.get_support_metadata_count(starting_height, ending_height),
            })
            completed = await self.run_tasks(tasks)
            if completed:
                if starting_height == 0:
                    await self.db.run(block_phase.blocks_constraints_and_indexes)
                else:
                    await self.db.run(block_phase.blocks_vacuum)
                best_height_processed = max(f.result() for f in completed)
                return starting_height, best_height_processed

    async def sync_filters(self):
        if not self.conf.spv_address_filters:
            return
        with Progress(self.db.message_queue, FILTER_INIT_EVENT) as p:
            p.start(2)
            initial_sync = not await self.db.has_filters()
            p.step()
            if initial_sync:
                blocks = [0, await self.db.get_best_block_height()]
            else:
                blocks = await self.db.run(block_phase.get_block_range_without_filters)
            if blocks != (-1, -1):
                batches = split_range_into_10k_batches(*blocks)
                p.step()
            else:
                p.step()
                return
        with Progress(self.db.message_queue, FILTER_MAIN_EVENT) as p:
            p.start((blocks[1]-blocks[0])+1)
            await self.run_tasks([
                self.db.run(block_phase.sync_filters, *batch) for batch in batches
            ])
            if initial_sync:
                await self.db.run(block_phase.filters_constraints_and_indexes)
            else:
                await self.db.run(block_phase.filters_vacuum)

    async def sync_spends(self, blocks_added):
        if blocks_added:
            await self.db.run(block_phase.sync_spends, blocks_added[0] == 0)

    async def count_unspent_txos(
        self,
        txo_types: Tuple[int, ...],
        blocks: Tuple[int, int] = None,
        missing_in_supports_table: bool = False,
        missing_in_claims_table: bool = False,
        missing_or_stale_in_claims_table: bool = False,
    ) -> int:
        return await self.db.run(
            q.count_unspent_txos, txo_types, blocks,
            missing_in_supports_table,
            missing_in_claims_table,
            missing_or_stale_in_claims_table,
        )

    async def distribute_unspent_txos(
        self,
        txo_types: Tuple[int, ...],
        blocks: Tuple[int, int] = None,
        missing_in_supports_table: bool = False,
        missing_in_claims_table: bool = False,
        missing_or_stale_in_claims_table: bool = False,
    ) -> int:
        return await self.db.run(
            q.distribute_unspent_txos, txo_types, blocks,
            missing_in_supports_table,
            missing_in_claims_table,
            missing_or_stale_in_claims_table,
            self.db.workers
        )

    async def count_abandoned_supports(self) -> int:
        return await self.db.run(q.count_abandoned_supports)

    async def count_abandoned_claims(self) -> int:
        return await self.db.run(q.count_abandoned_claims)

    async def count_claims_with_changed_supports(self, blocks) -> int:
        return await self.db.run(q.count_claims_with_changed_supports, blocks)

    async def count_claims_with_changed_reposts(self, blocks) -> int:
        return await self.db.run(q.count_claims_with_changed_reposts, blocks)

    async def count_channels_with_changed_content(self, blocks) -> int:
        return await self.db.run(q.count_channels_with_changed_content, blocks)

    async def count_takeovers(self, blocks) -> int:
        return await self.chain.db.get_takeover_count(
            start_height=blocks[0], end_height=blocks[-1]
        )

    async def sync_claims(self, blocks) -> bool:
        delete_claims = takeovers = claims_with_changed_supports = claims_with_changed_reposts = 0
        initial_sync = not await self.db.has_claims()
        with Progress(self.db.message_queue, CLAIMS_INIT_EVENT) as p:
            if initial_sync:
                total, batches = await self.distribute_unspent_txos(CLAIM_TYPE_CODES)
            elif blocks:
                p.start(5)
                # 1. content claims to be inserted or updated
                total = await self.count_unspent_txos(
                    CLAIM_TYPE_CODES, blocks, missing_or_stale_in_claims_table=True
                )
                batches = [blocks] if total else []
                p.step()
                # 2. claims to be deleted
                delete_claims = await self.count_abandoned_claims()
                total += delete_claims
                p.step()
                # 3. claims to be updated with new support totals
                claims_with_changed_supports = await self.count_claims_with_changed_supports(blocks)
                total += claims_with_changed_supports
                p.step()
                # 4. claims to be updated with new repost totals
                claims_with_changed_reposts = await self.count_claims_with_changed_reposts(blocks)
                total += claims_with_changed_reposts
                p.step()
                # 5. claims to be updated due to name takeovers
                takeovers = await self.count_takeovers(blocks)
                total += takeovers
                p.step()
            else:
                return initial_sync
        with Progress(self.db.message_queue, CLAIMS_MAIN_EVENT) as p:
            p.start(total)
            if batches:
                await self.run_tasks([
                    self.db.run(claim_phase.claims_insert, batch, not initial_sync, self.CLAIM_FLUSH_SIZE)
                    for batch in batches
                ])
                if not initial_sync:
                    await self.run_tasks([
                        self.db.run(claim_phase.claims_update, batch) for batch in batches
                    ])
            if delete_claims:
                await self.db.run(claim_phase.claims_delete, delete_claims)
            if takeovers:
                await self.db.run(claim_phase.update_takeovers, blocks, takeovers)
            if claims_with_changed_supports:
                await self.db.run(claim_phase.update_stakes, blocks, claims_with_changed_supports)
            if claims_with_changed_reposts:
                await self.db.run(claim_phase.update_reposts, blocks, claims_with_changed_reposts)
            if initial_sync:
                await self.db.run(claim_phase.claims_constraints_and_indexes)
            else:
                await self.db.run(claim_phase.claims_vacuum)
            return initial_sync

    async def sync_supports(self, blocks):
        delete_supports = 0
        initial_sync = not await self.db.has_supports()
        with Progress(self.db.message_queue, SUPPORTS_INIT_EVENT) as p:
            if initial_sync:
                total, support_batches = await self.distribute_unspent_txos(TXO_TYPES['support'])
            elif blocks:
                p.start(2)
                # 1. supports to be inserted
                total = await self.count_unspent_txos(
                    TXO_TYPES['support'], blocks, missing_in_supports_table=True
                )
                support_batches = [blocks] if total else []
                p.step()
                # 2. supports to be deleted
                delete_supports = await self.count_abandoned_supports()
                total += delete_supports
                p.step()
            else:
                return
        with Progress(self.db.message_queue, SUPPORTS_MAIN_EVENT) as p:
            p.start(total)
            if support_batches:
                await self.run_tasks([
                    self.db.run(
                        support_phase.supports_insert, batch, not initial_sync, self.SUPPORT_FLUSH_SIZE
                    ) for batch in support_batches
                ])
            if delete_supports:
                await self.db.run(support_phase.supports_delete, delete_supports)
            if initial_sync:
                await self.db.run(support_phase.supports_constraints_and_indexes)
            else:
                await self.db.run(support_phase.supports_vacuum)

    async def sync_channel_stats(self, blocks, initial_sync):
        await self.db.run(claim_phase.update_channel_stats, blocks, initial_sync)

    async def sync_trends(self):
        pass

    async def advance(self):
        blocks_added = await self.sync_blocks()
        await self.sync_spends(blocks_added)
        await self.sync_filters()
        initial_claim_sync = await self.sync_claims(blocks_added)
        await self.sync_supports(blocks_added)
        await self.sync_channel_stats(blocks_added, initial_claim_sync)
        await self.sync_trends()
        if blocks_added:
            await self._on_block_controller.add(BlockEvent(blocks_added[-1]))

    async def sync_mempool(self):
        await self.db.run(block_phase.sync_mempool)
        await self.sync_spends([-1])
        await self.db.run(claim_phase.claims_insert, [-2, 0], True, self.CLAIM_FLUSH_SIZE)
        await self.db.run(claim_phase.claims_vacuum)

    async def advance_loop(self):
        while True:
            try:
                await asyncio.wait([
                    self.tx_hash_event.wait(),
                    self.block_hash_event.wait(),
                ], return_when=asyncio.FIRST_COMPLETED)
                if self.block_hash_event.is_set():
                    self.block_hash_event.clear()
                    await self.db.run(block_phase.clear_mempool)
                    await self.advance()
                self.tx_hash_event.clear()
                await self.sync_mempool()
            except asyncio.CancelledError:
                return
            except Exception as e:
                log.exception(e)
                await self.stop()

    async def rewind(self, height):
        await self.db.run(block_phase.rewind, height)
