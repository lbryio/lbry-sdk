import time
import unittest
import twisted.internet.selectreactor

import lbrynet.dht.protocol
import lbrynet.dht.contact
import lbrynet.dht.constants
import lbrynet.dht.msgtypes
from lbrynet.dht.error import TimeoutError
from lbrynet.dht.node import Node, rpcmethod


class KademliaProtocolTest(unittest.TestCase):
    """ Test case for the Protocol class """

    def setUp(self):
        del lbrynet.dht.protocol.reactor
        lbrynet.dht.protocol.reactor = twisted.internet.selectreactor.SelectReactor()
        self.node = Node(node_id='1' * 48, udpPort=9182, externalIP="127.0.0.1")
        self.protocol = lbrynet.dht.protocol.KademliaProtocol(self.node)

    def testReactor(self):
        """ Tests if the reactor can start/stop the protocol correctly """
        lbrynet.dht.protocol.reactor.listenUDP(0, self.protocol)
        lbrynet.dht.protocol.reactor.callLater(0, lbrynet.dht.protocol.reactor.stop)
        lbrynet.dht.protocol.reactor.run()

    def testRPCTimeout(self):
        """ Tests if a RPC message sent to a dead remote node times out correctly """

        @rpcmethod
        def fake_ping(*args, **kwargs):
            time.sleep(lbrynet.dht.constants.rpcTimeout + 1)
            return 'pong'

        real_ping = self.node.ping
        real_timeout = lbrynet.dht.constants.rpcTimeout
        real_attempts = lbrynet.dht.constants.rpcAttempts
        lbrynet.dht.constants.rpcAttempts = 1
        lbrynet.dht.constants.rpcTimeout = 1
        self.node.ping = fake_ping
        deadContact = lbrynet.dht.contact.Contact('2' * 48, '127.0.0.1', 9182, self.protocol)
        self.node.addContact(deadContact)
        # Make sure the contact was added
        self.failIf(deadContact not in self.node.contacts,
                    'Contact not added to fake node (error in test code)')
        lbrynet.dht.protocol.reactor.listenUDP(9182, self.protocol)

        # Run the PING RPC (which should raise a timeout error)
        df = self.protocol.sendRPC(deadContact, 'ping', {})

        def check_timeout(err):
            self.assertEqual(type(err), TimeoutError)

        df.addErrback(check_timeout)

        def reset_values():
            self.node.ping = real_ping
            lbrynet.dht.constants.rpcTimeout = real_timeout
            lbrynet.dht.constants.rpcAttempts = real_attempts

        # See if the contact was removed due to the timeout
        def check_removed_contact():
            self.failIf(deadContact in self.node.contacts,
                        'Contact was not removed after RPC timeout; check exception types.')

        df.addCallback(lambda _: reset_values())

        # Stop the reactor if a result arrives (timeout or not)
        df.addBoth(lambda _: lbrynet.dht.protocol.reactor.stop())
        df.addCallback(lambda _: check_removed_contact())
        lbrynet.dht.protocol.reactor.run()

    def testRPCRequest(self):
        """ Tests if a valid RPC request is executed and responded to correctly """
        remoteContact = lbrynet.dht.contact.Contact('2' * 48, '127.0.0.1', 9182, self.protocol)
        self.node.addContact(remoteContact)
        self.error = None

        def handleError(f):
            self.error = 'An RPC error occurred: %s' % f.getErrorMessage()

        def handleResult(result):
            expectedResult = 'pong'
            if result != expectedResult:
                self.error = 'Result from RPC is incorrect; expected "%s", got "%s"' \
                             % (expectedResult, result)

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
        self.failUnlessEqual(len(self.protocol._sentMessages), 0,
                             'The protocol is still waiting for a RPC result, '
                             'but the transaction is already done!')

    def testRPCAccess(self):
        """ Tests invalid RPC requests
        Verifies that a RPC request for an existing but unpublished
        method is denied, and that the associated (remote) exception gets
        raised locally """
        remoteContact = lbrynet.dht.contact.Contact('2' * 48, '127.0.0.1', 9182, self.protocol)
        self.node.addContact(remoteContact)
        self.error = None

        def handleError(f):
            try:
                f.raiseException()
            except AttributeError, e:
                # This is the expected outcome since the remote node did not publish the method
                self.error = None
            except Exception, e:
                self.error = 'The remote method failed, but the wrong exception was raised; ' \
                             'expected AttributeError, got %s' % type(e)

        def handleResult(result):
            self.error = 'The remote method executed successfully, returning: "%s"; ' \
                         'this RPC should not have been allowed.' % result

        # Publish the "local" node on the network
        lbrynet.dht.protocol.reactor.listenUDP(9182, self.protocol)
        # Simulate the RPC
        df = remoteContact.not_a_rpc_function()
        df.addCallback(handleResult)
        df.addErrback(handleError)
        df.addBoth(lambda _: lbrynet.dht.protocol.reactor.stop())
        lbrynet.dht.protocol.reactor.run()
        self.failIf(self.error, self.error)
        # The list of sent RPC messages should be empty at this stage
        self.failUnlessEqual(len(self.protocol._sentMessages), 0,
                             'The protocol is still waiting for a RPC result, '
                             'but the transaction is already done!')

    def testRPCRequestArgs(self):
        """ Tests if an RPC requiring arguments is executed correctly """
        remoteContact = lbrynet.dht.contact.Contact('2' * 48, '127.0.0.1', 9182, self.protocol)
        self.node.addContact(remoteContact)
        self.error = None

        def handleError(f):
            self.error = 'An RPC error occurred: %s' % f.getErrorMessage()

        def handleResult(result):
            expectedResult = 'pong'
            if result != expectedResult:
                self.error = 'Result from RPC is incorrect; expected "%s", got "%s"' % \
                             (expectedResult, result)

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
        self.failUnlessEqual(len(self.protocol._sentMessages), 0,
                             'The protocol is still waiting for a RPC result, '
                             'but the transaction is already done!')
