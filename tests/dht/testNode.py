#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive

import hashlib
import unittest
import struct

import lbrynet.dht.node
import lbrynet.dht.constants
import lbrynet.dht.datastore

class NodeIDTest(unittest.TestCase):
    """ Test case for the Node class's ID """
    def setUp(self):
        self.node = lbrynet.dht.node.Node()

    def testAutoCreatedID(self):
        """ Tests if a new node has a valid node ID """
        self.failUnlessEqual(type(self.node.id), str, 'Node does not have a valid ID')
        self.failUnlessEqual(len(self.node.id), 20, 'Node ID length is incorrect! Expected 160 bits, got %d bits.' % (len(self.node.id)*8))

    def testUniqueness(self):
        """ Tests the uniqueness of the values created by the NodeID generator 
        """
        generatedIDs = []
        for i in range(100):
            newID = self.node._generateID()
            # ugly uniqueness test
            self.failIf(newID in generatedIDs, 'Generated ID #%d not unique!' % (i+1))
            generatedIDs.append(newID)
    
    def testKeyLength(self):
        """ Tests the key Node ID key length """
        for i in range(20):
            id = self.node._generateID()
            # Key length: 20 bytes == 160 bits
            self.failUnlessEqual(len(id), 20, 'Length of generated ID is incorrect! Expected 160 bits, got %d bits.' % (len(id)*8))


class NodeDataTest(unittest.TestCase):
    """ Test case for the Node class's data-related functions """
    def setUp(self):
        import lbrynet.dht.contact
        h = hashlib.sha1()
        h.update('test')
        self.node = lbrynet.dht.node.Node()
        self.contact = lbrynet.dht.contact.Contact(h.digest(), '127.0.0.1', 12345, self.node._protocol)
        self.token = self.node.make_token(self.contact.compact_ip())
        self.cases = []
        for i in xrange(5):
            h.update(str(i))
            self.cases.append((h.digest(), 5000+2*i))
            self.cases.append((h.digest(), 5001+2*i))
            #(('a', 'hello there\nthis is a test'),
            #         ('b', unicode('jasdklfjklsdj;f2352352ljklzsdlkjkasf\ndsjklafsd')),
            #         ('e', 123),
            #         ('f', [('this', 'is', 1), {'complex': 'data entry'}]),
            #         ('aMuchLongerKeyThanAnyOfThePreviousOnes', 'some data'))
        
    def testStore(self):

        def check_val_in_result(r, peer_info):
            self.failUnless

        """ Tests if the node can store (and privately retrieve) some data """
        for key, value in self.cases:
            self.node.store(key, {'port': value, 'bbid': self.contact.id, 'token': self.token}, self.contact.id, _rpcNodeContact=self.contact)
        for key, value in self.cases:
            expected_result = self.contact.compact_ip() + str(struct.pack('>H', value))  + self.contact.id
            self.failUnless(self.node._dataStore.hasPeersForBlob(key), 'Stored key not found in node\'s DataStore: "%s"' % key)
            self.failUnless(expected_result in self.node._dataStore.getPeersForBlob(key), 'Stored val not found in node\'s DataStore: key:"%s" port:"%s" %s' % (key, value, self.node._dataStore.getPeersForBlob(key)))

class NodeContactTest(unittest.TestCase):
    """ Test case for the Node class's contact management-related functions """
    def setUp(self):
        self.node = lbrynet.dht.node.Node()
    
    def testAddContact(self):
        """ Tests if a contact can be added and retrieved correctly """
        import lbrynet.dht.contact
        # Create the contact
        h = hashlib.sha1()
        h.update('node1')
        contactID = h.digest()
        contact = lbrynet.dht.contact.Contact(contactID, '127.0.0.1', 91824, self.node._protocol)
        # Now add it...
        self.node.addContact(contact)
        # ...and request the closest nodes to it using FIND_NODE
        closestNodes = self.node._routingTable.findCloseNodes(contactID, lbrynet.dht.constants.k)
        self.failUnlessEqual(len(closestNodes), 1, 'Wrong amount of contacts returned; expected 1, got %d' % len(closestNodes))
        self.failUnless(contact in closestNodes, 'Added contact not found by issueing _findCloseNodes()')
        
    def testAddSelfAsContact(self):
        """ Tests the node's behaviour when attempting to add itself as a contact """
        import lbrynet.dht.contact
        # Create a contact with the same ID as the local node's ID
        contact = lbrynet.dht.contact.Contact(self.node.id, '127.0.0.1', 91824, None)
        # Now try to add it
        self.node.addContact(contact)
        # ...and request the closest nodes to it using FIND_NODE
        closestNodes = self.node._routingTable.findCloseNodes(self.node.id, lbrynet.dht.constants.k)
        self.failIf(contact in closestNodes, 'Node added itself as a contact')


