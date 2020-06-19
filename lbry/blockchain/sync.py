import os
import asyncio
import logging
from contextvars import ContextVar
from typing import Optional, Tuple, Set, NamedTuple

from sqlalchemy import func, bindparam, case, distinct, between
from sqlalchemy.future import select

from lbry.event import BroadcastSubscription
from lbry.service.base import Sync, BlockEvent
from lbry.db import Database, queries, TXO_TYPES, CLAIM_TYPE_CODES
from lbry.db.tables import Claim, Takeover, Support, TXO, TX, TXI, Block as BlockTable
from lbry.db.query_context import progress, context, Event
from lbry.db.queries import rows_to_txos
from lbry.db.sync import (
    condition_spent_claims, condition_spent_supports,
    select_missing_claims, select_stale_claims, select_missing_supports
)
from lbry.schema.url import normalize_name

from .lbrycrd import Lbrycrd
from .block import Block, create_block_filter
from .bcd_data_stream import BCDataStream
from .transaction import Output


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


def process_block_file(block_file_number: int, starting_height: int, initial_sync: bool):
    ctx = context()
    chain = get_or_initialize_lbrycrd(ctx)
    stop = ctx.stop_event
    loader = ctx.get_bulk_loader()

    with progress(Event.BLOCK_READ, 100) as p:
        new_blocks = chain.db.sync_get_blocks_in_file(block_file_number, starting_height)
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
                loader.add_block(
                    block, initial_sync and chain.db.sync_get_claim_support_txo_hashes(block_height)
                )
                last_block_processed = block_height
                p.step(done)

    with progress(Event.BLOCK_SAVE) as p:
        p.extra = {'block_file': block_file_number}
        loader.save()

    return last_block_processed


def process_takeovers(starting_height: int, ending_height: int):
    chain = get_or_initialize_lbrycrd()
    with progress(Event.TAKEOVER_INSERT) as p:
        p.start(chain.db.sync_get_takeover_count(
            above_height=starting_height, limit_height=ending_height
        ))
        done, step_size = 0, 500
        for offset in range(starting_height, ending_height+1, step_size):
            takeovers = chain.db.sync_get_takeovers(
                above_height=offset, limit_height=min(offset+step_size, ending_height),
            )
            if takeovers:
                p.ctx.execute(Takeover.insert(), takeovers)
                done += len(takeovers)
                p.step(done)


def signature_validation(d: dict, row: dict, public_key) -> dict:
    d['is_signature_valid'] = False
    if Output.is_signature_valid(bytes(row['signature']), bytes(row['signature_digest']), public_key):
        d['is_signature_valid'] = True
    return d


def select_updated_channel_keys(starting_height, ending_height, *cols):
    return (
        select(*cols).select_from(Claim)
        .where(
            (Claim.c.claim_type == TXO_TYPES['channel']) &
            between(Claim.c.public_key_height, starting_height, ending_height)
        )
    )


def get_updated_channel_key_count(ctx, starting_height, ending_height):
    sql = select_updated_channel_keys(
        starting_height, ending_height, func.count('*').label('total')
    )
    return ctx.fetchone(sql)['total']


def get_updated_channel_keys(ctx, starting_height, ending_height):
    sql = select_updated_channel_keys(
        starting_height, ending_height,
        Claim.c.claim_hash, Claim.c.public_key, Claim.c.height
    )
    return ctx.fetchall(sql)


def get_signables_for_channel(ctx, table, pk, channel):
    sql = (
        select(pk, table.c.signature, table.c.signature_digest)
        .where(table.c.channel_hash == channel['claim_hash'])
    )
    return ctx.fetchall(sql)


def select_unvalidated_signables(signable, starting_height: int, ending_height: int, *cols):
    channel = Claim.alias('channel')
    if len(cols) > 1:
        cols += (channel.c.public_key,)
    return (
        select(*cols)
        .select_from(signable.join(channel, signable.c.channel_hash == channel.c.claim_hash))
        .where(
            (signable.c.signature != None) &
            (signable.c.is_signature_valid == False) &
            between(signable.c.height, starting_height, ending_height)
        )
    )


