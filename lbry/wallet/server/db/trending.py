import copy
import math
import time

# Half life in blocks
HALF_LIFE = 288

# Decay coefficient per block
DECAY = 0.5**(1.0/HALF_LIFE)

# How frequently to write trending values to the db
SAVE_INTERVAL = 10

# Renormalisation interval
RENORM_INTERVAL = 1000

# Assertion
assert (RENORM_INTERVAL % SAVE_INTERVAL == 0)

# Decay coefficient per renormalisation interval
DECAY_PER_RENORM = DECAY**(RENORM_INTERVAL)

# Log trending calculations?
TRENDING_LOG = True


def spike_height(trending_score, x, x_old, time_boost=1.0):
    """
    Compute the size of a trending spike.
    """
    change_in_softened_amount = x**0.25 - x_old**0.25
    spike_height = time_boost*change_in_softened_amount

    # Minnow boost
    boost = 0.0
    if spike_height > 0.0 and (trending_score + spike_height) > 0.0:
        boost = math.exp(-(trending_score + spike_height)/time_boost)
    spike_height += time_boost*boost

    return spike_height


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
        f = open("trending.log", "a")
        f.write(s)
        f.flush()
        f.close()

class TrendingData:
    """
    An object of this class holds trending data
    """
    def __init__(self):
        self.claims = {}

        # Have all claims been read from db yet?
        self.initialised = False

    def insert_claim_from_load(self, claim_id, trending_score, total_amount):
        assert not self.initialised
        self.claims[claim_id] = {"trending_score": trending_score,
                                 "total_amount": total_amount,
                                 "changed": False}


    def update_claim(self, claim_id, total_amount, time_boost=1.0):
        """
        Update trending data for a claim, given its new total amount.
        """
        assert self.initialised

        # Extract existing total amount and trending score
        # or use starting values if the claim is new
        if claim_id in self.claims:
            old_state = copy.deepcopy(self.claims[claim_id])
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
            self.claims[claim_id] = {"total_amount": total_amount,
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
trending_data = TrendingData()
f = open("trending.log", "w")
f.close()

def calculate_trending(db, height, final_height, recalculate_claim_hashes):

    if height < final_height - 5*HALF_LIFE:
        trending_log("Skipping AR trending at block {h}.\n".format(h=height))

    start = time.time()

    trending_log("Calculating AR trending at block {h}.\n".format(h=height))
    trending_log("    Length of trending data = {l}.\n"\
                        .format(l=len(trending_data.claims)))

    # Renormalise trending scores and mark all as having changed
    if height % RENORM_INTERVAL == 0:
        trending_log("    Renormalising trending scores...")

        keys = trending_data.claims.keys()
        for key in keys:
            trending_data.claims[key]["trending_score"] *= DECAY_PER_RENORM

        trending_log("done.\n")


    # Regular message.
    trending_log("    Reading total_amounts from db and updating"\
                        + " trending scores in RAM...")

    # Get the value of the time boost
    time_boost = get_time_boost(height)

    # Update claims from db
    if len(trending_data.claims) == 0:
        # On fresh launch
        for row in db.execute("""
                              SELECT claim_id, trending_mixed,
                                     (amount + support_amount)
                                         AS total_amount
                              FROM claim;
                              """):
            trending_data.insert_claim_from_load(row[0], row[1], 1E-8*row[2])
        trending_data.initialised = True
    else:
        for row in db.execute(f"""
                              SELECT claim_id,
                                     (amount + support_amount)
                                         AS total_amount
                              FROM claim
                              WHERE claim_hash IN
                            ({','.join('?' for _ in recalculate_claim_hashes)});
                              """, recalculate_claim_hashes):
            trending_data.update_claim(row[0], 1E-8*row[1], time_boost)

    trending_log("done.\n")


    if height % RENORM_INTERVAL == 0:
        # Mark all claims as having changed
        trending_data.claims[key]["changed"] = True


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

        db.executemany("UPDATE claim SET trending_mixed=? WHERE claim_id=?;",
                        the_list)

        trending_log("done.\n")


    # Mark claims as not having changed
    if height % RENORM_INTERVAL == 0:
        trending_log("    Marking all claims as unchanged...")

        keys = trending_data.claims.keys()
        for key in keys:
            trending_data.claims[key]["changed"] = False


        trending_log("done.\n")

    trending_log("Trending operations took {time} seconds.\n\n"\
                            .format(time=time.time() - start))


if __name__ == "__main__":
    test_trending()

