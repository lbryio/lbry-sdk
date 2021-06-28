import copy
import math
import time

# Half life in blocks
HALF_LIFE = 134

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
    Install the AR trending algorithm.
    """
    check_trending_values(connection)

    if TRENDING_LOG:
        f = open("trending_ar.log", "a")
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


def spike_height(trending_score, x, x_old, time_boost=1.0):
    """
    Compute the size of a trending spike.
    """

    # Change in softened amount
    change_in_softened_amount = x**0.25 - x_old**0.25

    # Softened change in amount
    delta = x - x_old
    softened_change_in_amount = abs(delta)**0.25

    # Softened change in amount counts more for minnows
    if delta > 0.0:
        if trending_score >= 0.0:
            multiplier = 0.1/((trending_score/time_boost + softened_change_in_amount) + 1.0)
            softened_change_in_amount *= multiplier
    else:
        softened_change_in_amount *= -1.0

    return time_boost*(softened_change_in_amount + change_in_softened_amount)


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
        fout = open("trending_ar.log", "a")
        fout.write(s)
        fout.flush()
        fout.close()

class TrendingData:
    """
    An object of this class holds trending data
    """
    def __init__(self):
        self.claims = {}

        # Have all claims been read from db yet?
        self.initialised = False

    def insert_claim_from_load(self, claim_hash, trending_score, total_amount):
        assert not self.initialised
        self.claims[claim_hash] = {"trending_score": trending_score,
                                   "total_amount": total_amount,
                                   "changed": False}


    def update_claim(self, claim_hash, total_amount, time_boost=1.0):
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
            spike = spike_height(old_state["trending_score"],
                                 total_amount,
                                 old_state["total_amount"],
                                 time_boost)
            trending_score = old_state["trending_score"] + spike
            self.claims[claim_hash] = {"total_amount": total_amount,
                                       "trending_score": trending_score,
                                       "changed": True}



def test_trending():
    """
    Quick trending test for something receiving 10 LBC per block
    """
    data = TrendingData()
    data.insert_claim_from_load("abc", 10.0, 1.0)
    data.initialised = True

    for height in range(1, 5000):

        if height % RENORM_INTERVAL == 0:
            data.claims["abc"]["trending_score"] *= DECAY_PER_RENORM

        time_boost = get_time_boost(height)
        data.update_claim("abc", data.claims["abc"]["total_amount"] + 10.0,
                          time_boost=time_boost)


        print(str(height) + " " + str(time_boost) + " " \
                + str(data.claims["abc"]["trending_score"]))



# One global instance
# pylint: disable=C0103
trending_data = TrendingData()

def run(db, height, final_height, recalculate_claim_hashes):

    if height < final_height - 5*HALF_LIFE:
        trending_log("Skipping AR trending at block {h}.\n".format(h=height))
        return

    start = time.time()

    trending_log("Calculating AR trending at block {h}.\n".format(h=height))
    trending_log("    Length of trending data = {l}.\n"\
                        .format(l=len(trending_data.claims)))

    # Renormalise trending scores and mark all as having changed
    if height % RENORM_INTERVAL == 0:
        trending_log("    Renormalising trending scores...")

        keys = trending_data.claims.keys()
        for key in keys:
            if trending_data.claims[key]["trending_score"] != 0.0:
                trending_data.claims[key]["trending_score"] *= DECAY_PER_RENORM
                trending_data.claims[key]["changed"] = True

                # Tiny becomes zero
                if abs(trending_data.claims[key]["trending_score"]) < 1E-9:
                    trending_data.claims[key]["trending_score"] = 0.0

        trending_log("done.\n")


    # Regular message.
    trending_log("    Reading total_amounts from db and updating"\
                        + " trending scores in RAM...")

    # Get the value of the time boost
    time_boost = get_time_boost(height)

    # Update claims from db
    if not trending_data.initialised:
        # On fresh launch
        for row in db.execute("""
                              SELECT claim_hash, trending_mixed,
                                     (amount + support_amount)
                                         AS total_amount
                              FROM claim;
                              """):
            trending_data.insert_claim_from_load(row[0], row[1], 1E-8*row[2])
        trending_data.initialised = True
    else:
        for row in db.execute(f"""
                              SELECT claim_hash,
                                     (amount + support_amount)
                                         AS total_amount
                              FROM claim
                              WHERE claim_hash IN
                            ({','.join('?' for _ in recalculate_claim_hashes)});
                              """, list(recalculate_claim_hashes)):
            trending_data.update_claim(row[0], 1E-8*row[1], time_boost)

    trending_log("done.\n")


    # Write trending scores to DB
    if height % SAVE_INTERVAL == 0:

        trending_log("    Writing trending scores to db...")

        the_list = []
        keys = trending_data.claims.keys()
        for key in keys:
            if trending_data.claims[key]["changed"]:
                the_list.append((trending_data.claims[key]["trending_score"],
                                 key))
                trending_data.claims[key]["changed"] = False

        trending_log("{n} scores to write...".format(n=len(the_list)))

        db.executemany("UPDATE claim SET trending_mixed=? WHERE claim_hash=?;",
                       the_list)

        trending_log("done.\n")

    trending_log("Trending operations took {time} seconds.\n\n"\
                            .format(time=time.time() - start))


if __name__ == "__main__":
    test_trending()
