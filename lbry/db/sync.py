from sqlalchemy.future import select

from lbry.db.query_context import progress, Event
from lbry.db.tables import TXI, TXO, Claim, Support
from .constants import TXO_TYPES, CLAIM_TYPE_CODES
from .queries import (
    rows_to_txos, where_unspent_txos,
    where_abandoned_supports,
    where_abandoned_claims
)


SPENDS_UPDATE_EVENT = Event.add("client.sync.spends.update", "steps")
CLAIMS_INSERT_EVENT = Event.add("client.sync.claims.insert", "claims")
CLAIMS_UPDATE_EVENT = Event.add("client.sync.claims.update", "claims")
CLAIMS_DELETE_EVENT = Event.add("client.sync.claims.delete", "claims")
SUPPORT_INSERT_EVENT = Event.add("client.sync.claims.insert", "supports")
SUPPORT_UPDATE_EVENT = Event.add("client.sync.claims.update", "supports")
SUPPORT_DELETE_EVENT = Event.add("client.sync.claims.delete", "supports")


def process_all_things_after_sync():
    with progress(SPENDS_UPDATE_EVENT) as p:
        p.start(2)
        set_input_addresses(p.ctx)
        p.step(1)
        update_spent_outputs(p.ctx)
        p.step(2)
    with progress(SUPPORT_DELETE_EVENT) as p:
        p.start(1)
        sql = Support.delete().where(where_abandoned_supports())
        p.ctx.execute(sql)
    with progress(SUPPORT_INSERT_EVENT) as p:
        loader = p.ctx.get_bulk_loader()
        sql = where_unspent_txos(TXO_TYPES['support'], missing_in_supports_table=True)
        for support in rows_to_txos(p.ctx.fetchall(sql)):
            loader.add_support(support)
        loader.flush(Support)
    with progress(CLAIMS_DELETE_EVENT) as p:
        p.start(1)
        sql = Claim.delete().where(where_abandoned_claims())
        p.ctx.execute(sql)
    with progress(CLAIMS_INSERT_EVENT) as p:
        loader = p.ctx.get_bulk_loader()
        sql = where_unspent_txos(CLAIM_TYPE_CODES, missing_in_claims_table=True)
        for claim in rows_to_txos(p.ctx.fetchall(sql)):
            loader.add_claim(claim)
        loader.flush(Claim)
    with progress(CLAIMS_UPDATE_EVENT) as p:
        loader = p.ctx.get_bulk_loader()
        sql = where_unspent_txos(CLAIM_TYPE_CODES, missing_or_stale_in_claims_table=True)
        for claim in rows_to_txos(p.ctx.fetchall(sql)):
            loader.update_claim(claim)
        loader.flush(Claim)


def set_input_addresses(ctx):
    # Update TXIs to have the address of TXO they are spending.
    if ctx.is_sqlite:
        address_query = select(TXO.c.address).where(TXI.c.txo_hash == TXO.c.txo_hash)
        set_addresses = (
            TXI.update()
            .values(address=address_query.scalar_subquery())
            .where(TXI.c.address.is_(None))
        )
    else:
        set_addresses = (
            TXI.update()
            .values({TXI.c.address: TXO.c.address})
            .where((TXI.c.address.is_(None)) & (TXI.c.txo_hash == TXO.c.txo_hash))
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
            (TXO.c.txo_hash.in_(select(TXI.c.txo_hash).where(TXI.c.address.is_(None))))
        )
    )
    ctx.execute(set_spent_height)
