# pylint: disable=singleton-comparison
from sqlalchemy.future import select

from lbry.db.constants import CLAIM_TYPE_CODES, TXO_TYPES
from lbry.db.queries import select_txos, rows_to_txos
from lbry.db.query_context import progress, Event
from lbry.db.tables import (
    TXO, TXI, Claim, Support
)


def process_all_things_after_sync():
    process_inputs_outputs()
    process_supports()
    process_claim_deletes()
    process_claim_changes()


def process_inputs_outputs():

    with progress(Event.INPUT_UPDATE) as p:
        p.start(2)

        if p.ctx.is_sqlite:
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

        # 1. Update TXIs to have the address of TXO they are spending.
        p.ctx.execute(set_addresses)
        p.step(1)

        # 2. Update spent TXOs setting is_spent = True
        set_is_spent = (
            TXO.update()
            .values({TXO.c.is_spent: True})
            .where(
                (TXO.c.is_spent == False) &
                (TXO.c.txo_hash.in_(select(TXI.c.txo_hash)))
            )
        )
        p.ctx.execute(set_is_spent)
        p.step(2)


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
        select(TXO.c.claim_hash).where(type_filter & (TXO.c.is_spent == False))
    )


# find UTXOs that are claims and their claim_id is not in claim table,
# this means they need to be inserted
select_missing_claims = (
    select_txos(txo_type__in=CLAIM_TYPE_CODES, is_spent=False, claim_id_not_in_claim_table=True)
)


# find UTXOs that are claims and their txo_id is not in claim table,
# this ONLY works if you first ran select_missing_claims and inserted the missing claims, then
# all claims_ids should match between TXO and Claim table but txo_hashes will not match for
# claims that are not up-to-date
select_stale_claims = (
    select_txos(txo_type__in=CLAIM_TYPE_CODES, is_spent=False, txo_id_not_in_claim_table=True)
)


condition_spent_supports = (
    Support.c.txo_hash.notin_(
        select(TXO.c.txo_hash).where(
            (TXO.c.txo_type == TXO_TYPES['support']) &
            (TXO.c.is_spent == False)
        )
    )
)


select_missing_supports = (
    select_txos(txo_type=TXO_TYPES['support'], is_spent=False, txo_id_not_in_support_table=True)
)


def process_supports():
    with progress(Event.SUPPORT_DELETE) as p:
        p.start(1)
        sql = Support.delete().where(condition_spent_supports)
        p.ctx.execute(sql)
    with progress(Event.SUPPORT_INSERT) as p:
        loader = p.ctx.get_bulk_loader()
        for support in rows_to_txos(p.ctx.fetchall(select_missing_supports)):
            loader.add_support(support)
        loader.save()


def process_claim_deletes():
    with progress(Event.CLAIM_DELETE) as p:
        p.start(1)
        sql = Claim.delete().where(condition_spent_claims())
        p.ctx.execute(sql)


def process_claim_changes():
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