def get_unvalidated_signable_count(ctx, signable, starting_height: int, ending_height: int):
    sql = select_unvalidated_signables(
        signable, starting_height, ending_height, func.count('*').label('total')
    )
    return ctx.fetchone(sql)['total']


def get_unvalidated_signables(ctx, signable, starting_height: int, ending_height: int, pk):
    sql = select_unvalidated_signables(
        signable, starting_height, ending_height,
        pk, signable.c.signature, signable.c.signature_digest
    )
    return ctx.fetchall(sql)


class ClaimChanges(NamedTuple):
    deleted_channels: Set[bytes]
    channels_with_changed_claims: Set[bytes]
    claims_with_changed_supports: Set[bytes]


def process_claims_and_supports():
    with progress(Event.CLAIM_DELETE) as p:
        channels_with_deleted_claims = {
            r['channel_hash'] for r in p.ctx.fetchall(
                select(distinct(Claim.c.channel_hash))
                .where(condition_spent_claims(
                    list(set(CLAIM_TYPE_CODES) - {TXO_TYPES['channel']})
                ) & (Claim.c.channel_hash != None))
            )
        }
        deleted_channels = {
            r['claim_hash'] for r in p.ctx.fetchall(
                select(distinct(Claim.c.claim_hash)).where(
                    (Claim.c.claim_type == TXO_TYPES['channel']) &
                    condition_spent_claims([TXO_TYPES['channel']])
                )
            )
        }
        p.start(1)
        p.ctx.execute(Claim.delete().where(condition_spent_claims()))

    with progress(Event.CLAIM_INSERT) as p:
        channels_with_added_claims = set()
        loader = p.ctx.get_bulk_loader()
        for txo in rows_to_txos(p.ctx.fetchall(select_missing_claims)):
            loader.add_claim(txo)
            if txo.can_decode_claim and txo.claim.is_signed:
                channels_with_added_claims.add(txo.claim.signing_channel_hash)
        loader.save()

    with progress(Event.CLAIM_UPDATE) as p:
        loader = p.ctx.get_bulk_loader()
        for claim in rows_to_txos(p.ctx.fetchall(select_stale_claims)):
            loader.update_claim(claim)
        loader.save()

    with progress(Event.SUPPORT_DELETE) as p:
        claims_with_deleted_supports = {
            r['claim_hash'] for r in p.ctx.fetchall(
                select(distinct(Support.c.claim_hash)).where(condition_spent_supports)
            )
        }
        p.start(1)
        sql = Support.delete().where(condition_spent_supports)
        p.ctx.execute(sql)

    with progress(Event.SUPPORT_INSERT) as p:
        claims_with_added_supports = {
            r['claim_hash'] for r in p.ctx.fetchall(
                select(distinct(Support.c.claim_hash)).where(condition_spent_supports)
            )
        }
        loader = p.ctx.get_bulk_loader()
        for support in rows_to_txos(p.ctx.fetchall(select_missing_supports)):
            loader.add_support(support)
        loader.save()

    return ClaimChanges(
        deleted_channels=deleted_channels,
        channels_with_changed_claims=(
            channels_with_added_claims | channels_with_deleted_claims
        ),
        claims_with_changed_supports=(
            claims_with_added_supports | claims_with_deleted_supports
        )
    )


