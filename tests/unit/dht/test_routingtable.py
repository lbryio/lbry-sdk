import hashlib
from twisted.trial import unittest
from twisted.internet import defer
from lbrynet.dht import constants
from lbrynet.dht.routingtable import TreeRoutingTable
from lbrynet.dht.contact import ContactManager
from lbrynet.dht.distance import Distance


class FakeRPCProtocol(object):
    """ Fake RPC protocol; allows lbrynet.dht.contact.Contact objects to "send" RPCs """
    def sendRPC(self, *args, **kwargs):
        return defer.succeed(None)


class TreeRoutingTableTest(unittest.TestCase):
    """ Test case for the RoutingTable class """
    def setUp(self):
        h = hashlib.sha384()
        h.update('node1')
        self.contact_manager = ContactManager()
        self.nodeID = h.digest()
        self.protocol = FakeRPCProtocol()
        self.routingTable = TreeRoutingTable(self.nodeID)

    def testDistance(self):
        """ Test to see if distance method returns correct result"""

        # testList holds a couple 3-tuple (variable1, variable2, result)
        basicTestList = [(chr(170) * 48, chr(85) * 48, long((chr(255) * 48).encode('hex'), 16))]

        for test in basicTestList:
            result = Distance(test[0])(test[1])
            self.failIf(result != test[2], 'Result of _distance() should be %s but %s returned' %
                        (test[2], result))

    @defer.inlineCallbacks
    def testAddContact(self):
        """ Tests if a contact can be added and retrieved correctly """
        # Create the contact
        h = hashlib.sha384()
        h.update('node2')
        contactID = h.digest()
        contact = self.contact_manager.make_contact(contactID, '127.0.0.1', 9182, self.protocol)
        # Now add it...
        yield self.routingTable.addContact(contact)
        # ...and request the closest nodes to it (will retrieve it)
        closestNodes = self.routingTable.findCloseNodes(contactID)
        self.failUnlessEqual(len(closestNodes), 1, 'Wrong amount of contacts returned; expected 1,'
                                                   ' got %d' % len(closestNodes))
        self.failUnless(contact in closestNodes, 'Added contact not found by issueing '
                                                 '_findCloseNodes()')

    @defer.inlineCallbacks
    def testGetContact(self):
        """ Tests if a specific existing contact can be retrieved correctly """
        h = hashlib.sha384()
        h.update('node2')
        contactID = h.digest()
        contact = self.contact_manager.make_contact(contactID, '127.0.0.1', 9182, self.protocol)
        # Now add it...
        yield self.routingTable.addContact(contact)
        # ...and get it again
        sameContact = self.routingTable.getContact(contactID)
        self.failUnlessEqual(contact, sameContact, 'getContact() should return the same contact')

    @defer.inlineCallbacks
    def testAddParentNodeAsContact(self):
        """
        Tests the routing table's behaviour when attempting to add its parent node as a contact
        """

        # Create a contact with the same ID as the local node's ID
        contact = self.contact_manager.make_contact(self.nodeID, '127.0.0.1', 9182, self.protocol)
        # Now try to add it
        yield self.routingTable.addContact(contact)
        # ...and request the closest nodes to it using FIND_NODE
        closestNodes = self.routingTable.findCloseNodes(self.nodeID, constants.k)
        self.failIf(contact in closestNodes, 'Node added itself as a contact')

    @defer.inlineCallbacks
    def testRemoveContact(self):
        """ Tests contact removal """
        # Create the contact
        h = hashlib.sha384()
        h.update('node2')
        contactID = h.digest()
        contact = self.contact_manager.make_contact(contactID, '127.0.0.1', 9182, self.protocol)
        # Now add it...
        yield self.routingTable.addContact(contact)
        # Verify addition
        self.failUnlessEqual(len(self.routingTable._buckets[0]), 1, 'Contact not added properly')
        # Now remove it
        self.routingTable.removeContact(contact)
        self.failUnlessEqual(len(self.routingTable._buckets[0]), 0, 'Contact not removed properly')

    @defer.inlineCallbacks
    def testSplitBucket(self):
        """ Tests if the the routing table correctly dynamically splits k-buckets """
        self.failUnlessEqual(self.routingTable._buckets[0].rangeMax, 2**384,
                             'Initial k-bucket range should be 0 <= range < 2**384')
        # Add k contacts
        for i in range(constants.k):
            h = hashlib.sha384()
            h.update('remote node %d' % i)
            nodeID = h.digest()
            contact = self.contact_manager.make_contact(nodeID, '127.0.0.1', 9182, self.protocol)
            yield self.routingTable.addContact(contact)
        self.failUnlessEqual(len(self.routingTable._buckets), 1,
                             'Only k nodes have been added; the first k-bucket should now '
                             'be full, but should not yet be split')
        # Now add 1 more contact
        h = hashlib.sha384()
        h.update('yet another remote node')
        nodeID = h.digest()
        contact = self.contact_manager.make_contact(nodeID, '127.0.0.1', 9182, self.protocol)
        yield self.routingTable.addContact(contact)
        self.failUnlessEqual(len(self.routingTable._buckets), 2,
                             'k+1 nodes have been added; the first k-bucket should have been '
                             'split into two new buckets')
        self.failIfEqual(self.routingTable._buckets[0].rangeMax, 2**384,
                         'K-bucket was split, but its range was not properly adjusted')
        self.failUnlessEqual(self.routingTable._buckets[1].rangeMax, 2**384,
                             'K-bucket was split, but the second (new) bucket\'s '
                             'max range was not set properly')
        self.failUnlessEqual(self.routingTable._buckets[0].rangeMax,
                             self.routingTable._buckets[1].rangeMin,
                             'K-bucket was split, but the min/max ranges were '
                             'not divided properly')

    @defer.inlineCallbacks
    def testFullSplit(self):
        """
        Test that a bucket is not split if it is full, but the new contact is not closer than the kth closest contact
        """

        self.routingTable._parentNodeID = 48 * chr(255)

        node_ids = [
            "100000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
            "200000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
            "300000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
            "400000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
            "500000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
            "600000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
            "700000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
            "800000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
            "ff0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
            "010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
        ]

        # Add k contacts
        for nodeID in node_ids:
            # self.assertEquals(nodeID, node_ids[i].decode('hex'))
            contact = self.contact_manager.make_contact(nodeID.decode('hex'), '127.0.0.1', 9182, self.protocol)
            yield self.routingTable.addContact(contact)
        self.failUnlessEqual(len(self.routingTable._buckets), 2)
        self.failUnlessEqual(len(self.routingTable._buckets[0]._contacts), 8)
        self.failUnlessEqual(len(self.routingTable._buckets[1]._contacts), 2)

        #  try adding a contact who is further from us than the k'th known contact
        nodeID = '020000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
        nodeID = nodeID.decode('hex')
        contact = self.contact_manager.make_contact(nodeID, '127.0.0.1', 9182, self.protocol)
        self.assertFalse(self.routingTable._shouldSplit(self.routingTable._kbucketIndex(contact.id), contact.id))
        yield self.routingTable.addContact(contact)
        self.failUnlessEqual(len(self.routingTable._buckets), 2)
        self.failUnlessEqual(len(self.routingTable._buckets[0]._contacts), 8)
        self.failUnlessEqual(len(self.routingTable._buckets[1]._contacts), 2)
        self.failIf(contact in self.routingTable._buckets[0]._contacts)
        self.failIf(contact in self.routingTable._buckets[1]._contacts)


