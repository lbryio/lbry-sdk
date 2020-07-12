from sqlalchemy.future import select

from lbry.db.query_context import progress, Event
from lbry.db.tables import TXI, TXO
from .queries import rows_to_txos


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
