# pylint: disable=singleton-comparison
import logging
import functools
from contextvars import ContextVar
from typing import Set

from sqlalchemy import bindparam, case, distinct, text
from sqlalchemy.schema import CreateTable

from lbry.db import queries
from lbry.db.tables import Block as BlockTable, TXO, TXI
from lbry.db.query_context import progress, context, Event
from lbry.db.queries import rows_to_txos
from lbry.db.sync import (
    select_missing_supports,
    select_missing_claims, select_stale_claims,
    condition_spent_claims, condition_spent_supports,
    set_input_addresses, update_spent_outputs
)
from lbry.db.utils import least
from lbry.schema.url import normalize_name

from lbry.blockchain.lbrycrd import Lbrycrd
from lbry.blockchain.block import Block, create_block_filter
from lbry.blockchain.bcd_data_stream import BCDataStream
from lbry.blockchain.transaction import Output

from .queries import (
    select, Claim, Support,
    TXO_TYPES, CLAIM_TYPE_CODES,
    channel_content_count_calc,
    staked_support_amount_calc, staked_support_count_calc,
    select_unvalidated_signables, get_unvalidated_signable_count
)


log = logging.getLogger(__name__)
_chain: ContextVar[Lbrycrd] = ContextVar('chain')


SYNC_STEPS = {
    "initial_sync": [],
    "ongoing_sync": [],
    "events": [],
}


def sync_step(event: Event, step_size=1, initial_sync=False, ongoing_sync=False):
    assert event.label not in SYNC_STEPS['events'], f"Event {event.label} used more than once."
    assert initial_sync or ongoing_sync, "At least one of initial_sync or ongoing_sync must be true."
    SYNC_STEPS['events'].append(event.label)
    if initial_sync:
        SYNC_STEPS['initial_sync'].append(event.label)
    if ongoing_sync:
        SYNC_STEPS['ongoing_sync'].append(event.label)

    def wrapper(f):
        @functools.wraps(f)
        def with_progress(*args, **kwargs):
            with progress(event, step_size=step_size) as p:
                return f(*args, **kwargs, p=p)
        return with_progress

    return wrapper


class ClaimChanges:
    deleted_channels: Set[bytes]
    channels_with_changed_content: Set[bytes]
    claims_with_changed_supports: Set[bytes]

    def __init__(self):
        self.deleted_channels = set()
        self.channels_with_changed_content = set()
        self.claims_with_changed_supports = set()


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
    loader = ctx.get_bulk_loader()
    last_block_processed = process_block_read(block_file_number, starting_height, initial_sync, loader)
    process_block_save(block_file_number, loader)
    return last_block_processed


def process_metadata(starting_height: int, ending_height: int, initial_sync: bool):
    chain = get_or_initialize_lbrycrd()
    process_inputs_outputs(initial_sync)
    changes = None
    if not initial_sync:
        changes = ClaimChanges()
        process_claim_delete(changes)
        process_claim_insert(changes)
        process_claim_update(changes)
        process_support_delete(changes)
        process_support_insert(changes)
        process_takeovers(starting_height, ending_height, chain)
    process_claim_metadata(starting_height, ending_height, chain)
    process_claim_signatures(changes)
    process_support_signatures(changes)
    if not initial_sync:
        # these depend on signature validation
        process_stake_calc(changes)
        process_channel_content(changes)


@sync_step(Event.BLOCK_READ, step_size=100, initial_sync=True, ongoing_sync=True)
def process_block_read(block_file_number: int, starting_height: int, initial_sync: bool, loader, p=None):
    chain = get_or_initialize_lbrycrd(p.ctx)
    stop = p.ctx.stop_event
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
    return last_block_processed


@sync_step(Event.BLOCK_SAVE, initial_sync=True, ongoing_sync=True)
def process_block_save(block_file_number: int, loader, p=None):
    p.extra = {'block_file': block_file_number}
    loader.save()


