# pylint: disable=singleton-comparison
import logging
from contextvars import ContextVar
from functools import partial
from typing import Optional, Tuple

from sqlalchemy import table, bindparam, case, distinct, text, func, between, desc
from sqlalchemy.future import select
from sqlalchemy.schema import CreateTable

from lbry.db import queries
from lbry.db.tables import (
    Block as BlockTable, TX, TXO, TXI, Claim, Support,
    pg_add_txo_constraints_and_indexes, pg_add_txi_constraints_and_indexes
)
from lbry.db.query_context import ProgressContext, context, event_emitter
from lbry.db.queries import rows_to_txos
from lbry.db.sync import (
    select_missing_supports,
    condition_spent_claims,
    condition_spent_supports, condition_missing_supports,
    set_input_addresses, update_spent_outputs,
)
from lbry.db.utils import least
from lbry.db.constants import TXO_TYPES, CLAIM_TYPE_CODES

from lbry.blockchain.lbrycrd import Lbrycrd
from lbry.blockchain.block import Block, create_block_filter
from lbry.blockchain.bcd_data_stream import BCDataStream
from lbry.blockchain.transaction import Output, OutputScript, TXRefImmutable


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


def process_block_file(block_file_number: int, starting_height: int):
    ctx = context()
    loader = ctx.get_bulk_loader()
    last_block_processed = process_block_read(block_file_number, starting_height, loader)
    process_block_save(block_file_number, loader)
    return last_block_processed


@event_emitter("blockchain.sync.block.read", "blocks", step_size=100)
def process_block_read(block_file_number: int, starting_height: int, loader, p: ProgressContext):
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
            loader.add_block(block)
            last_block_processed = block_height
            p.step(done)
    return last_block_processed


@event_emitter("blockchain.sync.block.save", "txs")
def process_block_save(block_file_number: int, loader, p: ProgressContext):
    p.extra = {'block_file': block_file_number}
    loader.save(TX)


@event_emitter("blockchain.sync.block.filters", "blocks")
def process_block_filters(p: ProgressContext):
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


@event_emitter("blockchain.sync.spends", "steps")
def process_spends(initial_sync: bool, p: ProgressContext):

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
        # D. drop old txi and vacuum
        p.ctx.execute(text("DROP TABLE old_txi;"))
        if p.ctx.is_postgres:
            with p.ctx.engine.connect() as c:
                c.execute(text("COMMIT;"))
                c.execute(text("VACUUM ANALYZE txi;"))
        p.step(next_step())
        # E. restore integrity constraint
        if p.ctx.is_postgres:
            pg_add_txi_constraints_and_indexes(p.ctx.execute)
        p.step(next_step())
    else:
        set_input_addresses(p.ctx)
        p.step(next_step())

    # 2. Update spent TXOs setting spent_height
    if initial_sync:
        # F. txo table reshuffling
        p.ctx.execute(text("ALTER TABLE txo RENAME TO old_txo;"))
        p.ctx.execute(CreateTable(TXO, include_foreign_key_constraints=[]))
        if p.ctx.is_postgres:
            p.ctx.execute(text("ALTER TABLE txo DROP CONSTRAINT txo_pkey;"))
        p.step(next_step())
        # G. insert
        old_txo = table('old_txo', *(c.copy() for c in TXO.columns))
        columns = [c for c in old_txo.columns if c.name != 'spent_height']
        select_columns = columns + [func.coalesce(TXI.c.height, 0).label('spent_height')]
        insert_columns = columns + [TXO.c.spent_height]
        join_txo_on_txi = old_txo.join(TXI, old_txo.c.txo_hash == TXI.c.txo_hash, isouter=True)
        select_txos = (select(*select_columns).select_from(join_txo_on_txi))
        insert_txos = TXO.insert().from_select(insert_columns, select_txos)
        p.ctx.execute(insert_txos)
        p.step(next_step())
        # H. drop old txo
        p.ctx.execute(text("DROP TABLE old_txo;"))
        if p.ctx.is_postgres:
            with p.ctx.engine.connect() as c:
                c.execute(text("COMMIT;"))
                c.execute(text("VACUUM ANALYZE txo;"))
        p.step(next_step())
        # I. restore integrity constraint
        if p.ctx.is_postgres:
            pg_add_txo_constraints_and_indexes(p.ctx.execute)
        p.step(next_step())
    else:
        update_spent_outputs(p.ctx)
        p.step(next_step())


