import time
import unittest
from twisted.internet.task import Clock
from twisted.internet import defer, threads
import lbrynet.dht.protocol
import lbrynet.dht.contact
import lbrynet.dht.constants
import lbrynet.dht.msgtypes
from lbrynet.dht.error import TimeoutError
from lbrynet.dht.node import Node, rpcmethod
from lbrynet.tests.mocks import listenUDP, resolve
from lbrynet.core.call_later_manager import CallLaterManager

import logging

log = logging.getLogger()


class KademliaProtocolTest(unittest.TestCase):
    """ Test case for the Protocol class """

    udpPort = 9182

    def setUp(self):
        self._reactor = Clock()
        CallLaterManager.setup(self._reactor.callLater)
        self.node = Node(node_id='1' * 48, udpPort=self.udpPort, externalIP="127.0.0.1", listenUDP=listenUDP,
                         resolve=resolve, clock=self._reactor, callLater=self._reactor.callLater)

    def tearDown(self):
        CallLaterManager.stop()
        del self._reactor

    @defer.inlineCallbacks
    def testReactor(self):
        """ Tests if the reactor can start/stop the protocol correctly """

        d = defer.Deferred()
        self._reactor.callLater(1, d.callback, True)
        self._reactor.advance(1)
        result = yield d
        self.assertTrue(result)

    def testRPCTimeout(self):
        """ Tests if a RPC message sent to a dead remote node times out correctly """
        dead_node = Node(node_id='2' * 48, udpPort=self.udpPort, externalIP="127.0.0.2", listenUDP=listenUDP,
                         resolve=resolve, clock=self._reactor, callLater=self._reactor.callLater)
        dead_node.start_listening()
        dead_node.stop()
        self._reactor.pump([1 for _ in range(10)])
        dead_contact = lbrynet.dht.contact.Contact('2' * 48, '127.0.0.2', 9182, self.node._protocol)
        self.node.addContact(dead_contact)

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
        # Make sure the contact was added
        self.failIf(dead_contact not in self.node.contacts,
                    'Contact not added to fake node (error in test code)')
        self.node.start_listening()

        # Run the PING RPC (which should raise a timeout error)
        df = self.node._protocol.sendRPC(dead_contact, 'ping', {})

        def check_timeout(err):
            self.assertEqual(err.type, TimeoutError)

        df.addErrback(check_timeout)

        def reset_values():
            self.node.ping = real_ping
            lbrynet.dht.constants.rpcTimeout = real_timeout
            lbrynet.dht.constants.rpcAttempts = real_attempts

        # See if the contact was removed due to the timeout
        def check_removed_contact():
            self.failIf(dead_contact in self.node.contacts,
                        'Contact was not removed after RPC timeout; check exception types.')

        df.addCallback(lambda _: reset_values())

        # Stop the reactor if a result arrives (timeout or not)
        df.addCallback(lambda _: check_removed_contact())
        self._reactor.pump([1 for _ in range(20)])

    def testRPCRequest(self):
        """ Tests if a valid RPC request is executed and responded to correctly """

        remote_node = Node(node_id='2' * 48, udpPort=self.udpPort, externalIP="127.0.0.2", listenUDP=listenUDP,
                     resolve=resolve, clock=self._reactor, callLater=self._reactor.callLater)
        remote_node.start_listening()
        remoteContact = lbrynet.dht.contact.Contact('2' * 48, '127.0.0.2', 9182, self.node._protocol)
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
        self.node.start_listening()
        # Simulate the RPC
        df = remoteContact.ping()
        df.addCallback(handleResult)
        df.addErrback(handleError)

        for _ in range(10):
            self._reactor.advance(1)

        self.failIf(self.error, self.error)
        # The list of sent RPC messages should be empty at this stage
        self.failUnlessEqual(len(self.node._protocol._sentMessages), 0,
                             'The protocol is still waiting for a RPC result, '
                             'but the transaction is already done!')

    def testRPCAccess(self):
        """ Tests invalid RPC requests
        Verifies that a RPC request for an existing but unpublished
        method is denied, and that the associated (remote) exception gets
        raised locally """
        remote_node = Node(node_id='2' * 48, udpPort=self.udpPort, externalIP="127.0.0.2", listenUDP=listenUDP,
                           resolve=resolve, clock=self._reactor, callLater=self._reactor.callLater)
        remote_node.start_listening()
        remote_contact = lbrynet.dht.contact.Contact('2' * 48, '127.0.0.2', 9182, self.node._protocol)
        self.node.addContact(remote_contact)

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

        self.node.start_listening()
        self._reactor.pump([1 for _ in range(10)])
        # Simulate the RPC
        df = remote_contact.not_a_rpc_function()
        df.addCallback(handleResult)
        df.addErrback(handleError)
        self._reactor.pump([1 for _ in range(10)])
        self.failIf(self.error, self.error)
        # The list of sent RPC messages should be empty at this stage
        self.failUnlessEqual(len(self.node._protocol._sentMessages), 0,
                             'The protocol is still waiting for a RPC result, '
                             'but the transaction is already done!')

    def testRPCRequestArgs(self):
        """ Tests if an RPC requiring arguments is executed correctly """
        remote_node = Node(node_id='2' * 48, udpPort=self.udpPort, externalIP="127.0.0.2", listenUDP=listenUDP,
                           resolve=resolve, clock=self._reactor, callLater=self._reactor.callLater)
        remote_node.start_listening()
        remote_contact = lbrynet.dht.contact.Contact('2' * 48, '127.0.0.2', 9182, self.node._protocol)
        self.node.addContact(remote_contact)
        self.error = None

        def handleError(f):
            self.error = 'An RPC error occurred: %s' % f.getErrorMessage()

        def handleResult(result):
            expectedResult = 'pong'
            if result != expectedResult:
                self.error = 'Result from RPC is incorrect; expected "%s", got "%s"' % \
                             (expectedResult, result)

        # Publish the "local" node on the network
        self.node.start_listening()
        # Simulate the RPC
        df = remote_contact.ping()
        df.addCallback(handleResult)
        df.addErrback(handleError)
        self._reactor.pump([1 for _ in range(10)])
        self.failIf(self.error, self.error)
        # The list of sent RPC messages should be empty at this stage
        self.failUnlessEqual(len(self.node._protocol._sentMessages), 0,
                             'The protocol is still waiting for a RPC result, '
                             'but the transaction is already done!')
