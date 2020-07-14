import logging
from typing import Tuple

from sqlalchemy import case, func, desc, text
from sqlalchemy.future import select

from lbry.db.queries.txio import (
    minimum_txo_columns, row_to_txo,
    where_unspent_txos, where_claims_with_changed_supports,
    count_unspent_txos, where_channels_with_changed_content,
    where_abandoned_claims, count_channels_with_changed_content
)
from lbry.db.query_context import ProgressContext, event_emitter
from lbry.db.tables import TX, TXO, Claim, Support, pg_add_claim_and_tag_constraints_and_indexes
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
        'signature': row.signature,
        'signature_digest': row.signature_digest,
        'channel_public_key': row.channel_public_key
    }


@event_emitter("blockchain.sync.claims.insert", "claims")
def claims_insert(
    blocks: Tuple[int, int],
    missing_in_claims_table: bool,
    p: ProgressContext
):
    chain = get_or_initialize_lbrycrd(p.ctx)

    p.start(
        count_unspent_txos(
            CLAIM_TYPE_CODES, blocks,
            missing_in_claims_table=missing_in_claims_table,
        ), progress_id=blocks[0], label=make_label("add claims", blocks)
    )

    with p.ctx.engine.connect().execution_options(stream_results=True) as c:
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
                metadata = claim_metadata[i] if i < len(claim_metadata) else None
                if metadata is None:
                    break
                if metadata['claim_hash'] != row.claim_hash:
                    continue
                i += 1
                txo, extra = row_to_claim_for_saving(row)
                extra.update({
                    'short_url': metadata['short_url'],
                    'creation_height': metadata['creation_height'],
                    'activation_height': metadata['activation_height'],
                    'expiration_height': metadata['expiration_height'],
                    'takeover_height': metadata['takeover_height'],
                })
                loader.add_claim(txo, **extra)
            if len(loader.claims) >= 25_000:
                p.add(loader.flush(Claim))
        p.add(loader.flush(Claim))


@event_emitter("blockchain.sync.claims.indexes", "steps")
def claims_constraints_and_indexes(p: ProgressContext):
    p.start(1 + len(pg_add_claim_and_tag_constraints_and_indexes))
    if p.ctx.is_postgres:
        with p.ctx.engine.connect() as c:
            c.execute(text("COMMIT;"))
            c.execute(text("VACUUM ANALYZE claim;"))
    p.step()
    for constraint in pg_add_claim_and_tag_constraints_and_indexes:
        if p.ctx.is_postgres:
            p.ctx.execute(constraint)
        p.step()


@event_emitter("blockchain.sync.claims.update", "claims")
def claims_update(blocks: Tuple[int, int], p: ProgressContext):
    p.start(
        count_unspent_txos(CLAIM_TYPE_CODES, blocks, missing_or_stale_in_claims_table=True),
        progress_id=blocks[0], label=make_label("mod claims", blocks)
    )
    with p.ctx.engine.connect().execution_options(stream_results=True) as c:
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
        result = p.ctx.execute(update_claims)
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
    p.step(result.rowcount)
