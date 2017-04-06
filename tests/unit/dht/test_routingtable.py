import unittest

from lbrynet.dht import contact, routingtable, constants


class KeyErrorFixedTest(unittest.TestCase):
    """ Basic tests case for boolean operators on the Contact class """

    def setUp(self):
        own_id = (2 ** constants.key_bits) - 1
        # carefully chosen own_id. here's the logic
        # we want a bunch of buckets (k+1, to be exact), and we want to make sure own_id
        # is not in bucket 0. so we put own_id at the end so we can keep splitting by adding to the
        # end

        self.table = routingtable.OptimizedTreeRoutingTable(own_id)

    def fill_bucket(self, bucket_min):
        bucket_size = constants.k
        for i in range(bucket_min, bucket_min + bucket_size):
            self.table.addContact(contact.Contact(long(i), '127.0.0.1', 9999, None))

    def overflow_bucket(self, bucket_min):
        bucket_size = constants.k
        self.fill_bucket(bucket_min)
        self.table.addContact(
            contact.Contact(long(bucket_min + bucket_size + 1), '127.0.0.1', 9999, None))

    def testKeyError(self):

        # find middle, so we know where bucket will split
        bucket_middle = self.table._buckets[0].rangeMax / 2

        # fill last bucket
        self.fill_bucket(self.table._buckets[0].rangeMax - constants.k - 1)
        # -1 in previous line because own_id is in last bucket

        # fill/overflow 7 more buckets
        bucket_start = 0
        for i in range(0, constants.k):
            self.overflow_bucket(bucket_start)
            bucket_start += bucket_middle / (2 ** i)

        # replacement cache now has k-1 entries.
        # adding one more contact to bucket 0 used to cause a KeyError, but it should work
        self.table.addContact(contact.Contact(long(constants.k + 2), '127.0.0.1', 9999, None))

        # import math
        # print ""
        # for i, bucket in enumerate(self.table._buckets):
        #     print "Bucket " + str(i) + " (2 ** " + str(
        #         math.log(bucket.rangeMin, 2) if bucket.rangeMin > 0 else 0) + " <= x < 2 ** "+str(
        #         math.log(bucket.rangeMax, 2)) + ")"
        #     for c in bucket.getContacts():
        #         print "  contact " + str(c.id)
        # for key, bucket in self.table._replacementCache.iteritems():
        #     print "Replacement Cache for Bucket " + str(key)
        #     for c in bucket:
        #         print "  contact " + str(c.id)
