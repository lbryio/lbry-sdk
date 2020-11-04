import logging
from typing import Tuple

from sqlalchemy import case, func, desc, text
from sqlalchemy.future import select

from lbry.db.queries.txio import (
    minimum_txo_columns, row_to_txo,
    where_unspent_txos, where_claims_with_changed_supports,
    count_unspent_txos, where_channels_with_changed_content,
    where_abandoned_claims, count_channels_with_changed_content,
    where_claims_with_changed_reposts,
)
from lbry.db.query_context import ProgressContext, event_emitter
from lbry.db.tables import TX, TXO, Claim, Support, pg_add_claim_and_tag_constraints_and_indexes, ClaimFilter
from lbry.db.utils import least
from lbry.db.constants import TXO_TYPES, CLAIM_TYPE_CODES
from lbry.blockchain.transaction import Output

from .context import get_or_initialize_lbrycrd


log = logging.getLogger(__name__)


def channel_content_count_calc(signable):
    return (
        select(func.count(signable.c.claim_hash))
        .where((signable.c.channel_hash == Claim.c.claim_hash) & signable.c.is_signature_valid)
        .scalar_subquery()
    )


support = TXO.alias('support')


def staked_support_aggregation(aggregate):
    return (
        select(aggregate).where(
            (support.c.txo_type == TXO_TYPES['support']) &
            (support.c.spent_height == 0)
        ).scalar_subquery()
    )


def staked_support_amount_calc(other):
    return (
        staked_support_aggregation(func.coalesce(func.sum(support.c.amount), 0))
        .where(support.c.claim_hash == other.c.claim_hash)
    )


def staked_support_count_calc(other):
    return (
        staked_support_aggregation(func.coalesce(func.count('*'), 0))
        .where(support.c.claim_hash == other.c.claim_hash)
    )


def reposted_claim_count_calc(other):
    repost = TXO.alias('repost')
    return (
        select(func.coalesce(func.count(repost.c.reposted_claim_hash), 0))
        .where(
            (repost.c.reposted_claim_hash == other.c.claim_hash) &
            (repost.c.spent_height == 0)
        ).scalar_subquery()
    )


def make_label(action, blocks):
    if blocks[0] == blocks[-1]:
        return f"{action} {blocks[0]:>6}"
    else:
        return f"{action} {blocks[0]:>6}-{blocks[-1]:>6}"


def select_claims_for_saving(
    blocks: Tuple[int, int],
    missing_in_claims_table=False,
    missing_or_stale_in_claims_table=False,
):
    channel_txo = TXO.alias('channel_txo')
    return select(
        *minimum_txo_columns, TXO.c.claim_hash,
        staked_support_amount_calc(TXO).label('staked_support_amount'),
        staked_support_count_calc(TXO).label('staked_support_count'),
        reposted_claim_count_calc(TXO).label('reposted_count'),
        TXO.c.signature, TXO.c.signature_digest,
        case([(
            TXO.c.channel_hash.isnot(None),
            select(channel_txo.c.public_key).select_from(channel_txo).where(
                (channel_txo.c.txo_type == TXO_TYPES['channel']) &
                (channel_txo.c.claim_hash == TXO.c.channel_hash) &
                (channel_txo.c.height <= TXO.c.height)
            ).order_by(desc(channel_txo.c.height)).limit(1).scalar_subquery()
        )]).label('channel_public_key')
    ).where(
        where_unspent_txos(
            CLAIM_TYPE_CODES, blocks,
            missing_in_claims_table=missing_in_claims_table,
            missing_or_stale_in_claims_table=missing_or_stale_in_claims_table,
        )
    ).select_from(TXO.join(TX))


def row_to_claim_for_saving(row) -> Tuple[Output, dict]:
    return row_to_txo(row), {
        'staked_support_amount': int(row.staked_support_amount),
        'staked_support_count': int(row.staked_support_count),
        'reposted_count': int(row.reposted_count),
        'signature': row.signature,
        'signature_digest': row.signature_digest,
        'channel_public_key': row.channel_public_key
    }


@event_emitter("blockchain.sync.claims.insert", "claims")
def claims_insert(
    blocks: Tuple[int, int],
    missing_in_claims_table: bool,
    flush_size: int,
    p: ProgressContext
):
    chain = get_or_initialize_lbrycrd(p.ctx)

    p.start(
        count_unspent_txos(
            CLAIM_TYPE_CODES, blocks,
            missing_in_claims_table=missing_in_claims_table,
        ), progress_id=blocks[0], label=make_label("add claims", blocks)
    )

    with p.ctx.connect_streaming() as c:
        loader = p.ctx.get_bulk_loader()
        cursor = c.execute(select_claims_for_saving(
            blocks, missing_in_claims_table=missing_in_claims_table
        ).order_by(TXO.c.claim_hash))
        for rows in cursor.partitions(900):
            claim_metadata = chain.db.sync_get_claim_metadata(
                claim_hashes=[row['claim_hash'] for row in rows]
            )
            i = 0
            for row in rows:
                metadata = claim_metadata[i] if i < len(claim_metadata) else {}
                if metadata and metadata['claim_hash'] == row.claim_hash:
                    i += 1
                txo, extra = row_to_claim_for_saving(row)
                extra.update({
                    'short_url': metadata.get('short_url'),
                    'creation_height': metadata.get('creation_height'),
                    'activation_height': metadata.get('activation_height'),
                    'expiration_height': metadata.get('expiration_height'),
                    'takeover_height': metadata.get('takeover_height'),
                })
                loader.add_claim(txo, **extra)
            if len(loader.claims) >= flush_size:
                p.add(loader.flush(Claim))
        p.add(loader.flush(Claim))


