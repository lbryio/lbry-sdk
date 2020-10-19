from sqlalchemy import select
from sqlalchemy.sql import func

from lbry.db.query_context import event_emitter, ProgressContext
from lbry.db.tables import Trending, Support, Claim
WINDOW = 576  # a day


@event_emitter("blockchain.sync.trending.update", "steps")
def calculate_trending(height, p: ProgressContext):
    # zero all as decay
    with p.ctx.engine.begin() as ctx:
        _trending(height, ctx)


def _trending(height, ctx):
        ctx.execute(Trending.delete())
        start = height - WINDOW
        trending = func.sum(Support.c.amount * (WINDOW - (height - Support.c.height)))
        sql = select([Claim.c.claim_hash, trending, trending, trending, 4]).where(
            (Support.c.claim_hash == Claim.c.claim_hash)
            & (Support.c.height <= height)
            & (Support.c.height >= start)).group_by(Claim.c.claim_hash)
        ctx.execute(Trending.insert().from_select(
            ['claim_hash', 'trending_global', 'trending_local', 'trending_mixed', 'trending_group'], sql))


if __name__ == "__main__":
    from sqlalchemy import create_engine
    import time
    start = time.time()
    engine = create_engine("postgresql:///lbry")
    for height in range(830000, 840000, 1000):
        start = time.time()
        _trending(height, engine)
        print(f"{height} took {time.time() - start} seconds")