def process_metadata(starting_height: int, ending_height: int, initial_sync: bool):
    # TODO:
    # - claim updates to point to a different channel
    # - deleting a channel should invalidate contained claim signatures
    chain = get_or_initialize_lbrycrd()
    channel = Claim.alias('channel')
    changes = process_claims_and_supports() if not initial_sync else None

    support_amount_calculator = (
        select(func.coalesce(func.sum(Support.c.amount), 0) + Claim.c.amount)
        .select_from(Support)
        .where(Support.c.claim_hash == Claim.c.claim_hash)
        .scalar_subquery()
    )

    supports_in_claim_calculator = (
        select(func.count('*'))
        .select_from(Support)
        .where(Support.c.claim_hash == Claim.c.claim_hash)
        .scalar_subquery()
    )

    stream = Claim.alias('stream')
    claims_in_channel_calculator = (
        select(func.count('*'))
        .select_from(stream)
        .where(stream.c.channel_hash == Claim.c.claim_hash)
        .scalar_subquery()
    )

    with progress(Event.CLAIM_META) as p:
        p.start(chain.db.sync_get_claim_metadata_count(start_height=starting_height, end_height=ending_height))
        claim_update_sql = (
            Claim.update().where(Claim.c.claim_hash == bindparam('claim_hash_'))
            .values(
                canonical_url=case([(
                    ((Claim.c.canonical_url == None) & (Claim.c.channel_hash != None)),
                    select(channel.c.short_url).select_from(channel)
                    .where(channel.c.claim_hash == Claim.c.channel_hash)
                    .scalar_subquery() + '/' + bindparam('short_url_')
                )], else_=Claim.c.canonical_url),
                support_amount=support_amount_calculator,
                supports_in_claim_count=supports_in_claim_calculator,
                claims_in_channel_count=case([(
                    (Claim.c.claim_type == TXO_TYPES['channel']), claims_in_channel_calculator
                )], else_=0),
            )
        )
        done, step_size = 0, 500
        for offset in range(starting_height, ending_height+1, step_size):
            claims = chain.db.sync_get_claim_metadata(
                start_height=offset, end_height=min(offset+step_size, ending_height)
            )
            if claims:
                p.ctx.execute(claim_update_sql, claims)
                done += len(claims)
                p.step(done)

    if not initial_sync and changes.claims_with_changed_supports:
        # covered by Event.CLAIM_META during initial_sync, then only run if supports change
        with progress(Event.CLAIM_CALC) as p:
            p.start(len(changes.claims_with_changed_supports))
            sql = (
                Claim.update()
                .where((Claim.c.claim_hash.in_(changes.claims_with_changed_supports)))
                .values(
                    support_amount=support_amount_calculator,
                    supports_in_claim_count=supports_in_claim_calculator,
                )
            )
            p.ctx.execute(sql)

    if not initial_sync and changes.channels_with_changed_claims:
        # covered by Event.CLAIM_META during initial_sync, then only run if claims are deleted
        with progress(Event.CLAIM_CALC) as p:
            p.start(len(changes.channels_with_changed_claims))
            sql = (
                Claim.update()
                .where((Claim.c.claim_hash.in_(changes.channels_with_changed_claims)))
                .values(claims_in_channel_count=claims_in_channel_calculator)
            )
            p.ctx.execute(sql)

    if not initial_sync:
        # covered by Event.CLAIM_META during initial_sync, otherwise loop over every block
        with progress(Event.CLAIM_TRIE, 100) as p:
            p.start(chain.db.sync_get_takeover_count(start_height=starting_height, end_height=ending_height))
            for offset in range(starting_height, ending_height+1):
                for takeover in chain.db.sync_get_takeovers(start_height=offset, end_height=offset):
                    update_claims = (
                        Claim.update()
                        .where(Claim.c.normalized == normalize_name(takeover['name'].decode()))
                        .values(
                            is_controlling=case(
                                [(Claim.c.claim_hash == takeover['claim_hash'], True)],
                                else_=False
                            ),
                            takeover_height=case(
                                [(Claim.c.claim_hash == takeover['claim_hash'], takeover['height'])],
                                else_=None
                            ),
                            activation_height=func.min(Claim.c.activation_height, takeover['height']),
                        )
                    )
                    p.ctx.execute(update_claims)
                    p.step(1)

