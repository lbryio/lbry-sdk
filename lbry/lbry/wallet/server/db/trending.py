from math import sqrt
import time

#######################################################
################### DEPRECATED ########################
#######################################################
CREATE_TREND_TABLE = """
    create table if not exists trend (
        claim_hash bytes not null,
        height integer not null,
        amount integer not null,
        primary key (claim_hash, height)
    ) without rowid;
"""


# Half life in blocks
half_life = 576

# Decay coefficient
decay = 0.5**(1.0/half_life)


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

        # Dict from claim_id to [total_amount, trending_score]
        self.claims = {}
        self.initialised = False


    def insert_claim(self, claim_id, total_amount, trending_score):
        """
        Insert a claim (happens upon re-running wallet server to
        repopulate trending data from the DB)
        """
        if claim_id in self.claims:
            return

        self.claims[claim_id] = [total_amount, trending_score]


    def update_claim(self, claim_id, total_amount):
        """
        Update trending data for a claim, given its new total amount.
        """

        # Extract existing total amount and trending score
        if claim_id in self.claims:
            old_data = self.claims[claim_id]
        else:
            old_data = [0.0, 0.0]

        trending_score = decay*old_data[1] \
                            + soften(1E-8*(total_amount - old_data[0]))
        self.claims[claim_id] = [total_amount, trending_score]


# One global instance
trending_data = TrendingData()


def calculate_trending(db, height, final_height):

    start = time.time()

    # I'm using the original column names
    # trending_global = my trending score
    # trending_local  = old total amount
    print("Calculating AR trending at block {h}...".format(h=height),
                end="", flush=True)


    # Read all values from db to re-init trending_data
    if not trending_data.initialised:
        for row in db.execute("""
                          SELECT claim_id, amount, support_amount, trending_global
                          FROM claim;
                          """):
            trending_data.insert_claim(row[0], row[1] + row[2], row[3])  
        trending_data.initialised = True

    # Update all claims from db
    for row in db.execute("""
                          SELECT claim_id, amount, support_amount
                          FROM claim;
                          """):
        trending_data.update_claim(row[0], row[1] + row[2])

    # Write trending scores to DB
    if height % 20 == 0: # and height >= (final_height - 100):
        the_list = []
        keys = trending_data.claims.keys()
        for key in keys:
            the_list.append((trending_data.claims[key][1], key))
        db.executemany("UPDATE claim SET trending_global=? WHERE claim_id=?;",
                        the_list)

    print("done. Took {time} seconds.".format(time=time.time() - start))

#######################################################
################### DEPRECATED ########################
#######################################################
# TRENDING_WINDOW is the number of blocks in ~6hr period (21600 seconds / 161 seconds per block)
TRENDING_WINDOW = 134

#######################################################
################### DEPRECATED ########################
#######################################################
# TRENDING_DATA_POINTS says how many samples to use for the trending algorithm
# i.e. only consider claims from the most recent (TRENDING_WINDOW * TRENDING_DATA_POINTS) blocks
TRENDING_DATA_POINTS = 28

#######################################################
################### DEPRECATED ########################
#######################################################
CREATE_TREND_TABLE = """
    create table if not exists trend (
        claim_hash bytes not null,
        height integer not null,
        amount integer not null,
        primary key (claim_hash, height)
    ) without rowid;
"""



#######################################################
################### DEPRECATED ########################
#######################################################
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
            self.power += self.last ** 2
        self.last = value

    @property
    def mean(self):
        return self.total / self.count

    @property
    def standard_deviation(self):
        value = (self.power / self.count) - self.mean ** 2
        return sqrt(value) if value > 0 else 0

    def finalize(self):
        if self.count == 0:
            return self.last
        return (self.last - self.mean) / (self.standard_deviation or 1)


#######################################################
################### DEPRECATED ########################
#######################################################
def register_trending_functions(connection):
    connection.create_aggregate("zscore", 1, ZScore)