@event_emitter("blockchain.sync.claims.indexes", "steps")
def claims_constraints_and_indexes(p: ProgressContext):
    p.start(2 + len(pg_add_claim_and_tag_constraints_and_indexes))
    if p.ctx.is_postgres:
        p.ctx.execute_notx(text("VACUUM ANALYZE claim;"))
    p.step()
    if p.ctx.is_postgres:
        p.ctx.execute_notx(text("VACUUM ANALYZE tag;"))
    p.step()
    for constraint in pg_add_claim_and_tag_constraints_and_indexes:
        if p.ctx.is_postgres:
            p.ctx.execute(text(constraint))
        p.step()


@event_emitter("blockchain.sync.claims.vacuum", "steps")
def claims_vacuum(p: ProgressContext):
    p.start(2)
    if p.ctx.is_postgres:
        p.ctx.execute_notx(text("VACUUM claim;"))
    p.step()
    if p.ctx.is_postgres:
        p.ctx.execute_notx(text("VACUUM tag;"))
    p.step()


@event_emitter("blockchain.sync.claims.update", "claims")
def claims_update(blocks: Tuple[int, int], p: ProgressContext):
    p.start(
        count_unspent_txos(CLAIM_TYPE_CODES, blocks, missing_or_stale_in_claims_table=True),
        progress_id=blocks[0], label=make_label("mod claims", blocks)
    )
    with p.ctx.connect_streaming() as c:
        loader = p.ctx.get_bulk_loader()
        cursor = c.execute(select_claims_for_saving(
            blocks, missing_or_stale_in_claims_table=True
        ))
        for row in cursor:
            txo, extra = row_to_claim_for_saving(row)
            loader.update_claim(txo, **extra)
            if len(loader.update_claims) >= 25:
                p.add(loader.flush(Claim))
        p.add(loader.flush(Claim))


@event_emitter("blockchain.sync.claims.delete", "claims")
def claims_delete(claims, p: ProgressContext):
    p.start(claims, label="del claims")
    deleted = p.ctx.execute(Claim.delete().where(where_abandoned_claims()))
    p.step(deleted.rowcount)


@event_emitter("blockchain.sync.claims.takeovers", "claims")
def update_takeovers(blocks: Tuple[int, int], takeovers, p: ProgressContext):
    p.start(takeovers, label=make_label("mod winner", blocks))
    chain = get_or_initialize_lbrycrd(p.ctx)
    with p.ctx.engine.begin() as c:
        for takeover in chain.db.sync_get_takeovers(start_height=blocks[0], end_height=blocks[-1]):
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
            result = c.execute(update_claims)
            p.add(result.rowcount)


@event_emitter("blockchain.sync.claims.stakes", "claims")
def update_stakes(blocks: Tuple[int, int], claims: int, p: ProgressContext):
    p.start(claims)
    sql = (
        Claim.update()
        .where(where_claims_with_changed_supports(blocks))
        .values(
            staked_support_amount=staked_support_amount_calc(Claim),
            staked_support_count=staked_support_count_calc(Claim),
        )
    )
    result = p.ctx.execute(sql)
    p.step(result.rowcount)


@event_emitter("blockchain.sync.claims.reposts", "claims")
def update_reposts(blocks: Tuple[int, int], claims: int, p: ProgressContext):
    p.start(claims)
    sql = (
        Claim.update()
        .where(where_claims_with_changed_reposts(blocks))
        .values(reposted_count=reposted_claim_count_calc(Claim))
    )
    result = p.ctx.execute(sql)
    p.step(result.rowcount)


@event_emitter("blockchain.sync.claims.channels", "channels")
def update_channel_stats(blocks: Tuple[int, int], initial_sync: int, p: ProgressContext):
    update_sql = Claim.update().values(
        signed_claim_count=channel_content_count_calc(Claim.alias('content')),
        signed_support_count=channel_content_count_calc(Support),
    )
    if initial_sync:
        p.start(p.ctx.fetchtotal(Claim.c.claim_type == TXO_TYPES['channel']), label="channel stats")
        update_sql = update_sql.where(Claim.c.claim_type == TXO_TYPES['channel'])
    elif blocks:
        p.start(count_channels_with_changed_content(blocks), label="channel stats")
        update_sql = update_sql.where(where_channels_with_changed_content(blocks))
    else:
        return
    result = p.ctx.execute(update_sql)
    if result.rowcount and p.ctx.is_postgres:
        p.ctx.execute_notx(text("VACUUM claim;"))
    p.step(result.rowcount)


@event_emitter("blockchain.sync.claims.filters", "claim_filters")
def update_claim_filters(blocking_channel_hashes, filtering_channel_hashes, p: ProgressContext):
    def select_reposts(channel_hashes, filter_type=0):
        return select(
            Claim.c.reposted_claim_hash, filter_type).where(
            (Claim.c.channel_hash.in_(filtering_channel_hashes)) & (Claim.c.reposted_claim_hash.isnot(None)))

    p.ctx.execute(ClaimFilter.delete())
    p.ctx.execute(ClaimFilter.insert().from_select(
        ['claim_hash', 'filter_type'], select_reposts(blocking_channel_hashes, 1)))
    p.ctx.execute(p.ctx.insert_or_ignore(ClaimFilter).from_select(
        ['claim_hash', 'filter_type'], select_reposts(filtering_channel_hashes, 0)))
