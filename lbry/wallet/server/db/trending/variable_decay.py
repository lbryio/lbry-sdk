"""
Delayed AR with variable decay rate.

The spike height function is also simpler.
"""

import copy
import time
import apsw

# Half life in blocks *for lower LBC claims* (it's shorter for whale claims)
HALF_LIFE = 200

# Whale threshold (higher -> less DB writing)
WHALE_THRESHOLD = 3.0

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
        print("Resetting some columns. This might take a while...", flush=True, end="")
        c.execute(""" BEGIN;
                      UPDATE claim SET trending_group = 0;
                      UPDATE claim SET trending_mixed = 0;
                      UPDATE claim SET trending_global = 0;
                      UPDATE claim SET trending_local = 0;
                      COMMIT;""")
        print("done.")


def spike_height(x, x_old):
    """
    Compute the size of a trending spike (normed - constant units).
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



def get_time_boost(height):
    """
    Return the time boost at a given height.
    """
    return 1.0/DECAY**(height % RENORM_INTERVAL)


def trending_log(s):
    """
    Log a string.
    """
    if TRENDING_LOG:
        fout = open("trending_variable_decay.log", "a")
        fout.write(s)
        fout.flush()
        fout.close()

class TrendingData:
    """
    An object of this class holds trending data
    """
    def __init__(self):

        # Dict from claim id to some trending info.
        # Units are TIME VARIABLE in here
        self.claims = {}

        # Claims with >= WHALE_THRESHOLD LBC total amount
        self.whales = set([])

        # Have all claims been read from db yet?
        self.initialised = False

        # List of pending spikes.
        # Units are CONSTANT in here
        self.pending_spikes = []

    def insert_claim_from_load(self, height, claim_hash, trending_score, total_amount):
        assert not self.initialised
        self.claims[claim_hash] = {"trending_score": trending_score,
                                   "total_amount": total_amount,
                                   "changed": False}

        if trending_score >= WHALE_THRESHOLD*get_time_boost(height):
            self.add_whale(claim_hash)

    def add_whale(self, claim_hash):
        self.whales.add(claim_hash)

    def apply_spikes(self, height):
        """
        Apply all pending spikes that are due at this height.
        Apply with time boost ON.
        """
        time_boost = get_time_boost(height)

        for spike in self.pending_spikes:
            if spike["height"] > height:
                # Ignore
                pass
            if spike["height"] == height:
                # Apply
                self.claims[spike["claim_hash"]]["trending_score"] += time_boost*spike["size"]
                self.claims[spike["claim_hash"]]["changed"] = True

                if self.claims[spike["claim_hash"]]["trending_score"] >= WHALE_THRESHOLD*time_boost:
                    self.add_whale(spike["claim_hash"])
                if spike["claim_hash"] in self.whales and \
                    self.claims[spike["claim_hash"]]["trending_score"] < WHALE_THRESHOLD*time_boost:
                    self.whales.remove(spike["claim_hash"])


        # Keep only future spikes
        self.pending_spikes = [s for s in self.pending_spikes \
                               if s["height"] > height]




    def update_claim(self, height, claim_hash, total_amount):
        """
        Update trending data for a claim, given its new total amount.
        """
        assert self.initialised

        # Extract existing total amount and trending score
        # or use starting values if the claim is new
        if claim_hash in self.claims:
            old_state = copy.deepcopy(self.claims[claim_hash])
        else:
            old_state = {"trending_score": 0.0,
                         "total_amount": 0.0,
                         "changed": False}

        # Calculate LBC change
        change = total_amount - old_state["total_amount"]

        # Modify data if there was an LBC change
        if change != 0.0:
            spike = spike_height(total_amount,
                                 old_state["total_amount"])
            delay = min(int((total_amount + 1E-8)**0.4), HALF_LIFE)

            if change < 0.0:

                # How big would the spike be for the inverse movement?
                reverse_spike = spike_height(old_state["total_amount"], total_amount)

                # Remove that much spike from future pending ones
                for future_spike in self.pending_spikes:
                    if future_spike["claim_hash"] == claim_hash:
                        if reverse_spike >= future_spike["size"]:
                            reverse_spike -= future_spike["size"]
                            future_spike["size"] = 0.0
                        elif reverse_spike > 0.0:
                            future_spike["size"] -= reverse_spike
                            reverse_spike = 0.0

                delay = 0
                spike = -reverse_spike

            self.pending_spikes.append({"height": height + delay,
                                        "claim_hash": claim_hash,
                                        "size": spike})

            self.claims[claim_hash] = {"total_amount": total_amount,
                                       "trending_score": old_state["trending_score"],
                                       "changed": False}

    def process_whales(self, height):
        """
        Whale claims decay faster.
        """
        if height % SAVE_INTERVAL != 0:
            return

        for claim_hash in self.whales:
            trending_normed = self.claims[claim_hash]["trending_score"]/get_time_boost(height)

            # Overall multiplication factor for decay rate
            decay_rate_factor = trending_normed/WHALE_THRESHOLD

            # The -1 is because this is just the *extra* part being applied
            factor = (DECAY**SAVE_INTERVAL)**(decay_rate_factor - 1.0)
            # print(claim_hash, trending_normed, decay_rate_factor)
            self.claims[claim_hash]["trending_score"] *= factor
            self.claims[claim_hash]["changed"] = True


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

    # Insert initial states of claims
    everything = {"huge_whale": 0.01,
                  "huge_whale_botted": 0.01,
                  "medium_whale": 0.01,
                  "small_whale": 0.01,
                  "minnow": 0.01}

    def to_list_of_tuples(stuff):
        l = []
        for key in stuff:
            l.append((key, stuff[key]))
        return l

    db.executemany("""
        INSERT INTO claim (claim_hash, amount) VALUES (?, 1E8*?);
        """, to_list_of_tuples(everything))

    height = 0
    run(db, height, height, everything.keys())

    # Save trajectories for plotting
    trajectories = {}
    for key in trending_data.claims:
        trajectories[key] = [trending_data.claims[key]["trending_score"]]

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

        for key in trending_data.claims:
            trajectories[key].append(trending_data.claims[key]["trending_score"]\
                                        /get_time_boost(height))

    dbc.close()

    # pylint: disable=C0415
    import matplotlib.pyplot as plt
    for key in trending_data.claims:
        plt.plot(trajectories[key], label=key)
    plt.legend()
    plt.show()


# One global instance
# pylint: disable=C0103
trending_data = TrendingData()

def run(db, height, final_height, recalculate_claim_hashes):

    if height < final_height - 5*HALF_LIFE:
        trending_log("Skipping variable_decay trending at block {h}.\n".format(h=height))
        return

    start = time.time()

    trending_log("Calculating variable_decay trending at block {h}.\n".format(h=height))
    trending_log("    Length of trending data = {l}.\n"\
                        .format(l=len(trending_data.claims)))

    # Renormalise trending scores and mark all as having changed
    if height % RENORM_INTERVAL == 0:
        trending_log("    Renormalising trending scores...")

        keys = trending_data.claims.keys()
        trending_data.whales = set([])
        for key in keys:
            if trending_data.claims[key]["trending_score"] != 0.0:
                trending_data.claims[key]["trending_score"] *= DECAY_PER_RENORM
                trending_data.claims[key]["changed"] = True

                # Tiny becomes zero
                if abs(trending_data.claims[key]["trending_score"]) < 1E-3:
                    trending_data.claims[key]["trending_score"] = 0.0

                # Re-mark whales
                if trending_data.claims[key]["trending_score"] >= WHALE_THRESHOLD*get_time_boost(height):
                    trending_data.add_whale(key)

        trending_log("done.\n")


    # Regular message.
    trending_log("    Reading total_amounts from db and updating"\
                        + " trending scores in RAM...")

    # Update claims from db
    if not trending_data.initialised:

        trending_log("initial load...")
        # On fresh launch
        for row in db.execute("""
                              SELECT claim_hash, trending_mixed,
                                     (amount + support_amount)
                                         AS total_amount
                              FROM claim;
                              """):
            trending_data.insert_claim_from_load(height, row[0], row[1], 1E-8*row[2])
        trending_data.initialised = True
    else:
        for row in db.execute(f"""
                              SELECT claim_hash,
                                     (amount + support_amount)
                                         AS total_amount
                              FROM claim
                              WHERE claim_hash IN
                            ({','.join('?' for _ in recalculate_claim_hashes)});
                              """, recalculate_claim_hashes):
            trending_data.update_claim(height, row[0], 1E-8*row[1])

        # Apply pending spikes
        trending_data.apply_spikes(height)

    trending_log("done.\n")


    # Write trending scores to DB
    if height % SAVE_INTERVAL == 0:

        trending_log("    Finding and processing whales...")
        trending_log(str(len(trending_data.whales)) + " whales found...")
        trending_data.process_whales(height)
        trending_log("done.\n")

        trending_log("    Writing trending scores to db...")

        the_list = []
        keys = trending_data.claims.keys()

        for key in keys:
            if trending_data.claims[key]["changed"]:
                the_list.append((trending_data.claims[key]["trending_score"], key))
                trending_data.claims[key]["changed"] = False

        trending_log("{n} scores to write...".format(n=len(the_list)))

        db.executemany("UPDATE claim SET trending_mixed=? WHERE claim_hash=?;",
                       the_list)

        trending_log("done.\n")

    trending_log("Trending operations took {time} seconds.\n\n"\
                            .format(time=time.time() - start))


if __name__ == "__main__":
    test_trending()