#    with progress(Event.SUPPORT_META) as p:
#        p.start(chain.db.sync_get_support_metadata_count(start_height=starting_height, end_height=ending_height))
#        done, step_size = 0, 500
#        for offset in range(starting_height, ending_height+1, step_size):
#            supports = chain.db.sync_get_support_metadata(
#                start_height=offset, end_height=min(offset+step_size, ending_height)
#            )
#            if supports:
#                p.ctx.execute(
#                    Support.update().where(Support.c.txo_hash == bindparam('txo_hash_pk')),
#                    supports
#                )
#                done += len(supports)
#                p.step(done)

    with progress(Event.CHANNEL_SIGN) as p:
        p.start(get_updated_channel_key_count(p.ctx, starting_height, ending_height))
        done, step_size = 0, 500
        for offset in range(starting_height, ending_height+1, step_size):
            channels = get_updated_channel_keys(p.ctx, offset, min(offset+step_size, ending_height))
            for channel in channels:

                claim_updates = []
                for claim in get_signables_for_channel(p.ctx, Claim, Claim.c.claim_hash, channel):
                    claim_updates.append(
                        signature_validation({'pk': claim['claim_hash']}, claim, channel['public_key'])
                    )
                if claim_updates:
                    p.ctx.execute(
                        Claim.update().where(Claim.c.claim_hash == bindparam('pk')), claim_updates
                    )

                support_updates = []
                for support in get_signables_for_channel(p.ctx, Support, Support.c.txo_hash, channel):
                    support_updates.append(
                        signature_validation({'pk': support['txo_hash']}, support, channel['public_key'])
                    )
                if support_updates:
                    p.ctx.execute(
                        Support.update().where(Support.c.txo_hash == bindparam('pk')), support_updates
                    )

                p.step(len(channels))

    with progress(Event.CLAIM_SIGN) as p:
        p.start(get_unvalidated_signable_count(p.ctx, Claim, starting_height, ending_height))
        done, step_size = 0, 500
        for offset in range(starting_height, ending_height+1, step_size):
            claims = get_unvalidated_signables(
                p.ctx, Claim, offset, min(offset+step_size, ending_height), Claim.c.claim_hash)
            claim_updates = []
            for claim in claims:
                claim_updates.append(
                    signature_validation({'pk': claim['claim_hash']}, claim, claim['public_key'])
                )
            if claim_updates:
                p.ctx.execute(
                    Claim.update().where(Claim.c.claim_hash == bindparam('pk')), claim_updates
                )
            p.step(done)

    with progress(Event.SUPPORT_SIGN) as p:
        p.start(get_unvalidated_signable_count(p.ctx, Support, starting_height, ending_height))
        done, step_size = 0, 500
        for offset in range(starting_height, ending_height+1, step_size):
            supports = get_unvalidated_signables(
                p.ctx, Support, offset, min(offset+step_size, ending_height), Support.c.txo_hash)
            support_updates = []
            for support in supports:
                support_updates.append(
                    signature_validation({'pk': support['txo_hash']}, support, support['public_key'])
                )
            if support_updates:
                p.ctx.execute(
                    Support.update().where(Support.c.txo_hash == bindparam('pk')), support_updates
                )
            p.step(done)


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
        for _ in range(2):
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
        self.advance_loop_task.cancel()

    async def run(self, f, *args):
        return await asyncio.get_running_loop().run_in_executor(
            self.db.executor, f, *args
        )

    async def load_blocks(self, initial_sync: bool) -> Optional[Tuple[int, int]]:
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
                file = (await self.chain.db.get_block_files(
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
            return
        best_height_processed = max(f.result() for f in done)
        # putting event in queue instead of add to progress_controller because
        # we want this message to appear after all of the queued messages from workers
        self.db.message_queue.put((
            Event.BLOCK_DONE.value, os.getpid(),
            len(done), len(tasks),
            {"best_height_processed": best_height_processed}
        ))
        return starting_height, best_height_processed

    async def process(self, starting_height: int, ending_height: int, initial_sync: bool):
        await self.db.process_inputs_outputs()
        await self.run(process_metadata, starting_height, ending_height, initial_sync)
        if self.conf.spv_address_filters:
            await self.run(process_block_and_tx_filters)

    async def advance(self, initial_sync=False):
        heights = await self.load_blocks(initial_sync)
        if heights:
            starting_height, ending_height = heights
            await self.process(starting_height, ending_height, initial_sync)
            await self._on_block_controller.add(BlockEvent(ending_height))

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
