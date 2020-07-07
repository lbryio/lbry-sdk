# pylint: disable=singleton-comparison
from sqlalchemy.future import select

from lbry.db.constants import CLAIM_TYPE_CODES, TXO_TYPES
from lbry.db.queries import select_txos, rows_to_txos
from lbry.db.query_context import progress, Event
from lbry.db.tables import (
    TXO, TXI, Claim, Support
)


def process_all_things_after_sync():
    with progress(Event.INPUT_UPDATE) as p:
        p.start(2)
        set_input_addresses(p.ctx)
        p.step(1)
        update_spent_outputs(p.ctx)
        p.step(2)
    with progress(Event.SUPPORT_DELETE) as p:
        p.start(1)
        sql = Support.delete().where(condition_spent_supports)
        p.ctx.execute(sql)
    with progress(Event.SUPPORT_INSERT) as p:
        loader = p.ctx.get_bulk_loader()
        for support in rows_to_txos(p.ctx.fetchall(select_missing_supports)):
            loader.add_support(support)
        loader.save()
    with progress(Event.CLAIM_DELETE) as p:
        p.start(1)
        sql = Claim.delete().where(condition_spent_claims())
        p.ctx.execute(sql)
    with progress(Event.CLAIM_INSERT) as p:
        loader = p.ctx.get_bulk_loader()
        for claim in rows_to_txos(p.ctx.fetchall(select_missing_claims)):
            loader.add_claim(claim)
        loader.save()
    with progress(Event.CLAIM_UPDATE) as p:
        loader = p.ctx.get_bulk_loader()
        for claim in rows_to_txos(p.ctx.fetchall(select_stale_claims)):
            loader.update_claim(claim)
        loader.save()


def set_input_addresses(ctx):
    # Update TXIs to have the address of TXO they are spending.
    if ctx.is_sqlite:
        address_query = select(TXO.c.address).where(TXI.c.txo_hash == TXO.c.txo_hash)
        set_addresses = (
            TXI.update()
            .values(address=address_query.scalar_subquery())
            .where(TXI.c.address == None)
        )
    else:
        set_addresses = (
            TXI.update()
            .values({TXI.c.address: TXO.c.address})
            .where((TXI.c.address == None) & (TXI.c.txo_hash == TXO.c.txo_hash))
        )

    ctx.execute(set_addresses)


def update_spent_outputs(ctx):
    # Update spent TXOs setting spent_height
    set_spent_height = (
        TXO.update()
        .values({
            TXO.c.spent_height: (
                select(TXI.c.height)
                .where(TXI.c.txo_hash == TXO.c.txo_hash)
                .scalar_subquery()
            )
        }).where(
            (TXO.c.spent_height == 0) &
            (TXO.c.txo_hash.in_(select(TXI.c.txo_hash)))
        )
    )
    ctx.execute(set_spent_height)


def condition_spent_claims(claim_type: list = None):
    if claim_type is not None:
        if len(claim_type) == 0:
            raise ValueError("Missing 'claim_type'.")
        if len(claim_type) == 1:
            type_filter = TXO.c.txo_type == claim_type[0]
        else:
            type_filter = TXO.c.txo_type.in_(claim_type)
    else:
        type_filter = TXO.c.txo_type.in_(CLAIM_TYPE_CODES)
    return Claim.c.claim_hash.notin_(
        select(TXO.c.claim_hash).where(type_filter & (TXO.c.spent_height == 0))
    )


# find UTXOs that are claims and their claim_id is not in claim table,
# this means they need to be inserted
select_missing_claims = (
    select_txos(txo_type__in=CLAIM_TYPE_CODES, spent_height=0, claim_id_not_in_claim_table=True)
)


# find UTXOs that are claims and their txo_id is not in claim table,
# this ONLY works if you first ran select_missing_claims and inserted the missing claims, then
# all claims_ids should match between TXO and Claim table but txo_hashes will not match for
# claims that are not up-to-date
select_stale_claims = (
    select_txos(txo_type__in=CLAIM_TYPE_CODES, spent_height=0, txo_id_not_in_claim_table=True)
)


condition_spent_supports = (
    Support.c.txo_hash.notin_(
        select(TXO.c.txo_hash).where(
            (TXO.c.txo_type == TXO_TYPES['support']) &
            (TXO.c.spent_height == 0)
        )
    )
)


condition_missing_supports = (
    (TXO.c.txo_type == TXO_TYPES['support']) &
    (TXO.c.spent_height == 0) &
    (TXO.c.txo_hash.notin_(select(Support.c.txo_hash)))
)


select_missing_supports = (
    select_txos(txo_type=TXO_TYPES['support'], spent_height=0, txo_id_not_in_support_table=True)
)