def insert_claims_with_lbrycrd(done, chain, p: ProgressContext, cursor):
    loader = p.ctx.get_bulk_loader()
    for rows in cursor.partitions(900):
        claim_metadata = iter(chain.db.sync_get_claim_metadata(claim_hashes=[row['claim_hash'] for row in rows]))
        for row in rows:
            metadata = next(claim_metadata, None)
            if metadata is None or metadata['claim_hash'] != row.claim_hash:
                log.error(
                    r"During sync'ing a claim in our db couldn't find a "
                    r"match in lbrycrd's db. This could be because lbrycrd "
                    r"moved a block forward and updated its own claim table "
                    r"while we were still on a previous block, or it could be "
                    r"a more fundamental issue... ¯\_(ツ)_/¯"
                )
                if metadata is None:
                    break
                if metadata['claim_hash'] != row.claim_hash:
                    continue
            txo = Output(
                amount=row.amount,
                script=OutputScript(row.src),
                tx_ref=TXRefImmutable.from_hash(row.tx_hash, row.height),
                position=row.txo_position,
            )
            extra = {
                'timestamp': row.timestamp,
                'staked_support_amount': int(row.staked_support_amount),
                'staked_support_count': int(row.staked_support_count),
                'short_url': metadata['short_url'],
                'creation_height': metadata['creation_height'],
                'activation_height': metadata['activation_height'],
                'expiration_height': metadata['expiration_height'],
                'takeover_height': metadata['takeover_height'],
            }
            if hasattr(row, 'signature'):
                extra.update({
                    'signature': row.signature,
                    'signature_digest': row.signature_digest,
                    'channel_public_key': row.channel_public_key,
                    'channel_url': row.channel_url
                })
            loader.add_claim(txo, **extra)
        if len(loader.claims) >= 10_000:
            done += loader.flush(Claim)
            p.step(done)
    done += loader.flush(Claim)
    p.step(done)
    return done


def channel_content_count_calc(signable):
    return (
        select(func.count('*'))
        .select_from(signable)
        .where((signable.c.channel_hash == Claim.c.claim_hash) & signable.c.is_signature_valid)
        .scalar_subquery()
    )


