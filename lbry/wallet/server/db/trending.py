import math
import os
import sqlite3
import time


HALF_LIFE = 400
RENORM_INTERVAL = 1000
WHALE_THRESHOLD = 10000.0

def whale_decay_factor(lbc):
    """
    An additional decay factor applied to whale claims.
    """
    if lbc <= WHALE_THRESHOLD:
        return 1.0
    adjusted_half_life = HALF_LIFE/(math.log10(lbc/WHALE_THRESHOLD) + 1.0)
    return 2.0**(1.0/HALF_LIFE - 1.0/adjusted_half_life)


def soften(lbc):
    mag = abs(lbc) + 1E-8
    sign = 1.0 if lbc >= 0.0 else -1.0
    return sign*mag**0.25

def delay(lbc: int):
    if lbc <= 0:
        return 0
    elif lbc < 1000000:
        return int(lbc**0.5)
    else:
        return 1000


def inflate_units(height):
    blocks = height % RENORM_INTERVAL
    return 2.0 ** (blocks/HALF_LIFE)


PRAGMAS = ["PRAGMA FOREIGN_KEYS = OFF;",
           "PRAGMA JOURNAL_MODE = WAL;",
           "PRAGMA SYNCHRONOUS = 0;"]


class TrendingDB:

    def __init__(self, data_dir):
        """
        Opens the trending database in the directory data_dir.
        For testing, pass data_dir=":memory:"
        """
        if data_dir == ":memory:":
            path = ":memory:"
        else:
            path = os.path.join(data_dir, "trending.db")
        self.db = sqlite3.connect(path, check_same_thread=False)

        for pragma in PRAGMAS:
            self.execute(pragma)
        self.execute("BEGIN;")
        self._create_tables()
        self._create_indices()
        self.execute("COMMIT;")
        self.pending_events = []

    def execute(self, *args, **kwargs):
        return self.db.execute(*args, **kwargs)

    def add_event(self, event):
        self.pending_events.append(event)
#        print(f"Added event: {event}.", flush=True)


    def _create_tables(self):

        self.execute("""CREATE TABLE IF NOT EXISTS claims
            (claim_hash      BYTES NOT NULL PRIMARY KEY,
             bid_lbc         REAL NOT NULL,
             support_lbc     REAL NOT NULL,
             trending_score  REAL NOT NULL,
             needs_write     BOOLEAN NOT NULL)
            WITHOUT ROWID;""")

        self.execute("""CREATE TABLE IF NOT EXISTS spikes
            (claim_hash        BYTES NOT NULL REFERENCES claims (claim_hash),
             activation_height INTEGER NOT NULL,
             mass              REAL NOT NULL);""")


    def _create_indices(self):
        self.execute("CREATE INDEX IF NOT EXISTS idx1 ON spikes\
                        (activation_height, claim_hash, mass);")
        self.execute("CREATE INDEX IF NOT EXISTS idx2 ON spikes\
                        (claim_hash);")
        self.execute("CREATE INDEX IF NOT EXISTS idx3 ON claims (trending_score);")
        self.execute("CREATE INDEX IF NOT EXISTS idx4 ON claims (needs_write, claim_hash);")
        self.execute("CREATE INDEX IF NOT EXISTS idx5 ON claims (bid_lbc + support_lbc);")

    def get_trending_score(self, claim_hash):
        result = self.execute("SELECT trending_score FROM claims\
                             WHERE claim_hash = ?;", (claim_hash, ))\
                    .fetchall()
        if len(result) == 0:
            return 0.0
        else:
            return result[0]

    def _upsert_claim(self, height, event):

        claim_hash = event["claim_hash"]

        # Get old total lbc value of claim
        old_lbc_pair = self.execute("SELECT bid_lbc, support_lbc FROM claims\
                                     WHERE claim_hash = ?;",
                                    (claim_hash, )).fetchone()
        if old_lbc_pair is None:
            old_lbc_pair = (0.0, 0.0)

        if event["event"] == "upsert":
            new_lbc_pair = (event["lbc"], old_lbc_pair[1])
        elif event["event"] == "support":
            new_lbc_pair = (old_lbc_pair[0], old_lbc_pair[1] + event["lbc"])

        # Upsert the claim
        self.execute("INSERT INTO claims VALUES (?, ?, ?, ?, 1)\
                        ON CONFLICT (claim_hash) DO UPDATE\
                        SET bid_lbc     = excluded.bid_lbc,\
                            support_lbc = excluded.support_lbc;",
                        (claim_hash, new_lbc_pair[0], new_lbc_pair[1], 0.0))

        if self.active:
            old_lbc, lbc = sum(old_lbc_pair), sum(new_lbc_pair)

            # Add the spike
            softened_change = soften(lbc - old_lbc)
            change_in_softened = soften(lbc) - soften(old_lbc)
            spike_mass = (softened_change**0.25*change_in_softened**0.75).real
            activation_height = height + delay(lbc)
            if spike_mass != 0.0:
                self.execute("INSERT INTO spikes VALUES (?, ?, ?);",
                                (claim_hash, activation_height, spike_mass))

    def _delete_claim(self, claim_hash):
        self.execute("DELETE FROM spikes WHERE claim_hash = ?;", (claim_hash, ))
        self.execute("DELETE FROM claims WHERE claim_hash = ?;", (claim_hash, ))


    def _apply_spikes(self, height):
        spikes = self.execute("SELECT claim_hash, mass FROM spikes\
                                WHERE activation_height = ?;",
                                (height, )).fetchall()
        for claim_hash, mass in spikes: # TODO: executemany for efficiency
            self.execute("UPDATE claims SET trending_score = trending_score + ?,\
                            needs_write = 1\
                            WHERE claim_hash = ?;",
                            (mass, claim_hash))
        self.execute("DELETE FROM spikes WHERE activation_height = ?;",
                        (height, ))

    def _decay_whales(self):

        whales = self.execute("SELECT claim_hash, bid_lbc + support_lbc FROM claims\
                                 WHERE bid_lbc + support_lbc >= ?;", (WHALE_THRESHOLD, ))\
                            .fetchall()
        for claim_hash, lbc in whales:
            factor = whale_decay_factor(lbc)
            self.execute("UPDATE claims SET trending_score = trending_score*?, needs_write = 1\
                          WHERE claim_hash = ?;", (factor, claim_hash))


    def _renorm(self):
        factor = 2.0**(-RENORM_INTERVAL/HALF_LIFE)

        # Zero small values
        self.execute("UPDATE claims SET trending_score = 0.0, needs_write = 1\
                      WHERE trending_score <> 0.0 AND ABS(?*trending_score) < 1E-6;",
                        (factor, ))

        # Normalise other values
        self.execute("UPDATE claims SET trending_score = ?*trending_score, needs_write = 1\
                      WHERE trending_score <> 0.0;", (factor, ))


    def process_block(self, height, daemon_height):

        self.active = daemon_height - height <= 10*HALF_LIFE

        self.execute("BEGIN;")

        if self.active:

            # Check for a unit change
            if height % RENORM_INTERVAL == 0:
                self._renorm()

            # Apply extra whale decay
            self._decay_whales()

        # Upsert claims
        for event in self.pending_events:
            if event["event"] == "upsert":
                self._upsert_claim(height, event)

        # Process supports
        for event in self.pending_events:
            if event["event"] == "support":
                self._upsert_claim(height, event)

        # Delete claims
        for event in self.pending_events:
            if event["event"] == "delete":
                self._delete_claim(event["claim_hash"])

        if self.active:
            # Apply spikes
            self._apply_spikes(height)

        # Get set of claims that need writing to ES
        claims_to_write = set()
        for row in self.db.execute("SELECT claim_hash FROM claims WHERE\
                                    needs_write = 1;"):
            claims_to_write.add(row[0])
        self.db.execute("UPDATE claims SET needs_write = 0\
                         WHERE needs_write = 1;")

        self.execute("COMMIT;")

        self.pending_events.clear()

        return claims_to_write


