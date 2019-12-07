from math import sqrt
import time

# Half life in blocks
half_life = 576

# Decay coefficient per block
decay = 0.5**(1.0/half_life)

# How frequently to write trending values to the db
save_interval = 10

# Renormalisation interval
renorm_interval = 1000

# Decay coefficient per renormalisation interval
decay_per_renorm = decay**renorm_interval

assert renorm_interval % save_interval == 0


def soften(delta):
    """
    Softening function applies to LBC changes.
    """
    if delta >= 0.0:
        return delta**0.3

    # If delta is negative
    mag = abs(delta)
    return -(mag**0.3)


class TrendingData:
    """
    An object of this class holds trending data
    """
    def __init__(self):

        # Dict from claim_id to [total_amount, trending_score, changed_flag]
        self.claims = {}


    def update_claim(self, time_boost, claim_id, total_amount):
        """
        Update trending data for a claim, given its new total amount.
        """
        # Extract existing total amount and trending score
        if claim_id in self.claims:
            old_data = self.claims[claim_id]
        else:
            old_data = [0, 0.0, False]

        change = total_amount - old_data[0]
        if change != 0.0:
            trending_score = old_data[1] + soften(1E-8*time_boost*change)
            self.claims[claim_id] = [total_amount, trending_score, True]


# One global instance
trending_data = TrendingData()
f = open("trending.log", "w")
f.close()


def calculate_trending(db, height, final_height):

    f = open("trending.log", "a")

    if height < final_height - 2*half_life:
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
                          SELECT claim_id, amount, support_amount
                          FROM claim;
                          """):
        trending_data.update_claim(time_boost, row[0], row[1] + row[2])
    f.write("done.\n")
    f.flush()

    # Renormalise trending scores and mark all as having changed
    if height % renorm_interval == 0:
        f.write("    Renormalising trending scores...")
        f.flush()

        keys = trending_data.claims.keys()
        for key in keys:
            trending_data.claims[key][1] *= decay_per_renorm
            trending_data.claims[key][2] = True
        f.write("done.\n")
        f.flush()



    # Write trending scores to DB
    if height % save_interval == 0:
        f.write("    Writing trending scores to db...")
        f.flush()

        the_list = []
        keys = trending_data.claims.keys()
        for key in keys:
            if trending_data.claims[key][2]:
                the_list.append((trending_data.claims[key][1], key))
                trending_data.claims[key][2] = False
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
            trending_data.claims[key][2] = False
        f.write("done.\n")
        f.flush()

    f.write("Trending operations took {time} seconds.\n\n".format(time=time.time() - start))
    f.flush()
    f.close()

