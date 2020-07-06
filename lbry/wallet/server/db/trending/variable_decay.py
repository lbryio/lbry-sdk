"""
AR-like trending with a delayed effect and a faster
decay rate for high valued claims.
"""

import math
import time
import apsw

# Half life in blocks *for lower LBC claims* (it's shorter for whale claims)
HALF_LIFE = 200

# Whale threshold, in LBC (higher -> less DB writing)
WHALE_THRESHOLD = 10000.0

# Decay coefficient per block
DECAY = 0.5**(1.0/HALF_LIFE)

# How frequently to write trending values to the db
SAVE_INTERVAL = 10

# Renormalisation interval
RENORM_INTERVAL = 1000

# Assertion
assert RENORM_INTERVAL % SAVE_INTERVAL == 0

# Decay coefficient per renormalisation interval
DECAY_PER_RENORM = DECAY**(RENORM_INTERVAL)

# Log trending calculations?
TRENDING_LOG = True


def install(connection):
    """
    Install the trending algorithm.
    """
    check_trending_values(connection)
    trending_data.initialise(connection.cursor())

    if TRENDING_LOG:
        f = open("trending_variable_decay.log", "a")
        f.close()

# Stub
CREATE_TREND_TABLE = ""

def check_trending_values(connection):
    """
    If the trending values appear to be based on the zscore algorithm,
    reset them. This will allow resyncing from a standard snapshot.
    """
    c = connection.cursor()
    needs_reset = False
    for row in c.execute("SELECT COUNT(*) num FROM claim WHERE trending_global <> 0;"):
        if row[0] != 0:
            needs_reset = True
            break

    if needs_reset:
        print("Resetting some columns. This might take a while...", flush=True,
              end="")
        c.execute(""" BEGIN;
                      UPDATE claim SET trending_group = 0;
                      UPDATE claim SET trending_mixed = 0;
                      COMMIT;""")
        print("done.")




def trending_log(s):
    """
    Log a string to the log file
    """
    if TRENDING_LOG:
        fout = open("trending_variable_decay.log", "a")
        fout.write(s)
        fout.flush()
        fout.close()


def trending_unit(height):
    """
    Return the trending score unit at a given height.
    """
    # Round to the beginning of a SAVE_INTERVAL batch of blocks.
    _height = height - (height % SAVE_INTERVAL)
    return 1.0/DECAY**(height % RENORM_INTERVAL)


