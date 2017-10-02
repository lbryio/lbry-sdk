#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive

import time
import unittest

from twisted.internet import defer
from twisted.python import failure
import twisted.internet.selectreactor
from twisted.internet.protocol import DatagramProtocol

import lbrynet.dht.protocol
import lbrynet.dht.contact
import lbrynet.dht.constants
import lbrynet.dht.msgtypes
from lbrynet.dht.node import rpcmethod


class FakeNode(object):
    """ A fake node object implementing some RPC and non-RPC methods to 
    test the Kademlia protocol's behaviour
    """
    def __init__(self, id):
        self.id = id
        self.contacts = []
        
    @rpcmethod
    def ping(self):
        return 'pong'
    
    def pingNoRPC(self):
        return 'pong'
    
    @rpcmethod
    def echo(self, value):
        return value
    
    def addContact(self, contact):
        self.contacts.append(contact)
    
    def removeContact(self, contact):
        self.contacts.remove(contact)

    def indirectPingContact(self, protocol, contact):
        """ Pings the given contact (using the specified KademliaProtocol
        object, not the direct Contact API), and removes the contact
        on a timeout """
        df = protocol.sendRPC(contact, 'ping', {})
        def handleError(f):
            if f.check(lbrynet.dht.protocol.TimeoutError):
                self.removeContact(contact)
                return f
            else:
                # This is some other error
                return f
        df.addErrback(handleError)
        return df

class ClientDatagramProtocol(lbrynet.dht.protocol.KademliaProtocol):
    data = ''
    msgID = ''
    destination = ('127.0.0.1', 9182)
    
    def __init__(self):
        lbrynet.dht.protocol.KademliaProtocol.__init__(self, None)

    def startProtocol(self):
        self.sendDatagram()
    
    def sendDatagram(self):
        if len(self.data):
            self._send(self.data, self.msgID, self.destination)
            

        