@event_emitter("blockchain.sync.claims", "claims")
def process_claims(starting_height: int, blocks_added: Optional[Tuple[int, int]], p: ProgressContext):
    chain = get_or_initialize_lbrycrd(p.ctx)
    initial_sync = not p.ctx.has_records(Claim)
    to_be_modified = p.ctx.fetchtotal(
        (TXO.c.txo_type.in_(CLAIM_TYPE_CODES)) &
        (TXO.c.spent_height == 0) &
        (TXO.c.txo_hash.notin_(select(Claim.c.txo_hash)))
    )
    to_be_deleted = to_be_synced = to_be_overtaken = to_be_counted_channel_members = 0
    condition_changed_stakes = condition_changed_channel_content = None
    if initial_sync:
        to_be_counted_channel_members = p.ctx.fetchtotal(
            (TXO.c.txo_type == TXO_TYPES['channel']) &
            (TXO.c.spent_height == 0)
        )
    else:
        to_be_deleted = p.ctx.fetchtotal(condition_spent_claims())
        if blocks_added:
            condition_changed_stakes = (
                (TXO.c.txo_type == TXO_TYPES['support']) & (
                    between(TXO.c.height, blocks_added[0], blocks_added[-1]) |
                    between(TXO.c.spent_height, blocks_added[0], blocks_added[-1])
                )
            )
            sql = (
                select(func.count(distinct(TXO.c.claim_hash)).label('total'))
                .where(condition_changed_stakes)
            )
            to_be_synced = p.ctx.fetchone(sql)['total']

            condition_changed_channel_content = (
                (TXO.c.channel_hash != None) & (
                    between(TXO.c.height, blocks_added[0], blocks_added[-1]) |
                    between(TXO.c.spent_height, blocks_added[0], blocks_added[-1])
                )
            )
            sql = (
                select(func.count(distinct(TXO.c.channel_hash)).label('total'))
                .where(condition_changed_channel_content)
            )
            to_be_synced += p.ctx.fetchone(sql)['total']

            to_be_overtaken = chain.db.sync_get_takeover_count(
                start_height=blocks_added[0], end_height=blocks_added[-1])

    p.start(to_be_deleted + to_be_modified + to_be_synced + to_be_overtaken + to_be_counted_channel_members)

    done = 0

    if to_be_deleted:
        deleted = p.ctx.execute(Claim.delete().where(condition_spent_claims()))
        assert to_be_deleted == deleted.rowcount, \
            f"Expected claims to be deleted {to_be_deleted}, actual deleted {deleted.rowcount}."
        done += deleted.rowcount
        p.step(done)

    support = TXO.alias('support')
    staked_support_amount_calc = (
        select(func.coalesce(func.sum(support.c.amount), 0)).where(
            (support.c.txo_type == TXO_TYPES['support']) &
            (support.c.spent_height == 0)
        )
    )
    staked_support_count_calc = (
        select(func.coalesce(func.count('*'), 0)).where(
            (support.c.txo_type == TXO_TYPES['support']) &
            (support.c.spent_height == 0)
        )
    )
    select_claims = (
        select(
            TXO.c.claim_hash, TXO.c.amount, TXO.c.position.label('txo_position'),
            TX.c.tx_hash, TX.c.height, TX.c.timestamp,
            func.substr(TX.c.raw, TXO.c.script_offset+1, TXO.c.script_length).label('src'),
            (staked_support_amount_calc
             .where(support.c.claim_hash == TXO.c.claim_hash)
             .label('staked_support_amount')),
            (staked_support_count_calc
             .where(support.c.claim_hash == TXO.c.claim_hash)
             .label('staked_support_count'))
        ).order_by(TXO.c.claim_hash)
    )

    with p.ctx.engine.connect().execution_options(stream_results=True) as c:
        # all channels need to be inserted first because channel short_url will needed to
        # set the contained claims canonical_urls when those are inserted next
        done = insert_claims_with_lbrycrd(
            done, chain, p, c.execute(
                select_claims.select_from(TXO.join(TX)).where(
                    (TXO.c.txo_type == TXO_TYPES['channel']) &
                    (TXO.c.spent_height == 0) &
                    (TXO.c.claim_hash.notin_(select(Claim.c.claim_hash)))
                )
            )
        )

    channel_txo = TXO.alias('channel_txo')
    channel_claim = Claim.alias('channel_claim')
    select_claims = (
        select_claims.add_columns(
            TXO.c.signature, TXO.c.signature_digest,
            case([(
                TXO.c.channel_hash != None,
                select(channel_txo.c.public_key).select_from(channel_txo).where(
                    (channel_txo.c.txo_type == TXO_TYPES['channel']) &
                    (channel_txo.c.claim_hash == TXO.c.channel_hash) &
                    (channel_txo.c.height <= TXO.c.height)
                ).order_by(desc(channel_txo.c.height)).limit(1).scalar_subquery()
            )]).label('channel_public_key'),
            channel_claim.c.short_url.label('channel_url')
        ).select_from(
            TXO
            .join(TX)
            .join(channel_claim, channel_claim.c.claim_hash == TXO.c.channel_hash, isouter=True)
        )
    )

    with p.ctx.engine.connect().execution_options(stream_results=True) as c:
        done = insert_claims_with_lbrycrd(
            done, chain, p, c.execute(
                select_claims.where(
                    (TXO.c.txo_type.in_(list(set(CLAIM_TYPE_CODES) - {TXO_TYPES['channel']}))) &
                    (TXO.c.spent_height == 0) &
                    (TXO.c.claim_hash.notin_(select(Claim.c.claim_hash)))
                )
            )
        )

    if initial_sync:
        channel_update_member_count_sql = (
            Claim.update()
            .where(Claim.c.claim_type == TXO_TYPES['channel'])
            .values(
                signed_claim_count=channel_content_count_calc(Claim.alias('content')),
                signed_support_count=channel_content_count_calc(Support),
            )
        )
        result = p.ctx.execute(channel_update_member_count_sql)
        done += result.rowcount
        p.step(done)

    if initial_sync:
        return

    select_stale_claims = select_claims.where(
        (TXO.c.txo_type.in_(CLAIM_TYPE_CODES)) &
        (TXO.c.spent_height == 0) &
        (TXO.c.txo_hash.notin_(select(Claim.c.txo_hash)))
    )
    loader = p.ctx.get_bulk_loader()
    for row in p.ctx.connection.execution_options(stream_results=True).execute(select_stale_claims):
        txo = Output(
            amount=row['amount'],
            script=OutputScript(row['src']),
            tx_ref=TXRefImmutable.from_hash(row['tx_hash'], row['height']),
            position=row['txo_position'],
        )
        loader.update_claim(
            txo, channel_url=row['channel_url'], timestamp=row['timestamp'],
            staked_support_amount=int(row['staked_support_amount']),
            staked_support_count=int(row['staked_support_count']),
            signature=row['signature'], signature_digest=row['signature_digest'],
            channel_public_key=row['channel_public_key'],
        )
        if len(loader.update_claims) >= 1000:
            done += loader.flush(Claim)
            p.step(done)
    done += loader.flush(Claim)
    p.step(done)

    for takeover in chain.db.sync_get_takeovers(start_height=blocks_added[0], end_height=blocks_added[-1]):
        update_claims = (
            Claim.update()
            .where(Claim.c.normalized == takeover['normalized'])
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
        result = p.ctx.execute(update_claims)
        done += result.rowcount
        p.step(done)

    channel_update_member_count_sql = (
        Claim.update()
        .where(
            (Claim.c.claim_type == TXO_TYPES['channel']) &
            Claim.c.claim_hash.in_(select(TXO.c.channel_hash).where(condition_changed_channel_content))
        ).values(
            signed_claim_count=channel_content_count_calc(Claim.alias('content')),
            signed_support_count=channel_content_count_calc(Support),
        )
    )
    p.ctx.execute(channel_update_member_count_sql)

    claim_update_supports_sql = (
        Claim.update()
        .where(Claim.c.claim_hash.in_(select(TXO.c.claim_hash).where(condition_changed_stakes)))
        .values(
            staked_support_amount=(
                staked_support_amount_calc
                .where(support.c.claim_hash == Claim.c.claim_hash)
                .scalar_subquery())
            ,
            staked_support_count=(
                staked_support_count_calc
                .where(support.c.claim_hash == Claim.c.claim_hash)
                .scalar_subquery()
            ),
        )
    )
    result = p.ctx.execute(claim_update_supports_sql)
    p.step(done+result.rowcount)


@event_emitter("blockchain.sync.supports", "supports")
def process_supports(starting_height: int, blocks_added: Optional[Tuple[int, int]], p: ProgressContext):
    done = 0
    to_be_deleted = p.ctx.fetchtotal(condition_spent_supports)
    to_be_inserted = p.ctx.fetchtotal(condition_missing_supports)
    p.start(to_be_deleted + to_be_inserted)

    sql = Support.delete().where(condition_spent_supports)
    deleted = p.ctx.execute(sql)
    assert to_be_deleted == deleted.rowcount,\
        f"Expected supports to be deleted {to_be_deleted}, actual deleted {deleted.rowcount}."
    done += deleted.rowcount
    p.step(done)

    if p.ctx.is_postgres:
        insert_supports = partial(p.ctx.pg_copy, Support)
    else:
        insert_supports = partial(p.ctx.execute, Support.insert())
    loader = p.ctx.get_bulk_loader()
    inserted_supports, supports = 0, []
    for txo in rows_to_txos(p.ctx.fetchall(select_missing_supports)):
        supports.append(loader.support_to_row(txo))
        if len(supports) >= 50_000:
            insert_supports(supports)
            inserted_supports += len(supports)
            supports = []
    if supports:
        insert_supports(supports)
        inserted_supports += len(supports)
    assert to_be_inserted == inserted_supports, \
        f"Expected supports to be inserted {to_be_inserted}, actual inserted {inserted_supports}."
    return

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