class TrendingDB:
    """
    An in-memory database of trending scores
    """

    def __init__(self):
        self.conn = apsw.Connection(":memory:")
        self.cursor = self.conn.cursor()
        self.initialised = False
        self.write_needed = set()

    def execute(self, query, *args, **kwargs):
        return self.cursor.execute(query, *args, **kwargs)

    def executemany(self, query, *args, **kwargs):
        return self.cursor.executemany(query, *args, **kwargs)

    def begin(self):
        self.execute("BEGIN;")

    def commit(self):
        self.execute("COMMIT;")

    def initialise(self, db):
        """
        Pass in claims.db
        """
        if self.initialised:
            return

        trending_log("Initialising trending database...")

        # The need for speed
        self.execute("PRAGMA JOURNAL_MODE=OFF;")
        self.execute("PRAGMA SYNCHRONOUS=0;")

        self.begin()

        # Create the tables
        self.execute("""
            CREATE TABLE IF NOT EXISTS claims
                (claim_hash     BYTES PRIMARY KEY,
                 lbc            REAL NOT NULL DEFAULT 0.0,
                 trending_score REAL NOT NULL DEFAULT 0.0)
            WITHOUT ROWID;""")

        self.execute("""
            CREATE TABLE IF NOT EXISTS spikes
                (id         INTEGER PRIMARY KEY,
                 claim_hash BYTES NOT NULL,
                 height     INTEGER NOT NULL,
                 mass       REAL NOT NULL,
                 FOREIGN KEY (claim_hash)
                    REFERENCES claims (claim_hash));""")

        # Clear out any existing data
        self.execute("DELETE FROM claims;")
        self.execute("DELETE FROM spikes;")

        # Create indexes
        self.execute("CREATE INDEX idx1 ON spikes (claim_hash, height, mass);")
        self.execute("CREATE INDEX idx2 ON spikes (claim_hash, height, mass DESC);")
        self.execute("CREATE INDEX idx3 on claims (lbc DESC, claim_hash, trending_score);")

        # Import data from claims.db
        for row in db.execute("""
                              SELECT claim_hash,
                                     1E-8*(amount + support_amount) AS lbc,
                                     trending_mixed
                              FROM claim;
                              """):
            self.execute("INSERT INTO claims VALUES (?, ?, ?);", row)
        self.commit()

        self.initialised = True
        trending_log("done.\n")

    def apply_spikes(self, height):
        """
        Apply spikes that are due. This occurs inside a transaction.
        """

        spikes = []
        unit = trending_unit(height)
        for row in self.execute("""
                                  SELECT SUM(mass), claim_hash FROM spikes
                                  WHERE height = ?
                                  GROUP BY claim_hash;
                                """, (height, )):
            spikes.append((row[0]*unit, row[1]))
            self.write_needed.add(row[1])

        self.executemany("""
                            UPDATE claims
                                SET trending_score = (trending_score + ?)
                            WHERE claim_hash = ?;
                         """, spikes)
        self.execute("DELETE FROM spikes WHERE height = ?;", (height, ))


    def decay_whales(self, height):
        """
        Occurs inside transaction.
        """
        if height % SAVE_INTERVAL != 0:
            return

        whales = self.execute("""
                              SELECT trending_score, lbc, claim_hash
                              FROM claims
                              WHERE lbc >= ?;
                              """, (WHALE_THRESHOLD, )).fetchall()
        whales2 = []
        for whale in whales:
            trending, lbc, claim_hash = whale

            # Overall multiplication factor for decay rate
            # At WHALE_THRESHOLD, this is 1
            # At 10*WHALE_THRESHOLD, it is 3
            decay_rate_factor = 1.0 + 2.0*math.log10(lbc/WHALE_THRESHOLD)

            # The -1 is because this is just the *extra* part being applied
            factor = (DECAY**SAVE_INTERVAL)**(decay_rate_factor - 1.0)

            # Decay
            trending *= factor
            whales2.append((trending, claim_hash))
            self.write_needed.add(claim_hash)

        self.executemany("UPDATE claims SET trending_score=? WHERE claim_hash=?;",
                         whales2)


    def renorm(self, height):
        """
        Renormalise trending scores. Occurs inside a transaction.
        """

        if height % RENORM_INTERVAL == 0:
            threshold = 1.0E-3/DECAY_PER_RENORM
            for row in self.execute("""SELECT claim_hash FROM claims
                                    WHERE ABS(trending_score) >= ?;""",
                                    (threshold, )):
                self.write_needed.add(row[0])

            self.execute("""UPDATE claims SET trending_score = ?*trending_score
                            WHERE ABS(trending_score) >= ?;""",
                         (DECAY_PER_RENORM, threshold))

    def write_to_claims_db(self, db, height):
        """
        Write changed trending scores to claims.db.
        """
        if height % SAVE_INTERVAL != 0:
            return

        rows = self.execute(f"""
                                SELECT trending_score, claim_hash
                                FROM claims
                                WHERE claim_hash IN
                                ({','.join('?' for _ in self.write_needed)});
                                """, self.write_needed).fetchall()

        db.executemany("""UPDATE claim SET trending_mixed = ?
                         WHERE claim_hash = ?;""", rows)

        # Clear list of claims needing to be written to claims.db
        self.write_needed = set()


    def update(self, db, height, recalculate_claim_hashes):
        """
        Update trending scores.
        Input is a cursor to claims.db, the block height, and the list of
        claims that changed.
        """
        assert self.initialised

        self.begin()
        self.renorm(height)

        # Fetch changed/new claims from claims.db
        for row in db.execute(f"""
                             SELECT claim_hash,
                                1E-8*(amount + support_amount) AS lbc
                             FROM claim
                             WHERE claim_hash IN
                             ({','.join('?' for _ in recalculate_claim_hashes)});
                             """, recalculate_claim_hashes):
            claim_hash, lbc = row

            # Insert into trending db if it does not exist
            self.execute("""
                         INSERT INTO claims (claim_hash)
                         VALUES (?)
                         ON CONFLICT (claim_hash) DO NOTHING;""",
                         (claim_hash, ))

            # See if it was an LBC change
            old = self.execute("SELECT * FROM claims WHERE claim_hash=?;",
                               (claim_hash, )).fetchone()
            lbc_old = old[1]

            # Save new LBC value into trending db
            self.execute("UPDATE claims SET lbc = ? WHERE claim_hash = ?;",
                         (lbc, claim_hash))

            if lbc > lbc_old:

                # Schedule a future spike
                delay = min(int((lbc + 1E-8)**0.4), HALF_LIFE)
                spike = (claim_hash, height + delay, spike_mass(lbc, lbc_old))
                self.execute("""INSERT INTO spikes
                                    (claim_hash, height, mass)
                                    VALUES (?, ?, ?);""", spike)

            elif lbc < lbc_old:

                # Subtract from future spikes
                penalty = spike_mass(lbc_old, lbc)
                spikes = self.execute("""
                                      SELECT * FROM spikes
                                      WHERE claim_hash = ?
                                      ORDER BY height ASC, mass DESC;
                                      """, (claim_hash, )).fetchall()
                for spike in spikes:
                    spike_id, mass = spike[0], spike[3]

                    if mass > penalty:
                        # The entire penalty merely reduces this spike
                        self.execute("UPDATE spikes SET mass=? WHERE id=?;",
                                     (mass - penalty, spike_id))
                        penalty = 0.0
                    else:
                        # Removing this spike entirely accounts for some (or
                        # all) of the penalty, then move on to other spikes
                        self.execute("DELETE FROM spikes WHERE id=?;",
                                     (spike_id, ))
                        penalty -= mass

                # If penalty remains, that's a negative spike to be applied
                # immediately.
                if penalty > 0.0:
                    self.execute("""
                                 INSERT INTO spikes (claim_hash, height, mass)
                                 VALUES (?, ?, ?);""",
                                 (claim_hash, height, -penalty))

        self.apply_spikes(height)
        self.decay_whales(height)
        self.commit()

        self.write_to_claims_db(db, height)