#class NodeLookupTest(unittest.TestCase):
#    """ Test case for the Node class's iterative node lookup algorithm """
#    def setUp(self):
#        import entangled.kademlia.contact
#        self.node = entangled.kademlia.node.Node()
#        self.remoteNodes = []
#        for i in range(10):
#            remoteNode = entangled.kademlia.node.Node()
#           remoteContact = entangled.kademlia.contact.Contact(remoteNode.id, '127.0.0.1', 91827+i, self.node._protocol)
#           self.remoteNodes.append(remoteNode)
#            self.node.addContact(remoteContact)
            
            
#    def testIterativeFindNode(self):
#        """ Ugly brute-force test to see if the iterative node lookup algorithm runs without failing """
#        import entangled.kademlia.protocol
#        entangled.kademlia.protocol.reactor.listenUDP(91826, self.node._protocol)
#        for i in range(10):
#            entangled.kademlia.protocol.reactor.listenUDP(91827+i, self.remoteNodes[i]._protocol)
#        df = self.node.iterativeFindNode(self.node.id)
#        df.addBoth(lambda _: entangled.kademlia.protocol.reactor.stop())
#        entangled.kademlia.protocol.reactor.run()


""" Some scaffolding for the NodeLookupTest class. Allows isolated node testing by simulating remote node responses"""
from twisted.internet import protocol, defer, selectreactor
from lbrynet.dht.msgtypes import ResponseMessage


class FakeRPCProtocol(protocol.DatagramProtocol):
    def __init__(self):
        self.reactor = selectreactor.SelectReactor() 
        self.testResponse = None
        self.network = None

    def createNetwork(self, contactNetwork):
         """ set up a list of contacts together with their closest contacts
         @param contactNetwork: a sequence of tuples, each containing a contact together with its closest 
         contacts:  C{(<contact>, <closest contact 1, ...,closest contact n>)}
         """
         self.network = contactNetwork
       
    """ Fake RPC protocol; allows entangled.kademlia.contact.Contact objects to "send" RPCs """
    def sendRPC(self, contact, method, args, rawResponse=False):
        #print method + " " + str(args)
        
        if method == "findNode":        
            # get the specific contacts closest contacts
            closestContacts = []
            #print "contact" + contact.id
            for contactTuple in self.network:
                #print contactTuple[0].id
                if contact == contactTuple[0]:
                    # get the list of closest contacts for this contact
                    closestContactsList = contactTuple[1]
                    #print "contact" + contact.id
                
            # Pack the closest contacts into a ResponseMessage 
            for closeContact in closestContactsList:
                #print closeContact.id
                closestContacts.append((closeContact.id, closeContact.address, closeContact.port))
            message = ResponseMessage("rpcId", contact.id, closestContacts)
                    
            df = defer.Deferred()
            df.callback((message,(contact.address, contact.port)))
            return df
        elif method == "findValue":
            for contactTuple in self.network:
                if contact == contactTuple[0]:
                    # Get the data stored by this remote contact
                    dataDict = contactTuple[2]
                    dataKey = dataDict.keys()[0]
                    data = dataDict.get(dataKey)
                    
                    # Check if this contact has the requested value
                    if dataKey == args[0]:
                        # Return the data value
                        response = dataDict
                        
                        print "data found at contact: " + contact.id
                    else:
                        # Return the closest contact to the requested data key
                        print "data not found at contact: " + contact.id
                        closeContacts = contactTuple[1]
                        closestContacts = []
                        for closeContact in closeContacts:
                            closestContacts.append((closeContact.id, closeContact.address, closeContact.port))
                            response = closestContacts
                                        
            # Create the response message
            message = ResponseMessage("rpcId", contact.id, response)
            df = defer.Deferred()
            df.callback((message,(contact.address, contact.port)))
            return df

    def _send(self, data, rpcID, address):
        """ fake sending data """
        
            