if __name__ == "__main__":
    import matplotlib.pyplot as plt
    import numpy as np
    import numpy.random as rng
    import os

    trending_db = TrendingDB(":memory:")

    heights = list(range(1, 1000))
    heights = heights + heights[::-1] + heights

    events = [{"height": 45,
                "what": dict(claim_hash="a", event="upsert", lbc=1.0)},
              {"height": 100,
                "what": dict(claim_hash="a", event="support", lbc=3.0)},
              {"height": 150,
                "what": dict(claim_hash="a", event="support", lbc=-3.0)},
              {"height": 170,
                "what": dict(claim_hash="a", event="upsert", lbc=100000.0)},
              {"height": 730,
                "what": dict(claim_hash="a", event="delete")}]
    inverse_events = [{"height": 730,
                "what": dict(claim_hash="a", event="upsert", lbc=100000.0)},
              {"height": 170,
                "what": dict(claim_hash="a", event="upsert", lbc=1.0)},
              {"height": 150,
                "what": dict(claim_hash="a", event="support", lbc=3.0)},
              {"height": 100,
                "what": dict(claim_hash="a", event="support", lbc=-3.0)},
              {"height": 45,
                "what": dict(claim_hash="a", event="delete")}]


    xs, ys = [], []
    last_height = 0
    for height in heights:

        # Prepare the changes
        if height > last_height:
            es = events
        else:
            es = inverse_events

        for event in es:
            if event["height"] == height:
                trending_db.add_event(event["what"])

        # Process the block
        trending_db.process_block(height, height)

        if height > last_height: # Only plot when moving forward
            xs.append(height)
            y = trending_db.execute("SELECT trending_score FROM claims;").fetchone()
            y = 0.0 if y is None else y[0]
            ys.append(y/inflate_units(height))

        last_height = height

    xs = np.array(xs)
    ys = np.array(ys)

    plt.figure(1)
    plt.plot(xs, ys, "o-", alpha=0.2)

    plt.figure(2)
    plt.plot(xs)
    plt.show()
