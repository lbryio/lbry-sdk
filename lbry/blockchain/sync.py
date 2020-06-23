# pylint: disable=singleton-comparison
import os
import asyncio
import logging
from contextvars import ContextVar
from typing import Optional, Tuple, Set, NamedTuple

from sqlalchemy import func, bindparam, case, distinct, desc
from sqlalchemy.future import select

from lbry.event import BroadcastSubscription
from lbry.service.base import Sync, BlockEvent
from lbry.db import Database, queries, TXO_TYPES, CLAIM_TYPE_CODES
from lbry.db.tables import Claim, Takeover, Support, TXO, Block as BlockTable
from lbry.db.query_context import progress, context, Event
from lbry.db.queries import rows_to_txos
from lbry.db.sync import (
    condition_spent_claims, condition_spent_supports,
    select_missing_supports, process_claim_changes
)
from lbry.db.utils import least
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


class ClaimChanges(NamedTuple):
    deleted_channels: Set[bytes]
    channels_with_changed_content: Set[bytes]
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

    process_claim_changes()

    with progress(Event.SUPPORT_DELETE) as p:
        claims_with_deleted_supports = {
            r['claim_hash'] for r in p.ctx.fetchall(
                select(distinct(Support.c.claim_hash)).where(condition_spent_supports)
            )
        }
        channels_with_deleted_supports = {
            r['channel_hash'] for r in p.ctx.fetchall(
                select(distinct(Support.c.channel_hash))
                .where(condition_spent_supports & (Support.c.channel_hash != None))
            )
        }
        p.start(1)
        sql = Support.delete().where(condition_spent_supports)
        p.ctx.execute(sql)

    with progress(Event.SUPPORT_INSERT) as p:
        claims_with_added_supports = set()
        loader = p.ctx.get_bulk_loader()
        for txo in rows_to_txos(p.ctx.fetchall(select_missing_supports)):
            loader.add_support(txo)
            claims_with_added_supports.add(txo.claim_hash)
        loader.save()

    return ClaimChanges(
        deleted_channels=deleted_channels,
        channels_with_changed_content=(
            channels_with_deleted_supports | channels_with_deleted_claims
        ),
        claims_with_changed_supports=(
            claims_with_added_supports | claims_with_deleted_supports
        )
    )


def condition_unvalidated_signables(signable):
    return (
        (signable.c.is_signature_valid == None) &
        (signable.c.channel_hash != None)
    )


def get_unvalidated_signable_count(ctx, signable):
    sql = (
        select(func.count('*').label('total'))
        .select_from(signable)
        .where(condition_unvalidated_signables(signable))
    )
    return ctx.fetchone(sql)['total']


def select_unvalidated_signables(signable, pk, include_urls=False, include_previous=False):
    sql = (
        select(
            pk, signable.c.signature, signable.c.signature_digest, signable.c.channel_hash, (
                select(TXO.c.public_key).select_from(TXO)
                .where(
                    (TXO.c.claim_hash == signable.c.channel_hash) &
                    (TXO.c.txo_type == TXO_TYPES['channel']) &
                    (TXO.c.height <= signable.c.height)
                )
                .order_by(desc(TXO.c.height))
                .scalar_subquery().label('public_key')
            ),
        )
        .where(condition_unvalidated_signables(signable))
    )
    if include_previous:
        assert signable.name != 'support', "Supports cannot be updated and don't have a previous."
        sql = sql.add_columns(
            select(TXO.c.channel_hash).select_from(TXO)
            .where(
                (TXO.c.claim_hash == signable.c.claim_hash) &
                (TXO.c.txo_type.in_(CLAIM_TYPE_CODES)) &
                (TXO.c.height <= signable.c.height)
            )
            .order_by(desc(TXO.c.height)).offset(1)
            .scalar_subquery().label('previous_channel_hash')
        )
    if include_urls:
        channel = Claim.alias('channel')
        return sql.add_columns(
            signable.c.short_url.label('claim_url'),
            channel.c.short_url.label('channel_url')
        ).select_from(signable.join(channel, signable.c.channel_hash == channel.c.claim_hash))
    return sql.select_from(signable)


def signature_validation(d: dict, row: dict, public_key) -> dict:
    d['is_signature_valid'] = False
    if Output.is_signature_valid(bytes(row['signature']), bytes(row['signature_digest']), public_key):
        d['is_signature_valid'] = True
    return d


