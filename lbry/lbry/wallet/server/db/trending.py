import copy
import time

# Half life in blocks
half_life = 288

# Decay coefficient per block
decay = 0.5**(1.0/half_life)

# How frequently to write trending values to the db
save_interval = 10

# Renormalisation interval
renorm_interval = 1000

# Decay coefficient per renormalisation interval
decay_per_renorm = decay**renorm_interval

assert renorm_interval % save_interval == 0


def soften(x, power=0.3):
    """
    Softening function applied to LBC total amounts
    """
    return x**power



class TrendingData:
    """
    An object of this class holds trending data
    """
    def __init__(self):

        # Dict from claim_id to [total_amount, total_amount_softened,
        #                           trending_score, changed_flag]
        self.claims = {}

        # Have all claims been read from db yet?
        self.initialised = False


    def update_claim(self, claim_id, total_amount, trending_score,
                        time_boost=1.0):
        """
        Update trending data for a claim, given its new total amount.
        """

        # Just putting data in the dictionary
        if not self.initialised:
            self.claims[claim_id] = [total_amount, soften(total_amount),
                                     trending_score, False]
            return

        # Extract existing total amount and trending score
        # or use starting values if the claim is new
        if claim_id in self.claims:
            old_state = copy.deepcopy(self.claims[claim_id])
        else:
            old_state = [0.0, soften(0.0), 0.0, False]

        # Calculate LBC change
        change = total_amount - old_state[0]

        # Modify data if there was an LBC change
        if change != 0.0:
            total_amount_softened = soften(total_amount)
            spike = total_amount_softened - old_state[1]
            trending_score = old_state[2] + time_boost*spike
            self.claims[claim_id] = [total_amount, total_amount_softened,
                                            trending_score, True]




# One global instance
trending_data = TrendingData()
f = open("trending.log", "w")
f.close()

def calculate_trending(db, height, final_height):

    f = open("trending.log", "a")

    if height < final_height - half_life:
        if height % 100 == 0:
            f.write("Skipping AR trending at block {h}.\n".format(h=height))
            f.flush()
        f.close()
        return

    start = time.time()

    f.write("Calculating AR trending at block {h}.\n".format(h=height))
    f.flush()

    # I'm using the original column names
    # trending_mixed = my trending score
    f.write("    Length of trending data = {l}.\n".format(l=len(trending_data.claims)))
    f.flush()

    # Update all claims from db
    f.write("    Reading all total_amounts from db and updating trending scores in RAM...")
    f.flush()
    time_boost = decay**(-(height % renorm_interval))
    for row in db.execute("""
                          SELECT claim_id, (amount + support_amount) AS total_amount, trending_mixed
                          FROM claim;
                          """):
        trending_data.update_claim(row[0], 1E-8*row[1], row[2], time_boost)
    f.write("done.\n")
    f.flush()
    trending_data.initialised = True

    # Renormalise trending scores and mark all as having changed
    if height % renorm_interval == 0:
        f.write("    Renormalising trending scores...")
        f.flush()

        keys = trending_data.claims.keys()
        for key in keys:
            trending_data.claims[key][2] *= decay_per_renorm
            trending_data.claims[key][3] = True
        f.write("done.\n")
        f.flush()



    # Write trending scores to DB
    if height % save_interval == 0:
        f.write("    Writing trending scores to db...")
        f.flush()

        the_list = []
        keys = trending_data.claims.keys()
        for key in keys:
            if trending_data.claims[key][3]:
                the_list.append((trending_data.claims[key][2], key))
                trending_data.claims[key][3] = False
        f.write("{n} scores to write...".format(n=len(the_list)))
        f.flush()

        db.executemany("UPDATE claim SET trending_mixed=? WHERE claim_id=?;",
                        the_list)
        f.write("done.\n")


    # Mark claims as not having changed
    if height % renorm_interval == 0:
        f.write("    Marking all claims as unchanged...")
        f.flush()

        keys = trending_data.claims.keys()
        for key in keys:
            trending_data.claims[key][3] = False
        f.write("done.\n")
        f.flush()

    f.write("Trending operations took {time} seconds.\n\n".format(time=time.time() - start))
    f.flush()
    f.close()