class NodeLookupTest(unittest.TestCase):
    """ Test case for the Node class's iterativeFind node lookup algorithm """
       
    def setUp(self):
                        
        # create a fake protocol to imitate communication with other nodes
        self._protocol = FakeRPCProtocol()
        
        # Note: The reactor is never started for this test. All deferred calls run sequentially, 
        # since there is no asynchronous network communication
        
        # create the node to be tested in isolation
        self.node = lbrynet.dht.node.Node(None, 4000, None, None, self._protocol)
        
        self.updPort = 81173
        
        # create a dummy reactor 
        #self._protocol.reactor.listenUDP(self.updPort, self._protocol)
        
        self.contactsAmount = 80
        # set the node ID manually for testing
        self.node.id = '12345678901234567800'
        
        # Reinitialise the routing table
        self.node._routingTable = lbrynet.dht.routingtable.OptimizedTreeRoutingTable(self.node.id)
       
        # create 160 bit node ID's for test purposes
        self.testNodeIDs = []
        #idNum = long(self.node.id.encode('hex'), 16)
        idNum = int(self.node.id)
        for i in range(self.contactsAmount):
            # create the testNodeIDs in ascending order, away from the actual node ID, with regards to the distance metric 
            self.testNodeIDs.append(idNum + i + 1)

        # generate contacts
        self.contacts = []
        for i in range(self.contactsAmount):
            contact = lbrynet.dht.contact.Contact(str(self.testNodeIDs[i]), "127.0.0.1", self.updPort + i + 1, self._protocol)
            self.contacts.append(contact)
            
        # create the network of contacts in format: (contact, closest contacts)        
        contactNetwork = ((self.contacts[0], self.contacts[8:15]),
                          (self.contacts[1], self.contacts[16:23]),
                          (self.contacts[2], self.contacts[24:31]),
                          (self.contacts[3], self.contacts[32:39]),
                          (self.contacts[4], self.contacts[40:47]),
                          (self.contacts[5], self.contacts[48:55]),
                          (self.contacts[6], self.contacts[56:63]),
                          (self.contacts[7], self.contacts[64:71]),
                          (self.contacts[8], self.contacts[72:79]),
                          (self.contacts[40], self.contacts[41:48]),
                          (self.contacts[41], self.contacts[41:48]),
                          (self.contacts[42], self.contacts[41:48]),
                          (self.contacts[43], self.contacts[41:48]),
                          (self.contacts[44], self.contacts[41:48]),
                          (self.contacts[45], self.contacts[41:48]),
                          (self.contacts[46], self.contacts[41:48]),
                          (self.contacts[47], self.contacts[41:48]),
                          (self.contacts[48], self.contacts[41:48]),
                          (self.contacts[50], self.contacts[0:7]),
                          (self.contacts[51], self.contacts[8:15]),
                          (self.contacts[52], self.contacts[16:23]))

        contacts_with_datastores = []

        for contact_tuple in contactNetwork:
            contacts_with_datastores.append((contact_tuple[0], contact_tuple[1], lbrynet.dht.datastore.DictDataStore()))
        
        self._protocol.createNetwork(contacts_with_datastores)
        
    def testNodeBootStrap(self):
        """  Test bootstrap with the closest possible contacts """
                     
        df = self.node._iterativeFind(self.node.id, self.contacts[0:8])
        # Set the expected result
        expectedResult = []   
        
        for item in self.contacts[0:6]:
                expectedResult.append(item.id)
                #print item.id
        
        # Get the result from the deferred
        activeContacts = df.result
              
        
        # Check the length of the active contacts
        self.failUnlessEqual(activeContacts.__len__(), expectedResult.__len__(), \
                                 "More active contacts should exist, there should be %d contacts" %expectedResult.__len__())
            
        
        # Check that the received active contacts are the same as the input contacts
        self.failUnlessEqual(activeContacts, expectedResult, \
                                 "Active should only contain the closest possible contacts which were used as input for the boostrap")
    
#    def testFindingCloserNodes(self):
#        """ Test discovery of closer contacts""" 
#               
#        # Use input contacts that have knowledge of closer contacts,
#        df = self.node._iterativeFind(self.node.id, self.contacts[50:53])
#        #set the expected result
#        expectedResult = []   
#        #print "############ Expected Active contacts #################"
#        for item in self.contacts[0:9]:
#                expectedResult.append(item.id)
#                #print item.id
#        #print "#######################################################"
#        
#        # Get the result from the deferred
#        activeContacts = df.result
#        
#        #print "!!!!!!!!!!! Receieved Active contacts !!!!!!!!!!!!!!!"
#        #for item in activeContacts:
#        #    print item.id
#        #print "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
#        
#        # Check the length of the active contacts
#        self.failUnlessEqual(activeContacts.__len__(), expectedResult.__len__(), \
#                                 "Length of received active contacts not as expected, should be %d" %expectedResult.__len__())
#            
#        
#        # Check that the received active contacts are now closer to this node
#        self.failUnlessEqual(activeContacts, expectedResult, \
#                                 "Active contacts should now only contain the closest possible contacts")
    
    
        