# The "global" instance to work with
# pylint: disable=C0103
trending_data = TrendingDB()

def spike_mass(x, x_old):
    """
    Compute the mass of a trending spike (normed - constant units).
    x_old = old LBC value
    x = new LBC value
    """

    # Sign of trending spike
    sign = 1.0
    if x < x_old:
        sign = -1.0

    # Magnitude
    mag = abs(x**0.25 - x_old**0.25)

    # Minnow boost
    mag *= 1.0 + 2E4/(x + 100.0)**2

    return sign*mag


def run(db, height, final_height, recalculate_claim_hashes):
    if height < final_height - 5*HALF_LIFE:
        trending_log(f"Skipping trending calculations at block {height}.\n")
        return

    start = time.time()
    trending_log(f"Calculating variable_decay trending at block {height}.\n")
    trending_data.update(db, height, recalculate_claim_hashes)
    end = time.time()
    trending_log(f"Trending operations took {end - start} seconds.\n\n")

def test_trending():
    """
    Quick trending test for claims with different support patterns.
    Actually use the run() function.
    """

    # Create a fake "claims.db" for testing
    # pylint: disable=I1101
    dbc = apsw.Connection(":memory:")
    db = dbc.cursor()

    # Create table
    db.execute("""
        BEGIN;
        CREATE TABLE claim (claim_hash     TEXT PRIMARY KEY,
                            amount         REAL NOT NULL DEFAULT 0.0,
                            support_amount REAL NOT NULL DEFAULT 0.0,
                            trending_mixed REAL NOT NULL DEFAULT 0.0);
        COMMIT;
        """)

    # Initialise trending data before anything happens with the claims
    trending_data.initialise(db)

    # Insert initial states of claims
    everything = {"huge_whale": 0.01, "medium_whale": 0.01, "small_whale": 0.01,
                  "huge_whale_botted": 0.01, "minnow": 0.01}

    def to_list_of_tuples(stuff):
        l = []
        for key in stuff:
            l.append((key, stuff[key]))
        return l

    db.executemany("""
        INSERT INTO claim (claim_hash, amount) VALUES (?, 1E8*?);
        """, to_list_of_tuples(everything))

    # Process block zero
    height = 0
    run(db, height, height, everything.keys())

    # Save trajectories for plotting
    trajectories = {}
    for row in trending_data.execute("""
                                     SELECT claim_hash, trending_score
                                     FROM claims;
                                     """):
        trajectories[row[0]] = [row[1]/trending_unit(height)]

    # Main loop
    for height in range(1, 1000):

        # One-off supports
        if height == 1:
            everything["huge_whale"] += 5E5
            everything["medium_whale"] += 5E4
            everything["small_whale"] += 5E3

        # Every block
        if height < 500:
            everything["huge_whale_botted"] += 5E5/500
            everything["minnow"] += 1

        # Remove supports
        if height == 500:
            for key in everything:
                everything[key] = 0.01

        # Whack into the db
        db.executemany("""
            UPDATE claim SET amount = 1E8*? WHERE claim_hash = ?;
            """, [(y, x) for (x, y) in to_list_of_tuples(everything)])

        # Call run()
        run(db, height, height, everything.keys())

        # Append current trending scores to trajectories
        for row in db.execute("""
                              SELECT claim_hash, trending_mixed
                              FROM claim;
                              """):
            trajectories[row[0]].append(row[1]/trending_unit(height))

    dbc.close()

    # pylint: disable=C0415
    import matplotlib.pyplot as plt
    for key in trajectories:
        plt.plot(trajectories[key], label=key)
    plt.legend()
    plt.show()





if __name__ == "__main__":
    test_trending()
