# pylint: disable=singleton-comparison
from sqlalchemy.future import select

from .constants import CLAIM_TYPE_CODES
from .queries import get_txos
from .query_context import progress, Event
from .tables import (
    TXO, TXI,
    Claim
)


def process_inputs(heights):
    with progress(Event.INPUT_UPDATE) as p:
        if p.ctx.is_sqlite:
            address_query = select(TXO.c.address).where(TXI.c.txo_hash == TXO.c.txo_hash)
            sql = (
                TXI.update()
                .values(address=address_query.scalar_subquery())
                .where(TXI.c.address == None)
            )
        else:
            sql = (
                TXI.update()
                .values({TXI.c.address: TXO.c.address})
                .where((TXI.c.address == None) & (TXI.c.txo_hash == TXO.c.txo_hash))
            )
        p.start(1)
        p.ctx.execute(sql)


def process_claims(heights):

    with progress(Event.CLAIM_DELETE) as p:
        p.start(1)
        p.ctx.execute(Claim.delete())

    with progress(Event.CLAIM_UPDATE) as p:
        loader = p.ctx.get_bulk_loader()
        for claim in get_txos(
                txo_type__in=CLAIM_TYPE_CODES, is_spent=False,
                height__gte=heights[0], height__lte=heights[1])[0]:
            loader.add_claim(claim)
        loader.save()


def process_supports(heights):
    pass
