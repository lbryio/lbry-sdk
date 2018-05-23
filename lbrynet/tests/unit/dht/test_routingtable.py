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
        basicTestList = [('123456789', '123456789', 0L), ('12345', '98765', 34527773184L)]

        for test in basicTestList:
            result = Distance(test[0])(test[1])
            self.failIf(result != test[2], 'Result of _distance() should be %s but %s returned' %
                        (test[2], result))

        baseIp = '146.64.19.111'
        ipTestList = ['146.64.29.222', '192.68.19.333']

        distanceOne = Distance(baseIp)(ipTestList[0])
        distanceTwo = Distance(baseIp)(ipTestList[1])

        self.failIf(distanceOne > distanceTwo, '%s should be closer to the base ip %s than %s' %
                    (ipTestList[0], baseIp, ipTestList[1]))

    @defer.inlineCallbacks
    def testAddContact(self):
        """ Tests if a contact can be added and retrieved correctly """
        # Create the contact
        h = hashlib.sha384()
        h.update('node2')
        contactID = h.digest()
        contact = self.contact_manager.make_contact(contactID, '127.0.0.1', 91824, self.protocol)
        # Now add it...
        yield self.routingTable.addContact(contact)
        # ...and request the closest nodes to it (will retrieve it)
        closestNodes = self.routingTable.findCloseNodes(contactID, constants.k)
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
        contact = self.contact_manager.make_contact(contactID, '127.0.0.1', 91824, self.protocol)
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
        contact = self.contact_manager.make_contact(self.nodeID, '127.0.0.1', 91824, self.protocol)
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
        contact = self.contact_manager.make_contact(contactID, '127.0.0.1', 91824, self.protocol)
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
            contact = self.contact_manager.make_contact(nodeID, '127.0.0.1', 91824, self.protocol)
            yield self.routingTable.addContact(contact)
        self.failUnlessEqual(len(self.routingTable._buckets), 1,
                             'Only k nodes have been added; the first k-bucket should now '
                             'be full, but should not yet be split')
        # Now add 1 more contact
        h = hashlib.sha384()
        h.update('yet another remote node')
        nodeID = h.digest()
        contact = self.contact_manager.make_contact(nodeID, '127.0.0.1', 91824, self.protocol)
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
        Test that a bucket is not split if it full, but does not cover the range
        containing the parent node's ID
        """

        self.routingTable._parentNodeID = 49 * 'a'
        # more than 384 bits; this will not be in the range of _any_ k-bucket

        node_ids = [
            "d4a27096d81e3c4efacce9f940e887c956f736f859c8037b556efec6fdda5c388ae92bae96b9eb204b24da2f376c4282",
            "553c0bfe119c35247c8cb8124091acb5c05394d5be7b019f6b1a5e18036af7a6148711ad6d47a0f955047bf9eac868aa",
            "671a179c251c90863f46e7ef54264cbbad743fe3127871064d8f051ce4124fcbd893339e11358f621655e37bd6a74097",
            "f896bafeb7ffb14b92986e3b08ee06807fdd5be34ab43f4f52559a5bbf0f12dedcd8556801f97c334b3ac9be7a0f7a93",
            "33a7deb380eb4707211184798b66840c22c396e8cde00b75b64f9ead09bad1141b56d35a93bd511adb28c6708eecc39d",
            "5e1e8ca575b536ae5ec52f7766ada904a64ebaad805909b1067ec3c984bf99909c9fcdd37e04ea5c5c043ea8830100ce",
            "ee18857d0c1f7fc413424f3ffead4871f2499646d4c2ac16f35f0c8864318ca21596915f18f85a3a25f8ceaa56c844aa",
            "68039f78fbf130873e7cce2f71f39d217dcb7f3fe562d64a85de4e21ee980b4a800f51bf6851d2bbf10e6590fe0d46b2"
        ]

        # Add k contacts
        for i in range(constants.k):
            h = hashlib.sha384()
            h.update('remote node %d' % i)
            nodeID = h.digest()
            self.assertEquals(nodeID, node_ids[i].decode('hex'))
            contact = self.contact_manager.make_contact(nodeID, '127.0.0.1', 91824, self.protocol)
            yield self.routingTable.addContact(contact)
        self.failUnlessEqual(len(self.routingTable._buckets), 1)
        self.failUnlessEqual(len(self.routingTable._buckets[0]._contacts), constants.k)

        #  try adding a contact who is further from us than the k'th known contact
        h = hashlib.sha384()
        h.update('yet another remote node!')
        nodeID = h.digest()
        contact = self.contact_manager.make_contact(nodeID, '127.0.0.1', 91824, self.protocol)
        yield self.routingTable.addContact(contact)
        self.failUnlessEqual(len(self.routingTable._buckets), 1)
        self.failUnlessEqual(len(self.routingTable._buckets[0]._contacts), constants.k)
        self.failIf(contact in self.routingTable._buckets[0]._contacts)

        #  try adding a contact who is closer to us than the k'th known contact
        h = hashlib.sha384()
        h.update('yet another remote node')
        nodeID = h.digest()
        contact = self.contact_manager.make_contact(nodeID, '127.0.0.1', 91824, self.protocol)
        yield self.routingTable.addContact(contact)
        self.failUnlessEqual(len(self.routingTable._buckets), 2)
        self.failUnlessEqual(len(self.routingTable._buckets[0]._contacts), 5)
        self.failUnlessEqual(len(self.routingTable._buckets[1]._contacts), 4)
        self.failIf(contact not in self.routingTable._buckets[1]._contacts)


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