@sync_step(Event.INPUT_UPDATE, initial_sync=True, ongoing_sync=True)
def process_inputs_outputs(initial_sync=False, p=None):

    step = 0

    def next_step():
        nonlocal step
        step += 1
        return step

    if initial_sync:
        p.start(9)
    else:
        p.start(2)

    if initial_sync:
        # A. add tx constraints
        if p.ctx.is_postgres:
            p.ctx.execute(text("ALTER TABLE tx ADD PRIMARY KEY (tx_hash);"))
        p.step(next_step())

    # 1. Update TXIs to have the address of TXO they are spending.
    if initial_sync:
        # B. txi table reshuffling
        p.ctx.execute(text("ALTER TABLE txi RENAME TO old_txi;"))
        p.ctx.execute(CreateTable(TXI, include_foreign_key_constraints=[]))
        if p.ctx.is_postgres:
            p.ctx.execute(text("ALTER TABLE txi DROP CONSTRAINT txi_pkey;"))
        p.step(next_step())
        # C. insert
        old_txi = TXI.alias('old_txi')
        columns = [c for c in old_txi.columns if c.name != 'address'] + [TXO.c.address]
        select_txis = select(*columns).select_from(old_txi.join(TXO))
        insert_txis = TXI.insert().from_select(columns, select_txis)
        p.ctx.execute(text(
            str(insert_txis.compile(p.ctx.engine)).replace('txi AS old_txi', 'old_txi')
        ))
        p.step(next_step())
        # D. drop old txi
        p.ctx.execute(text("DROP TABLE old_txi;"))
        p.step(next_step())
        # E. restore integrity constraint
        if p.ctx.is_postgres:
            p.ctx.execute(text("ALTER TABLE txi ADD PRIMARY KEY (txo_hash);"))
        p.step(next_step())
    else:
        set_input_addresses(p.ctx)
        p.step(next_step())

    # 2. Update spent TXOs setting is_spent = True
    if initial_sync:
        # F. txo table reshuffling
        p.ctx.execute(text("ALTER TABLE txo RENAME TO old_txo;"))
        p.ctx.execute(CreateTable(TXO, include_foreign_key_constraints=[]))
        if p.ctx.is_postgres:
            p.ctx.execute(text("ALTER TABLE txo DROP CONSTRAINT txo_pkey;"))
        p.step(next_step())
        # G. insert
        old_txo = TXO.alias('old_txo')
        columns = (
            [c for c in old_txo.columns if c.name != 'is_spent'] +
            [(TXI.c.txo_hash != None).label('is_spent')]
        )
        select_txos = select(*columns).select_from(old_txo.join(TXI, isouter=True))
        insert_txos = TXO.insert().from_select(columns, select_txos)
        p.ctx.execute(text(
            str(insert_txos.compile(p.ctx.engine)).replace('txo AS old_txo', 'old_txo')
        ))
        p.step(next_step())
        # H. drop old txo
        p.ctx.execute(text("DROP TABLE old_txo;"))
        p.step(next_step())
        # I. restore integrity constraint
        if p.ctx.is_postgres:
            p.ctx.execute(text("ALTER TABLE txo ADD PRIMARY KEY (txo_hash);"))
        p.step(next_step())
    else:
        update_spent_outputs(p.ctx)
        p.step(next_step())


@sync_step(Event.BLOCK_FILTER, initial_sync=True, ongoing_sync=True)
def process_block_filters(p=None):
    blocks = []
    all_filters = []
    all_addresses = []
    for block in queries.get_blocks_without_filters():
        addresses = {
            p.ctx.ledger.address_to_hash160(r['address'])
            for r in queries.get_block_tx_addresses(block_hash=block['block_hash'])
        }
        all_addresses.extend(addresses)
        block_filter = create_block_filter(addresses)
        all_filters.append(block_filter)
        blocks.append({'pk': block['block_hash'], 'block_filter': block_filter})
    # filters = [get_block_filter(f) for f in all_filters]
    p.ctx.execute(BlockTable.update().where(BlockTable.c.block_hash == bindparam('pk')), blocks)

#    txs = []
#    for tx in queries.get_transactions_without_filters():
#        tx_filter = create_block_filter(
#            {r['address'] for r in queries.get_block_tx_addresses(tx_hash=tx['tx_hash'])}
#        )
#        txs.append({'pk': tx['tx_hash'], 'tx_filter': tx_filter})
#    execute(TX.update().where(TX.c.tx_hash == bindparam('pk')), txs)


@sync_step(Event.CLAIM_DELETE, ongoing_sync=True)
def process_claim_delete(changes: ClaimChanges, p=None):
    changes.channels_with_changed_content |= {
        r['channel_hash'] for r in p.ctx.fetchall(
            select(distinct(Claim.c.channel_hash))
            .where(condition_spent_claims(
                list(set(CLAIM_TYPE_CODES) - {TXO_TYPES['channel']})
            ) & (Claim.c.channel_hash != None))
        )
    }
    changes.deleted_channels |= {
        r['claim_hash'] for r in p.ctx.fetchall(
            select(distinct(Claim.c.claim_hash)).where(
                (Claim.c.claim_type == TXO_TYPES['channel']) &
                condition_spent_claims([TXO_TYPES['channel']])
            )
        )
    }
    p.start(1)
    p.ctx.execute(Claim.delete().where(condition_spent_claims()))


@sync_step(Event.CLAIM_INSERT, ongoing_sync=True)
def process_claim_insert(_, p=None):
    loader = p.ctx.get_bulk_loader()
    for claim in rows_to_txos(p.ctx.fetchall(select_missing_claims)):
        loader.add_claim(claim)
    loader.save()


