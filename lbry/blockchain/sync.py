import os
import asyncio
import logging
from contextvars import ContextVar
from typing import Optional

from sqlalchemy import func, bindparam
from sqlalchemy.future import select

from lbry.event import BroadcastSubscription
from lbry.service.base import Sync, BlockEvent
from lbry.db import Database, queries, TXO_TYPES
from lbry.db.tables import Claim, Claimtrie, TXO, TXI, Block as BlockTable
from lbry.db.query_context import progress, context, Event
from lbry.db.utils import chunk

from .lbrycrd import Lbrycrd
from .block import Block, create_block_filter
from .bcd_data_stream import BCDataStream


log = logging.getLogger(__name__)
_chain: ContextVar[Lbrycrd] = ContextVar('chain')


def get_or_initialize_lbrycrd(ctx=None) -> Lbrycrd:
    chain = _chain.get(None)
    if chain is not None:
        return chain
    chain = Lbrycrd((ctx or context()).ledger)
    chain.db.sync_open()
    _chain.set(chain)
    return chain


def process_block_file(block_file_number, current_height):
    ctx = context()
    chain = get_or_initialize_lbrycrd(ctx)
    stop = ctx.stop_event
    loader = ctx.get_bulk_loader()

    with progress(Event.BLOCK_READ, 100) as p:
        new_blocks = chain.db.sync_get_blocks_in_file(block_file_number, current_height)
        if not new_blocks:
            return -1
        done, total, last_block_processed = 0, len(new_blocks), -1
        block_file_path = chain.get_block_file_path_from_number(block_file_number)
        p.start(total, {'block_file': block_file_number})
        with open(block_file_path, 'rb') as fp:
            stream = BCDataStream(fp=fp)
            for done, block_info in enumerate(new_blocks, start=1):
                if stop.is_set():
                    return -1
                block_height = block_info['height']
                fp.seek(block_info['data_offset'])
                block = Block.from_data_stream(stream, block_height, block_file_number)
                loader.add_block(block)
                last_block_processed = block_height
                p.step(done)

    with progress(Event.BLOCK_SAVE) as p:
        p.extra = {'block_file': block_file_number}
        loader.save()

    return last_block_processed


def process_claimtrie(heights):
    chain = get_or_initialize_lbrycrd()

    with progress(Event.TRIE_DELETE) as p:
        p.start(1)
        p.ctx.execute(Claimtrie.delete())

    with progress(Event.TRIE_UPDATE) as p, context().connection.begin():
        trie = chain.db.sync_get_claimtrie()
        p.start(len(trie))
        done = 0
        for chunk_size, chunk_rows in chunk(trie, 10000):
            p.ctx.execute(
                Claimtrie.insert(), [{
                    'normalized': r['normalized'],
                    'claim_hash': r['claim_hash'],
                    'last_take_over_height': r['last_take_over_height'],
                } for r in chunk_rows]
            )
            done += chunk_size
            p.step(done)

    with progress(Event.CLAIM_UPDATE, 250) as p, context().connection.begin():
        claims = chain.db.sync_get_claims()
        p.start(len(claims))
        done = 0
        for record in claims:
            p.ctx.execute(
                Claim.update()
                .where(Claim.c.claim_hash == record['claim_hash'])
                .values(
                    activation_height=record['activation_height'],
                    expiration_height=record['expiration_height']
                )
            )
            done += 1
            p.step(done)

    with context("effective amount update") as ctx:
        support = TXO.alias('support')
        effective_amount_update = (
            Claim.update()
            .where(Claim.c.activation_height <= heights[-1])
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
        ctx.execute(effective_amount_update)


def process_block_and_tx_filters():

    with context("effective amount update") as ctx:
        blocks = []
        all_filters = []
        all_addresses = []
        for block in queries.get_blocks_without_filters():
            addresses = {
                ctx.ledger.address_to_hash160(r['address'])
                for r in queries.get_block_tx_addresses(block_hash=block['block_hash'])
            }
            all_addresses.extend(addresses)
            block_filter = create_block_filter(addresses)
            all_filters.append(block_filter)
            blocks.append({'pk': block['block_hash'], 'block_filter': block_filter})
        # filters = [get_block_filter(f) for f in all_filters]
        ctx.execute(BlockTable.update().where(BlockTable.c.block_hash == bindparam('pk')), blocks)

#    txs = []
#    for tx in queries.get_transactions_without_filters():
#        tx_filter = create_block_filter(
#            {r['address'] for r in queries.get_block_tx_addresses(tx_hash=tx['tx_hash'])}
#        )
#        txs.append({'pk': tx['tx_hash'], 'tx_filter': tx_filter})
#    execute(TX.update().where(TX.c.tx_hash == bindparam('pk')), txs)


class BlockchainSync(Sync):

    def __init__(self, chain: Lbrycrd, db: Database):
        super().__init__(chain.ledger, db)
        self.chain = chain
        self.on_block_subscription: Optional[BroadcastSubscription] = None
        self.advance_loop_task: Optional[asyncio.Task] = None
        self.advance_loop_event = asyncio.Event()

    async def start(self):
        # initial advance as task so that it can be stop()'ed before finishing
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
        self.db.stop_event.set()
        self.advance_loop_task.cancel()

    async def run(self, f, *args):
        return await asyncio.get_running_loop().run_in_executor(
            self.db.executor, f, *args
        )

    async def load_blocks(self):
        tasks = []
        starting_height = None
        tx_count = block_count = ending_height = 0
        for file in await self.chain.db.get_block_files():
            # block files may be read and saved out of order, need to check
            # each file individually to see if we have missing blocks
            current_height = await self.db.get_best_height_for_file(file['file_number'])
            if current_height == file['max_height']:
                # we have all blocks in this file, skipping
                continue
            if -1 < current_height < file['max_height']:
                # we have some blocks, need to figure out what we're missing
                # call get_block_files again limited to this file and current_height
                file = (await self.chain.db.get_block_files(
                    file_number=file['file_number'], above_height=current_height
                ))[0]
            tx_count += file['txs']
            block_count += file['blocks']
            starting_height = min(
                current_height if starting_height is None else starting_height, current_height
            )
            ending_height = max(ending_height, file['max_height'])
            tasks.append(self.run(process_block_file, file['file_number'], current_height))
        if not tasks:
            return None
        await self._on_progress_controller.add({
            "event": "blockchain.sync.start",
            "data": {
                "starting_height": starting_height,
                "ending_height": ending_height,
                "files": len(tasks),
                "blocks": block_count,
                "txs": tx_count
            }
        })
        done, pending = await asyncio.wait(
            tasks, return_when=asyncio.FIRST_EXCEPTION
        )
        if pending:
            self.db.stop_event.set()
            for future in pending:
                future.cancel()
            return None
        best_height_processed = max(f.result() for f in done)
        # putting event in queue instead of add to progress_controller because
        # we want this message to appear after all of the queued messages from workers
        self.db.message_queue.put((
            Event.BLOCK_DONE.value, os.getpid(),
            len(done), len(tasks),
            {"best_height_processed": best_height_processed}
        ))
        return starting_height, best_height_processed

    async def advance(self):
        heights = await self.load_blocks()
        if heights and heights[0] < heights[-1]:
            await self.db.process_inputs(heights)
            await self.db.process_claims(heights)
            await self.db.process_supports(heights)
            await self.run(process_claimtrie, heights)
            if self.conf.spv_address_filters:
                await self.run(process_block_and_tx_filters, heights)
            await self._on_block_controller.add(BlockEvent(heights[1]))

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
