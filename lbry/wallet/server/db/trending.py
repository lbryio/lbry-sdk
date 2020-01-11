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

# Decay coefficient per renormalisation interval
DECAY_PER_RENORM = DECAY**RENORM_INTERVAL

# Log trending calculations?
TRENDING_LOG = True

assert RENORM_INTERVAL % SAVE_INTERVAL == 0


def spike_height(trending_score, x, x_old, time_boost=1.0):

    # Delta and sign
    sign = 0.0
    if x > x_old:
        sign = 1.0;
    elif x < x_old:
        sign = -1.0

    change_in_softened_amount = abs(x**0.25 - x_old**0.25)
    spike_height = time_boost*sign*change_in_softened_amount

    # Minnow boost
    boost = 0.0
    if spike_height > 0.0:
        boost = time_boost*math.exp(-(trending_score + spike_height)/time_boost)
    spike_height += boost

    return spike_height


class TrendingData:
    """
    An object of this class holds trending data
    """
    def __init__(self):

        self.claims = {}

        # Have all claims been read from db yet?
        self.initialised = False


    def update_claim(self, claim_id, total_amount, trending_score=0.0,
                        time_boost=1.0):
        """
        Update trending data for a claim, given its new total amount.
        """

        # Just putting data in the dictionary
        if not self.initialised:
            self.claims[claim_id] = {"trending_score": trending_score,
                                     "total_amount": total_amount,
                                     "changed": False}
            return

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

# One global instance
trending_data = TrendingData()
f = open("trending.log", "w")
f.close()

def calculate_trending(db, height, final_height, recalculate_claim_hashes):

    if TRENDING_LOG:
        f = open("trending.log", "a")

    if height < final_height - 5*HALF_LIFE:
        if TRENDING_LOG:
            if height % 100 == 0:
                f.write("Skipping AR trending at block {h}.\n".format(h=height))
                f.flush()
            f.close()
        return

    start = time.time()

    if TRENDING_LOG:
        f.write("Calculating AR trending at block {h}.\n".format(h=height))
        f.flush()

        # I'm using the original column names
        # trending_mixed = my trending score
        f.write("    Length of trending data = {l}.\n"\
                        .format(l=len(trending_data.claims)))
        f.flush()

        f.write("    Reading total_amounts from db and updating"\
                        + " trending scores in RAM...")
        f.flush()


    time_boost = DECAY**(-(height % RENORM_INTERVAL))

    # Update claims from db
    if len(trending_data.claims) == 0:
        # On fresh launch
        for row in db.execute("""
                              SELECT claim_id,
                                     (amount + support_amount)
                                         AS total_amount,
                                     trending_mixed
                              FROM claim;
                              """):
            trending_data.update_claim(row[0], 1E-8*row[1], row[2], time_boost)
        trending_data.initialised = True
    else:
        for row in db.execute(f"""
                              SELECT claim_id,
                                     (amount + support_amount)
                                         AS total_amount,
                                     trending_mixed
                              FROM claim
                              WHERE claim_hash IN
                            ({','.join('?' for _ in recalculate_claim_hashes)});
                              """, recalculate_claim_hashes):
            trending_data.update_claim(row[0], 1E-8*row[1], row[2], time_boost)

    if TRENDING_LOG:
        f.write("done.\n")
        f.flush()

    # Renormalise trending scores and mark all as having changed
    if height % RENORM_INTERVAL == 0:

        if TRENDING_LOG:
            f.write("    Renormalising trending scores...")
            f.flush()

        keys = trending_data.claims.keys()
        for key in keys:
            trending_data.claims[key]["trending_score"] *= DECAY_PER_RENORM
            trending_data.claims[key]["changed"] = True

        if TRENDING_LOG:
            f.write("done.\n")
            f.flush()


    # Write trending scores to DB
    if height % SAVE_INTERVAL == 0:

        if TRENDING_LOG:
            f.write("    Writing trending scores to db...")
            f.flush()

        the_list = []
        keys = trending_data.claims.keys()
        for key in keys:
            if trending_data.claims[key]["changed"]:
                the_list.append((trending_data.claims[key]["trending_score"],
                                 key))
                trending_data.claims[key]["changed"] = False

        if TRENDING_LOG:
            f.write("{n} scores to write...".format(n=len(the_list)))
            f.flush()

        db.executemany("UPDATE claim SET trending_mixed=? WHERE claim_id=?;",
                        the_list)

        if TRENDING_LOG:
            f.write("done.\n")


    # Mark claims as not having changed
    if height % RENORM_INTERVAL == 0:
        if TRENDING_LOG:
            f.write("    Marking all claims as unchanged...")
            f.flush()

        keys = trending_data.claims.keys()
        for key in keys:
            trending_data.claims[key]["changed"] = False


        if TRENDING_LOG:
            f.write("done.\n")
            f.flush()

    if TRENDING_LOG:
        f.write("Trending operations took {time} seconds.\n\n"\
                            .format(time=time.time() - start))
        f.flush()
        f.close()

