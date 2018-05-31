import time
from twisted.trial import unittest
import logging
from twisted.internet.task import Clock
from twisted.internet import defer
import lbrynet.dht.protocol
import lbrynet.dht.contact
from lbrynet.dht.error import TimeoutError
from lbrynet.dht.node import Node, rpcmethod
from mock_transport import listenUDP, resolve

log = logging.getLogger()


class KademliaProtocolTest(unittest.TestCase):
    """ Test case for the Protocol class """

    udpPort = 9182

    def setUp(self):
        self._reactor = Clock()
        self.node = Node(node_id='1' * 48, udpPort=self.udpPort, externalIP="127.0.0.1", listenUDP=listenUDP,
                         resolve=resolve, clock=self._reactor, callLater=self._reactor.callLater)
        self.remote_node = Node(node_id='2' * 48, udpPort=self.udpPort, externalIP="127.0.0.2", listenUDP=listenUDP,
                                resolve=resolve, clock=self._reactor, callLater=self._reactor.callLater)
        self.remote_contact = self.node.contact_manager.make_contact('2' * 48, '127.0.0.2', 9182, self.node._protocol)
        self.us_from_them = self.remote_node.contact_manager.make_contact('1' * 48, '127.0.0.1', 9182,
                                                                          self.remote_node._protocol)
        self.node.start_listening()
        self.remote_node.start_listening()

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.node.stop()
        yield self.remote_node.stop()
        del self._reactor

    @defer.inlineCallbacks
    def testReactor(self):
        """ Tests if the reactor can start/stop the protocol correctly """

        d = defer.Deferred()
        self._reactor.callLater(1, d.callback, True)
        self._reactor.advance(1)
        result = yield d
        self.assertTrue(result)

    @defer.inlineCallbacks
    def testRPCTimeout(self):
        """ Tests if a RPC message sent to a dead remote node times out correctly """
        yield self.remote_node.stop()
        self._reactor.pump([1 for _ in range(10)])
        self.node.addContact(self.remote_contact)

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
        self.failIf(self.remote_contact not in self.node.contacts,
                    'Contact not added to fake node (error in test code)')
        self.node.start_listening()

        # Run the PING RPC (which should raise a timeout error)
        df = self.remote_contact.ping()

        def check_timeout(err):
            self.assertEqual(err.type, TimeoutError)

        df.addErrback(check_timeout)

        def reset_values():
            self.node.ping = real_ping
            lbrynet.dht.constants.rpcTimeout = real_timeout
            lbrynet.dht.constants.rpcAttempts = real_attempts

        # See if the contact was removed due to the timeout
        def check_removed_contact():
            self.failIf(self.remote_contact in self.node.contacts,
                        'Contact was not removed after RPC timeout; check exception types.')

        df.addCallback(lambda _: reset_values())

        # Stop the reactor if a result arrives (timeout or not)
        df.addCallback(lambda _: check_removed_contact())
        self._reactor.pump([1 for _ in range(20)])

    @defer.inlineCallbacks
    def testRPCRequest(self):
        """ Tests if a valid RPC request is executed and responded to correctly """

        yield self.node.addContact(self.remote_contact)

        self.error = None

        def handleError(f):
            self.error = 'An RPC error occurred: %s' % f.getErrorMessage()

        def handleResult(result):
            expectedResult = 'pong'
            if result != expectedResult:
                self.error = 'Result from RPC is incorrect; expected "%s", got "%s"' \
                             % (expectedResult, result)

        # Simulate the RPC
        df = self.remote_contact.ping()
        df.addCallback(handleResult)
        df.addErrback(handleError)

        self._reactor.advance(2)
        yield df

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

        self.assertRaises(AttributeError, getattr, self.remote_contact, "not_a_rpc_function")

    def testRPCRequestArgs(self):
        """ Tests if an RPC requiring arguments is executed correctly """

        self.node.addContact(self.remote_contact)
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
        df = self.remote_contact.ping()
        df.addCallback(handleResult)
        df.addErrback(handleError)
        self._reactor.pump([1 for _ in range(10)])
        self.failIf(self.error, self.error)
        # The list of sent RPC messages should be empty at this stage
        self.failUnlessEqual(len(self.node._protocol._sentMessages), 0,
                             'The protocol is still waiting for a RPC result, '
                             'but the transaction is already done!')

    @defer.inlineCallbacks
    def testDetectProtocolVersion(self):
        original_findvalue = self.remote_node.findValue
        fake_blob = str("AB" * 48).decode('hex')

        @rpcmethod
        def findValue(contact, key):
            result = original_findvalue(contact, key)
            result.pop('protocolVersion')
            return result

        self.assertEquals(self.remote_contact.protocolVersion, 1)

        self.remote_node.findValue = findValue
        d = self.remote_contact.findValue(fake_blob)
        self._reactor.advance(3)
        find_value_response = yield d
        self.assertEquals(self.remote_contact.protocolVersion, 0)
        self.assertTrue('protocolVersion' not in find_value_response)

        self.remote_node.findValue = original_findvalue
        d = self.remote_contact.findValue(fake_blob)
        self._reactor.advance(3)
        find_value_response = yield d
        self.assertEquals(self.remote_contact.protocolVersion, 1)
        self.assertTrue('protocolVersion' not in find_value_response)

        self.remote_node.findValue = findValue
        d = self.remote_contact.findValue(fake_blob)
        self._reactor.advance(3)
        find_value_response = yield d
        self.assertEquals(self.remote_contact.protocolVersion, 0)
        self.assertTrue('protocolVersion' not in find_value_response)

    @defer.inlineCallbacks
    def testStoreToPre_0_20_0_Node(self):

        self.remote_node._protocol._protocolVersion = 0

        def _dont_migrate(contact, method, *args):
            return args, {}

        self.remote_node._protocol._migrate_incoming_rpc_args = _dont_migrate

        original_findvalue = self.remote_node.findValue
        original_store = self.remote_node.store

        @rpcmethod
        def findValue(contact, key):
            result = original_findvalue(contact, key)
            if 'protocolVersion' in result:
                result.pop('protocolVersion')
            return result

        @rpcmethod
        def store(contact, key, value, originalPublisherID=None, self_store=False, **kwargs):
            self.assertTrue(len(key) == 48)
            self.assertSetEqual(set(value.keys()), {'token', 'lbryid', 'port'})
            self.assertFalse(self_store)
            self.assertDictEqual(kwargs, {})
            return original_store(   # pylint: disable=too-many-function-args
                contact, key, value['token'], value['port'], originalPublisherID, 0
            )

        self.assertEquals(self.remote_contact.protocolVersion, 1)

        self.remote_node.findValue = findValue
        self.remote_node.store = store

        fake_blob = str("AB" * 48).decode('hex')

        d = self.remote_contact.findValue(fake_blob)
        self._reactor.advance(3)
        find_value_response = yield d
        self.assertEquals(self.remote_contact.protocolVersion, 0)
        self.assertTrue('protocolVersion' not in find_value_response)
        token = find_value_response['token']
        d = self.remote_contact.store(fake_blob, token, 3333, self.node.node_id, 0)
        self._reactor.advance(3)
        response = yield d
        self.assertEquals(response, "OK")
        self.assertEquals(self.remote_contact.protocolVersion, 0)
        self.assertTrue(self.remote_node._dataStore.hasPeersForBlob(fake_blob))
        self.assertEquals(len(self.remote_node._dataStore.getStoringContacts()), 1)

    @defer.inlineCallbacks
    def testStoreFromPre_0_20_0_Node(self):

        self.remote_node._protocol._protocolVersion = 0

        def _dont_migrate(contact, method, *args):
            return args

        self.remote_node._protocol._migrate_outgoing_rpc_args = _dont_migrate

        us_from_them = self.remote_node.contact_manager.make_contact('1' * 48, '127.0.0.1', self.udpPort,
                                                                self.remote_node._protocol)

        fake_blob = str("AB" * 48).decode('hex')

        d = us_from_them.findValue(fake_blob)
        self._reactor.advance(3)
        find_value_response = yield d
        self.assertEquals(self.remote_contact.protocolVersion, 0)
        self.assertTrue('protocolVersion' not in find_value_response)
        token = find_value_response['token']
        us_from_them.update_protocol_version(0)
        d = self.remote_node._protocol.sendRPC(
            us_from_them, "store", (fake_blob, {'lbryid': self.remote_node.node_id, 'token': token, 'port': 3333})
        )
        self._reactor.advance(3)
        response = yield d
        self.assertEquals(response, "OK")
        self.assertEquals(self.remote_contact.protocolVersion, 0)
        self.assertTrue(self.node._dataStore.hasPeersForBlob(fake_blob))
        self.assertEquals(len(self.node._dataStore.getStoringContacts()), 1)
        self.assertIs(self.node._dataStore.getStoringContacts()[0], self.remote_contact)
