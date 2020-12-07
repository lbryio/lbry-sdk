from sqlalchemy import select
from sqlalchemy.sql import func

from lbry.db.query_context import event_emitter, ProgressContext
from lbry.db.tables import Trend, Support, Claim
WINDOW = 576  # a day


@event_emitter("blockchain.sync.trending.update", "steps")
def calculate_trending(height, p: ProgressContext):
    with p.ctx.engine.begin() as ctx:
        ctx.execute(Trend.delete())
        start = height - WINDOW
        trending = func.sum(Support.c.amount * (WINDOW - (height - Support.c.height)))
        sql = (
            select([Claim.c.claim_hash, trending, trending, trending, 4])
            .where(
                (Support.c.claim_hash == Claim.c.claim_hash) &
                (Support.c.height <= height) &
                (Support.c.height >= start)
            ).group_by(Claim.c.claim_hash)
        )
        ctx.execute(Trend.insert().from_select(
            ['claim_hash', 'trend_global', 'trend_local', 'trend_mixed', 'trend_group'], sql
        ))
