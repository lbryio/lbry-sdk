# pylint: disable=singleton-comparison
from sqlalchemy import func, desc
from sqlalchemy.future import select

from lbry.db import TXO_TYPES, CLAIM_TYPE_CODES
from lbry.db.tables import Claim, Support, TXO


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
                .limit(1)
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
            .order_by(desc(TXO.c.height)).offset(1).limit(1)
            .scalar_subquery().label('previous_channel_hash')
        )
    if include_urls:
        channel = Claim.alias('channel')
        return sql.add_columns(
            signable.c.short_url.label('claim_url'),
            channel.c.short_url.label('channel_url')
        ).select_from(signable.join(channel, signable.c.channel_hash == channel.c.claim_hash))
    return sql.select_from(signable)


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


staked_support_amount_calc = claim_support_aggregation(func.coalesce(func.sum(Support.c.amount), 0))
staked_support_count_calc = claim_support_aggregation(func.count('*'))