class KademliaProtocolTest(unittest.TestCase):
    """ Test case for the Protocol class """
    def setUp(self):
        del lbrynet.dht.protocol.reactor
        lbrynet.dht.protocol.reactor = twisted.internet.selectreactor.SelectReactor()
        self.node = FakeNode('node1')
        self.protocol = lbrynet.dht.protocol.KademliaProtocol(self.node)

    def testReactor(self):
        """ Tests if the reactor can start/stop the protocol correctly """
        lbrynet.dht.protocol.reactor.listenUDP(0, self.protocol)
        lbrynet.dht.protocol.reactor.callLater(0, lbrynet.dht.protocol.reactor.stop)
        lbrynet.dht.protocol.reactor.run()

    def testRPCTimeout(self):
        """ Tests if a RPC message sent to a dead remote node times out correctly """
        deadContact = lbrynet.dht.contact.Contact('node2', '127.0.0.1', 9182, self.protocol)
        self.node.addContact(deadContact)
        # Make sure the contact was added
        self.failIf(deadContact not in self.node.contacts, 'Contact not added to fake node (error in test code)')
        # Set the timeout to 0 for testing
        tempTimeout = lbrynet.dht.constants.rpcTimeout
        lbrynet.dht.constants.rpcTimeout = 0
        lbrynet.dht.protocol.reactor.listenUDP(0, self.protocol)
        # Run the PING RPC (which should timeout)
        df = self.node.indirectPingContact(self.protocol, deadContact)
        # Stop the reactor if a result arrives (timeout or not)
        df.addBoth(lambda _: lbrynet.dht.protocol.reactor.stop())
        lbrynet.dht.protocol.reactor.run()
        # See if the contact was removed due to the timeout
        self.failIf(deadContact in self.node.contacts, 'Contact was not removed after RPC timeout; check exception types.')
        # Restore the global timeout
        lbrynet.dht.constants.rpcTimeout = tempTimeout
        
    def testRPCRequest(self):
        """ Tests if a valid RPC request is executed and responded to correctly """
        remoteContact = lbrynet.dht.contact.Contact('node2', '127.0.0.1', 9182, self.protocol)
        self.node.addContact(remoteContact)
        self.error = None
        def handleError(f):
            self.error = 'An RPC error occurred: %s' % f.getErrorMessage()
        def handleResult(result):
            expectedResult = 'pong'
            if result != expectedResult:
                self.error = 'Result from RPC is incorrect; expected "%s", got "%s"' % (expectedResult, result)
        # Publish the "local" node on the network    
        lbrynet.dht.protocol.reactor.listenUDP(9182, self.protocol)
        # Simulate the RPC
        df = remoteContact.ping()
        df.addCallback(handleResult)
        df.addErrback(handleError)
        df.addBoth(lambda _: lbrynet.dht.protocol.reactor.stop())
        lbrynet.dht.protocol.reactor.run()
        self.failIf(self.error, self.error)
        # The list of sent RPC messages should be empty at this stage
        self.failUnlessEqual(len(self.protocol._sentMessages), 0, 'The protocol is still waiting for a RPC result, but the transaction is already done!')

    def testRPCAccess(self):
        """ Tests invalid RPC requests
        
        Verifies that a RPC request for an existing but unpublished
        method is denied, and that the associated (remote) exception gets
        raised locally """
        remoteContact = lbrynet.dht.contact.Contact('node2', '127.0.0.1', 9182, self.protocol)
        self.node.addContact(remoteContact)
        self.error = None
        def handleError(f):
            try:
                f.raiseException()
            except AttributeError, e:
                # This is the expected outcome since the remote node did not publish the method
                self.error = None
            except Exception, e:
                self.error = 'The remote method failed, but the wrong exception was raised; expected AttributeError, got %s' % type(e)
                
        def handleResult(result):
            self.error = 'The remote method executed successfully, returning: "%s"; this RPC should not have been allowed.' % result
        # Publish the "local" node on the network    
        lbrynet.dht.protocol.reactor.listenUDP(9182, self.protocol)
        # Simulate the RPC
        df = remoteContact.pingNoRPC()
        df.addCallback(handleResult)
        df.addErrback(handleError)
        df.addBoth(lambda _: lbrynet.dht.protocol.reactor.stop())
        lbrynet.dht.protocol.reactor.run()
        self.failIf(self.error, self.error)
        # The list of sent RPC messages should be empty at this stage
        self.failUnlessEqual(len(self.protocol._sentMessages), 0, 'The protocol is still waiting for a RPC result, but the transaction is already done!')

    def testRPCRequestArgs(self):
        """ Tests if an RPC requiring arguments is executed correctly """
        remoteContact = lbrynet.dht.contact.Contact('node2', '127.0.0.1', 9182, self.protocol)
        self.node.addContact(remoteContact)
        self.error = None
        def handleError(f):
            self.error = 'An RPC error occurred: %s' % f.getErrorMessage()
        def handleResult(result):
            expectedResult = 'This should be returned.'
            if result != 'This should be returned.':
                self.error = 'Result from RPC is incorrect; expected "%s", got "%s"' % (expectedResult, result)
        # Publish the "local" node on the network    
        lbrynet.dht.protocol.reactor.listenUDP(9182, self.protocol)
        # Simulate the RPC
        df = remoteContact.echo('This should be returned.')
        df.addCallback(handleResult)
        df.addErrback(handleError)
        df.addBoth(lambda _: lbrynet.dht.protocol.reactor.stop())
        lbrynet.dht.protocol.reactor.run()
        self.failIf(self.error, self.error)
        # The list of sent RPC messages should be empty at this stage
        self.failUnlessEqual(len(self.protocol._sentMessages), 0, 'The protocol is still waiting for a RPC result, but the transaction is already done!')


def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(KademliaProtocolTest))
    return suite

if __name__ == '__main__':
    # If this module is executed from the commandline, run all its tests
    unittest.TextTestRunner().run(suite())