#    def testIterativeStore(self):
#        """ test storing values """
#
#        # create the network of contacts in format: (contact, closest contacts)
#        contactNetwork = ((self.contacts[0], self.contacts[0:8]),
#                          (self.contacts[1], self.contacts[0:8]),
#                          (self.contacts[2], self.contacts[0:8]),
#                          (self.contacts[3], self.contacts[0:8]),
#                          (self.contacts[4], self.contacts[0:8]),
#                          (self.contacts[5], self.contacts[0:8]),
#                          (self.contacts[6], self.contacts[0:8]),
#                          (self.contacts[7], self.contacts[0:8]),
#                          (self.contacts[8], self.contacts[0:8]),
#                          (self.contacts[40], self.contacts[41:48]),
#                          (self.contacts[41], self.contacts[41:48]),
#                          (self.contacts[42], self.contacts[41:48]),
#                          (self.contacts[43], self.contacts[41:48]),
#                          (self.contacts[44], self.contacts[41:48]),
#                          (self.contacts[45], self.contacts[41:48]),
#                          (self.contacts[46], self.contacts[41:48]),
#                          (self.contacts[47], self.contacts[41:48]),
#                          (self.contacts[48], self.contacts[41:48]))
#        contacts_with_datastores = []
#
#        for contact_tuple in contactNetwork:
#            contacts_with_datastores.append((contact_tuple[0], contact_tuple[1], lbrynet.dht.datastore.DictDataStore()))
#
#        self._protocol.createNetwork(contacts_with_datastores)
#
#
#        #self._protocol.createNetwork(contactNetwork)
#
#
#        # Test storing a value that has an hash id close to the known contacts
#        # The value should only be stored at those nodes
#        value = 'value'
#        valueID = self.contacts[40].id
#
#        # Manually populate the routing table with contacts that have ID's close to the valueID
#        for contact in self.contacts[40:48]:
#            self.node.addContact(contact)
#
#        # Manually populate the routing table with contacts that have ID's far away from the valueID
#        for contact in self.contacts[0:8]:
#            self.node.addContact(contact)
#
#        # Store the value
#        df = self.node.announceHaveBlob(valueID, value)
#
#        storageNodes = df.result
#
#        storageNodeIDs = []
#        for item in storageNodes:
#            storageNodeIDs.append(item.id)
#        storageNodeIDs.sort()
#        #print storageNodeIDs
#
#        expectedIDs = []
#        for item in self.contacts[40:43]:
#            expectedIDs.append(item.id)
#        #print expectedIDs
#
#        #print '#### storage nodes ####'
#        #for node in storageNodes:
#        #    print node.id
#
#
#        # check that the value has been stored at nodes with ID's close to the valueID
#        self.failUnlessEqual(storageNodeIDs, expectedIDs, \
#                                 "Value not stored at nodes with ID's close to the valueID")
#
#    def testFindValue(self):
#        # create test values using the contact ID as the key
#        testValues = ({self.contacts[0].id: "some test data"},
#                      {self.contacts[1].id: "some more test data"},
#                      {self.contacts[8].id: "and more data"}
#                      )
#        
#              
#        # create the network of contacts in format: (contact, closest contacts, values)        
#        contactNetwork = ((self.contacts[0], self.contacts[0:6], testValues[0]),
#                          (self.contacts[1], self.contacts[0:6], testValues[1]),
#                          (self.contacts[2], self.contacts[0:6], {'2':'2'}),
#                          (self.contacts[3], self.contacts[0:6], {'4':'5'}),
#                          (self.contacts[4], self.contacts[0:6], testValues[2]),
#                          (self.contacts[5], self.contacts[0:6], {'2':'2'}),
#                          (self.contacts[6], self.contacts[0:6], {'2':'2'}))
#        
#        self._protocol.createNetwork(contactNetwork)
#        
#        # Initialise the routing table with some contacts
#        for contact in self.contacts[0:4]:
#            self.node.addContact(contact)
#        
#        # Initialise the node with some known contacts
#        #self.node._iterativeFind(self.node.id, self.contacts[0:3])
#        
#        df = self.node.iterativeFindValue(testValues[1].keys()[0])
#        
#        resultDict = df.result
#        keys = resultDict.keys()
#        
#        for key in keys:
#            if key == 'closestNodeNoValue':
#                print "closest contact without data " + " " + resultDict.get(key).id
#            else:
#                print "data key :" + key + "; " + "data: " + resultDict.get(key)
      
        
        
           
                      

def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(NodeIDTest))
    suite.addTest(unittest.makeSuite(NodeDataTest))
    suite.addTest(unittest.makeSuite(NodeContactTest))
    suite.addTest(unittest.makeSuite(NodeLookupTest))
    return suite

if __name__ == '__main__':
    # If this module is executed from the commandline, run all its tests
    unittest.TextTestRunner().run(suite())
