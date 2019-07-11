from math import sqrt

TRENDING_WINDOW = 650  # number of blocks, ~24hr period
TRENDING_DATA_POINTS = 7  # WINDOW * DATA_POINTS = ~1 week worth of trending data

CREATE_TREND_TABLE = """
    create table if not exists trend (
        claim_hash bytes not null,
        height integer not null,
        amount integer not null,
        primary key (claim_hash, height)
    ) without rowid;
"""


class ZScore:
    __slots__ = 'count', 'total', 'power', 'last'

    def __init__(self):
        self.count = 0
        self.total = 0
        self.power = 0
        self.last = None

    def step(self, value):
        if self.last is not None:
            self.count += 1
            self.total += self.last
            self.power += self.last**2
        self.last = value

    @property
    def mean(self):
        return self.total / self.count

    @property
    def standard_deviation(self):
        return sqrt((self.power / self.count) - self.mean**2)

    def finalize(self):
        if self.count == 0:
            return self.last
        return (self.last - self.mean) / (self.standard_deviation or 1)


def register_trending_functions(connection):
    connection.create_aggregate("zscore", 1, ZScore)


def calculate_trending(db, height, is_first_sync, final_height):
    # don't start tracking until we're at the end of initial sync
    if is_first_sync and height < (final_height - (TRENDING_WINDOW*TRENDING_DATA_POINTS)):
        return

    if height % TRENDING_WINDOW != 0:
        return

    db.execute(f"""
    DELETE FROM trend WHERE height < {height-(TRENDING_WINDOW*TRENDING_DATA_POINTS)}
    """)

    start = (height-TRENDING_WINDOW)+1
    db.execute(f"""
    INSERT OR IGNORE INTO trend (claim_hash, height, amount)
    SELECT claim_hash, {start}, COALESCE(
            (SELECT SUM(amount) FROM support WHERE claim_hash=claim.claim_hash
             AND height >= {start}), 0
        ) AS support_sum
    FROM claim WHERE support_sum > 0
    """)

    zscore = ZScore()
    for (global_sum,) in db.execute("SELECT AVG(amount) FROM trend GROUP BY height"):
        zscore.step(global_sum)
    global_mean, global_deviation = 0, 1
    if zscore.count > 0:
        global_mean = zscore.mean
        global_deviation = zscore.standard_deviation

    db.execute(f"""
    UPDATE claim SET
        trending_local = COALESCE((
            SELECT zscore(amount) FROM trend
            WHERE claim_hash=claim.claim_hash ORDER BY height DESC
        ), 0),
        trending_global = COALESCE((
            SELECT (amount - {global_mean}) / {global_deviation} FROM trend
            WHERE claim_hash=claim.claim_hash AND height = {start}
        ), 0),
        trending_group = 0,
        trending_mixed = 0
    """)

    # trending_group and trending_mixed determine how trending will show in query results
    # normally the SQL will be: "ORDER BY trending_group, trending_mixed"
    # changing the trending_group will have significant impact on trending results
    # changing the value used for trending_mixed will only impact trending within a trending_group
    db.execute(f"""
    UPDATE claim SET
        trending_group = CASE 
        WHEN trending_local > 0 AND trending_global > 0 THEN 4
        WHEN trending_local <= 0 AND trending_global > 0 THEN 3
        WHEN trending_local > 0 AND trending_global <= 0 THEN 2
        WHEN trending_local <= 0 AND trending_global <= 0 THEN 1
        END,
        trending_mixed = CASE 
        WHEN trending_local > 0 AND trending_global > 0 THEN trending_global
        WHEN trending_local <= 0 AND trending_global > 0 THEN trending_local
        WHEN trending_local > 0 AND trending_global <= 0 THEN trending_local
        WHEN trending_local <= 0 AND trending_global <= 0 THEN trending_global
        END
    WHERE trending_local <> 0 OR trending_global <> 0
    """)