def process_signature_validation(changes: ClaimChanges):

    with progress(Event.CLAIM_SIGN) as p:
        p.start(get_unvalidated_signable_count(p.ctx, Claim))
        claim_updates = []
        sql = select_unvalidated_signables(
            Claim, Claim.c.claim_hash, include_urls=True, include_previous=changes is not None
        )
        for claim in p.ctx.execute(sql):
            claim_updates.append(
                signature_validation({
                    'pk': claim['claim_hash'],
                    'canonical_url': claim['channel_url'] + '/' + claim['claim_url']
                }, claim, claim['public_key'])
            )
            if changes is not None:
                changes.channels_with_changed_content.add(claim['channel_hash'])
                if claim['previous_channel_hash']:
                    changes.channels_with_changed_content.add(claim['previous_channel_hash'])
            if len(claim_updates) > 500:
                p.ctx.execute(Claim.update().where(Claim.c.claim_hash == bindparam('pk')), claim_updates)
                p.step(len(claim_updates))
                claim_updates.clear()
        if claim_updates:
            p.ctx.execute(Claim.update().where(Claim.c.claim_hash == bindparam('pk')), claim_updates)
        del claim_updates

    with progress(Event.SUPPORT_SIGN) as p:
        p.start(get_unvalidated_signable_count(p.ctx, Support))
        support_updates = []
        for support in p.ctx.execute(select_unvalidated_signables(Support, Support.c.txo_hash)):
            support_updates.append(
                signature_validation({'pk': support['txo_hash']}, support, support['public_key'])
            )
            if changes is not None:
                changes.channels_with_changed_content.add(support['channel_hash'])
            if len(support_updates) > 500:
                p.ctx.execute(Support.update().where(Support.c.txo_hash == bindparam('pk')), support_updates)
                p.step(len(support_updates))
                support_updates.clear()
        if support_updates:
            p.ctx.execute(Support.update().where(Support.c.txo_hash == bindparam('pk')), support_updates)
        del support_updates


def channel_content_count_calc(signable):
    return (
        select(func.count('*'))
        .select_from(signable)
        .where((signable.c.channel_hash == Claim.c.claim_hash) & signable.c.is_signature_valid)
        .scalar_subquery()
    )


def claim_support_aggregation(*cols):
    return (
        select(*cols)
        .select_from(Support)
        .where(Support.c.claim_hash == Claim.c.claim_hash)
        .scalar_subquery()
    )


def process_metadata(starting_height: int, ending_height: int, initial_sync: bool):
    chain = get_or_initialize_lbrycrd()
    channel = Claim.alias('channel')
    stream = Claim.alias('stream')
    changes = process_claims_and_supports() if not initial_sync else None

    staked_support_amount_calc = claim_support_aggregation(func.coalesce(func.sum(Support.c.amount), 0))
    staked_support_count_calc = claim_support_aggregation(func.count('*'))

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
                staked_support_amount=staked_support_amount_calc,
                staked_support_count=staked_support_count_calc,
                signed_claim_count=case([(
                    (Claim.c.claim_type == TXO_TYPES['channel']),
                    channel_content_count_calc(stream)
                )], else_=0),
                signed_support_count=case([(
                    (Claim.c.claim_type == TXO_TYPES['channel']),
                    channel_content_count_calc(Support)
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

    process_signature_validation(changes)

    if not initial_sync and changes.claims_with_changed_supports:
        # covered by Event.CLAIM_META during initial_sync, then only run if supports change
        with progress(Event.CLAIM_CALC) as p:
            p.start(len(changes.claims_with_changed_supports))
            sql = (
                Claim.update()
                .where((Claim.c.claim_hash.in_(changes.claims_with_changed_supports)))
                .values(
                    staked_support_amount=staked_support_amount_calc,
                    staked_support_count=staked_support_count_calc,
                )
            )
            p.ctx.execute(sql)

    if not initial_sync and changes.channels_with_changed_content:
        # covered by Event.CLAIM_META during initial_sync, then only run if claims are deleted
        with progress(Event.CLAIM_CALC) as p:
            p.start(len(changes.channels_with_changed_content))
            sql = (
                Claim.update()
                .where((Claim.c.claim_hash.in_(changes.channels_with_changed_content)))
                .values(
                    signed_claim_count=channel_content_count_calc(stream),
                    signed_support_count=channel_content_count_calc(Support),
                )
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
                            activation_height=least(Claim.c.activation_height, takeover['height']),
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
        if self.advance_loop_task is not None:
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
            for future in done:
                future.result()
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