# class KeyErrorFixedTest(unittest.TestCase):
#     """ Basic tests case for boolean operators on the Contact class """
#
#     def setUp(self):
#         own_id = (2 ** constants.key_bits) - 1
#         # carefully chosen own_id. here's the logic
#         # we want a bunch of buckets (k+1, to be exact), and we want to make sure own_id
#         # is not in bucket 0. so we put own_id at the end so we can keep splitting by adding to the
#         # end
#
#         self.table = lbrynet.dht.routingtable.OptimizedTreeRoutingTable(own_id)
#
#     def fill_bucket(self, bucket_min):
#         bucket_size = lbrynet.dht.constants.k
#         for i in range(bucket_min, bucket_min + bucket_size):
#             self.table.addContact(lbrynet.dht.contact.Contact(long(i), '127.0.0.1', 9999, None))
#
#     def overflow_bucket(self, bucket_min):
#         bucket_size = lbrynet.dht.constants.k
#         self.fill_bucket(bucket_min)
#         self.table.addContact(
#             lbrynet.dht.contact.Contact(long(bucket_min + bucket_size + 1),
#                                         '127.0.0.1', 9999, None))
#
#     def testKeyError(self):
#
#         # find middle, so we know where bucket will split
#         bucket_middle = self.table._buckets[0].rangeMax / 2
#
#         # fill last bucket
#         self.fill_bucket(self.table._buckets[0].rangeMax - lbrynet.dht.constants.k - 1)
#         # -1 in previous line because own_id is in last bucket
#
#         # fill/overflow 7 more buckets
#         bucket_start = 0
#         for i in range(0, lbrynet.dht.constants.k):
#             self.overflow_bucket(bucket_start)
#             bucket_start += bucket_middle / (2 ** i)
#
#         # replacement cache now has k-1 entries.
#         # adding one more contact to bucket 0 used to cause a KeyError, but it should work
#         self.table.addContact(
#             lbrynet.dht.contact.Contact(long(lbrynet.dht.constants.k + 2), '127.0.0.1', 9999, None))
#
#         # import math
#         # print ""
#         # for i, bucket in enumerate(self.table._buckets):
#         #     print "Bucket " + str(i) + " (2 ** " + str(
#         #         math.log(bucket.rangeMin, 2) if bucket.rangeMin > 0 else 0) + " <= x < 2 ** "+str(
#         #         math.log(bucket.rangeMax, 2)) + ")"
#         #     for c in bucket.getContacts():
#         #         print "  contact " + str(c.id)
#         # for key, bucket in self.table._replacementCache.iteritems():
#         #     print "Replacement Cache for Bucket " + str(key)
#         #     for c in bucket:
#         #         print "  contact " + str(c.id)