@sync_step(Event.CLAIM_UPDATE, ongoing_sync=True)
def process_claim_update(_, p=None):
    loader = p.ctx.get_bulk_loader()
    for claim in rows_to_txos(p.ctx.fetchall(select_stale_claims)):
        loader.update_claim(claim)
    loader.save()


@sync_step(Event.SUPPORT_DELETE, ongoing_sync=True)
def process_support_delete(changes: ClaimChanges, p=None):
    changes.claims_with_changed_supports |= {
        r['claim_hash'] for r in p.ctx.fetchall(
            select(distinct(Support.c.claim_hash)).where(condition_spent_supports)
        )
    }
    changes.channels_with_changed_content |= {
        r['channel_hash'] for r in p.ctx.fetchall(
            select(distinct(Support.c.channel_hash))
            .where(condition_spent_supports & (Support.c.channel_hash != None))
        )
    }
    p.start(1)
    sql = Support.delete().where(condition_spent_supports)
    p.ctx.execute(sql)


@sync_step(Event.SUPPORT_INSERT, ongoing_sync=True)
def process_support_insert(changes: ClaimChanges, p=None):
    loader = p.ctx.get_bulk_loader()
    for txo in rows_to_txos(p.ctx.fetchall(select_missing_supports)):
        loader.add_support(txo)
        changes.claims_with_changed_supports.add(txo.claim_hash)
    loader.save()


@sync_step(Event.CLAIM_TRIE, step_size=100, ongoing_sync=True)
def process_takeovers(starting_height: int, ending_height: int, chain, p=None):
    p.start(chain.db.sync_get_takeover_count(start_height=starting_height, end_height=ending_height))
    for offset in range(starting_height, ending_height + 1):
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


@sync_step(Event.CLAIM_META, initial_sync=True, ongoing_sync=True)
def process_claim_metadata(starting_height: int, ending_height: int, chain, p=None):
    channel = Claim.alias('channel')
    stream = Claim.alias('stream')
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
    for offset in range(starting_height, ending_height + 1, step_size):
        claims = chain.db.sync_get_claim_metadata(
            start_height=offset, end_height=min(offset + step_size, ending_height)
        )
        if claims:
            p.ctx.execute(claim_update_sql, claims)
            done += len(claims)
            p.step(done)


def signature_validation(d: dict, row: dict, public_key) -> dict:
    d['is_signature_valid'] = False
    if Output.is_signature_valid(bytes(row['signature']), bytes(row['signature_digest']), public_key):
        d['is_signature_valid'] = True
    return d


@sync_step(Event.CLAIM_SIGN, initial_sync=True, ongoing_sync=True)
def process_claim_signatures(changes: ClaimChanges, p=None):
    p.start(get_unvalidated_signable_count(p.ctx, Claim))
    claim_updates = []
    sql = select_unvalidated_signables(
        Claim, Claim.c.claim_hash, include_urls=True, include_previous=changes is not None
    )
    steps = 0
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
        if len(claim_updates) > 1000:
            p.ctx.execute(Claim.update().where(Claim.c.claim_hash == bindparam('pk')), claim_updates)
            steps += len(claim_updates)
            p.step(steps)
            claim_updates.clear()
    if claim_updates:
        p.ctx.execute(Claim.update().where(Claim.c.claim_hash == bindparam('pk')), claim_updates)


@sync_step(Event.SUPPORT_SIGN, initial_sync=True, ongoing_sync=True)
def process_support_signatures(changes: ClaimChanges, p=None):
    p.start(get_unvalidated_signable_count(p.ctx, Support))
    support_updates = []
    for support in p.ctx.execute(select_unvalidated_signables(Support, Support.c.txo_hash)):
        support_updates.append(
            signature_validation({'pk': support['txo_hash']}, support, support['public_key'])
        )
        if changes is not None:
            changes.channels_with_changed_content.add(support['channel_hash'])
        if len(support_updates) > 1000:
            p.ctx.execute(Support.update().where(Support.c.txo_hash == bindparam('pk')), support_updates)
            p.step(len(support_updates))
            support_updates.clear()
    if support_updates:
        p.ctx.execute(Support.update().where(Support.c.txo_hash == bindparam('pk')), support_updates)


@sync_step(Event.STAKE_CALC, ongoing_sync=True)
def process_stake_calc(changes: ClaimChanges, p=None):
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


@sync_step(Event.CLAIM_CHAN, ongoing_sync=True)
def process_channel_content(changes: ClaimChanges, p=None):
    p.start(len(changes.channels_with_changed_content))
    stream = Claim.alias('stream')
    sql = (
        Claim.update()
        .where((Claim.c.claim_hash.in_(changes.channels_with_changed_content)))
        .values(
            signed_claim_count=channel_content_count_calc(stream),
            signed_support_count=channel_content_count_calc(Support),
        )
    )
    p.ctx.execute(sql)
