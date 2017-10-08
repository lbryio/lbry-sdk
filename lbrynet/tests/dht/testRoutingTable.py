#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive

import hashlib
import unittest

import lbrynet.dht.constants
import lbrynet.dht.routingtable
import lbrynet.dht.contact

class FakeRPCProtocol(object):
    """ Fake RPC protocol; allows lbrynet.dht.contact.Contact objects to "send" RPCs """
    def sendRPC(self, *args, **kwargs):
        return FakeDeferred()


class FakeDeferred(object):
    """ Fake Twisted Deferred object; allows the routing table to add callbacks that do nothing """
    def addCallback(self, *args, **kwargs):
        return
    def addErrback(self, *args, **kwargs):
        return


class TreeRoutingTableTest(unittest.TestCase):
    """ Test case for the RoutingTable class """
    def setUp(self):
        h = hashlib.sha1()
        h.update('node1')
        self.nodeID = h.digest()
        self.protocol = FakeRPCProtocol()
        self.routingTable = lbrynet.dht.routingtable.TreeRoutingTable(self.nodeID)
    
    def testDistance(self):
        """ Test to see if distance method returns correct result"""
        
        # testList holds a couple 3-tuple (variable1, variable2, result)
        basicTestList = [('123456789','123456789', 0L), ('12345', '98765', 34527773184L)]

        for test in basicTestList:
            result = self.routingTable.distance(test[0], test[1])
            self.failIf(result != test[2], 'Result of _distance() should be %s but %s returned' % (test[2], result))

        baseIp = '146.64.19.111'
        ipTestList = ['146.64.29.222', '192.68.19.333']

        distanceOne = self.routingTable.distance(baseIp, ipTestList[0])
        distanceTwo = self.routingTable.distance(baseIp, ipTestList[1])

        self.failIf(distanceOne > distanceTwo, '%s should be closer to the base ip %s than %s' % (ipTestList[0], baseIp, ipTestList[1]))
    
    def testAddContact(self):
        """ Tests if a contact can be added and retrieved correctly """
        # Create the contact
        h = hashlib.sha1()
        h.update('node2')
        contactID = h.digest()
        contact = lbrynet.dht.contact.Contact(contactID, '127.0.0.1', 91824, self.protocol)
        # Now add it...
        self.routingTable.addContact(contact)
        # ...and request the closest nodes to it (will retrieve it)
        closestNodes = self.routingTable.findCloseNodes(contactID, lbrynet.dht.constants.k)
        self.failUnlessEqual(len(closestNodes), 1, 'Wrong amount of contacts returned; expected 1, got %d' % len(closestNodes))
        self.failUnless(contact in closestNodes, 'Added contact not found by issueing _findCloseNodes()')
    
    def testGetContact(self):
        """ Tests if a specific existing contact can be retrieved correctly """
        h = hashlib.sha1()
        h.update('node2')
        contactID = h.digest()
        contact = lbrynet.dht.contact.Contact(contactID, '127.0.0.1', 91824, self.protocol)
        # Now add it...
        self.routingTable.addContact(contact)
        # ...and get it again
        sameContact = self.routingTable.getContact(contactID)
        self.failUnlessEqual(contact, sameContact, 'getContact() should return the same contact')
        
    def testAddParentNodeAsContact(self):
        """ Tests the routing table's behaviour when attempting to add its parent node as a contact """
        # Create a contact with the same ID as the local node's ID
        contact = lbrynet.dht.contact.Contact(self.nodeID, '127.0.0.1', 91824, self.protocol)
        # Now try to add it
        self.routingTable.addContact(contact)
        # ...and request the closest nodes to it using FIND_NODE
        closestNodes = self.routingTable.findCloseNodes(self.nodeID, lbrynet.dht.constants.k)
        self.failIf(contact in closestNodes, 'Node added itself as a contact')
    
    def testRemoveContact(self):
        """ Tests contact removal """
        # Create the contact
        h = hashlib.sha1()
        h.update('node2')
        contactID = h.digest()
        contact = lbrynet.dht.contact.Contact(contactID, '127.0.0.1', 91824, self.protocol)
        # Now add it...
        self.routingTable.addContact(contact)
        # Verify addition
        self.failUnlessEqual(len(self.routingTable._buckets[0]), 1, 'Contact not added properly')
        # Now remove it
        self.routingTable.removeContact(contact.id)
        self.failUnlessEqual(len(self.routingTable._buckets[0]), 0, 'Contact not removed properly')

    def testSplitBucket(self):
        """ Tests if the the routing table correctly dynamically splits k-buckets """
        self.failUnlessEqual(self.routingTable._buckets[0].rangeMax, 2**160, 'Initial k-bucket range should be 0 <= range < 2**160')
        # Add k contacts
        for i in range(lbrynet.dht.constants.k):
            h = hashlib.sha1()
            h.update('remote node %d' % i)
            nodeID = h.digest()
            contact = lbrynet.dht.contact.Contact(nodeID, '127.0.0.1', 91824, self.protocol)
            self.routingTable.addContact(contact)
        self.failUnlessEqual(len(self.routingTable._buckets), 1, 'Only k nodes have been added; the first k-bucket should now be full, but should not yet be split')
        # Now add 1 more contact
        h = hashlib.sha1()
        h.update('yet another remote node')
        nodeID = h.digest()
        contact = lbrynet.dht.contact.Contact(nodeID, '127.0.0.1', 91824, self.protocol)
        self.routingTable.addContact(contact)
        self.failUnlessEqual(len(self.routingTable._buckets), 2, 'k+1 nodes have been added; the first k-bucket should have been split into two new buckets')
        self.failIfEqual(self.routingTable._buckets[0].rangeMax, 2**160, 'K-bucket was split, but its range was not properly adjusted')
        self.failUnlessEqual(self.routingTable._buckets[1].rangeMax, 2**160, 'K-bucket was split, but the second (new) bucket\'s max range was not set properly')
        self.failUnlessEqual(self.routingTable._buckets[0].rangeMax, self.routingTable._buckets[1].rangeMin, 'K-bucket was split, but the min/max ranges were not divided properly')
        

    def testFullBucketNoSplit(self):
        """ Test that a bucket is not split if it full, but does not cover the range containing the parent node's ID """
        self.routingTable._parentNodeID = 21*'a' # more than 160 bits; this will not be in the range of _any_ k-bucket
        # Add k contacts
        for i in range(lbrynet.dht.constants.k):
            h = hashlib.sha1()
            h.update('remote node %d' % i)
            nodeID = h.digest()
            contact = lbrynet.dht.contact.Contact(nodeID, '127.0.0.1', 91824, self.protocol)
            self.routingTable.addContact(contact)
        self.failUnlessEqual(len(self.routingTable._buckets), 1, 'Only k nodes have been added; the first k-bucket should now be full, and there should not be more than 1 bucket')
        self.failUnlessEqual(len(self.routingTable._buckets[0]._contacts), lbrynet.dht.constants.k, 'Bucket should have k contacts; expected %d got %d' % (lbrynet.dht.constants.k, len(self.routingTable._buckets[0]._contacts)))
        # Now add 1 more contact
        h = hashlib.sha1()
        h.update('yet another remote node')
        nodeID = h.digest()
        contact = lbrynet.dht.contact.Contact(nodeID, '127.0.0.1', 91824, self.protocol)
        self.routingTable.addContact(contact)
        self.failUnlessEqual(len(self.routingTable._buckets), 1, 'There should not be more than 1 bucket, since the bucket should not have been split (parent node ID not in range)')
        self.failUnlessEqual(len(self.routingTable._buckets[0]._contacts), lbrynet.dht.constants.k, 'Bucket should have k contacts; expected %d got %d' % (lbrynet.dht.constants.k, len(self.routingTable._buckets[0]._contacts)))
        self.failIf(contact in self.routingTable._buckets[0]._contacts, 'New contact should have been discarded (since RPC is faked in this test)')

def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TreeRoutingTableTest))
    return suite

if __name__ == '__main__':
    # If this module is executed from the commandline, run all its tests
    unittest.TextTestRunner().run(suite())
