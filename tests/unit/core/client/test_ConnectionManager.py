import sys
import time
import logging

from lbrynet.core import log_support
from lbrynet.core.client.ConnectionManager import ConnectionManager
from lbrynet.core.client.ClientRequest import ClientRequest
from lbrynet.core.server.ServerProtocol import ServerProtocol
from lbrynet.core.RateLimiter import RateLimiter
from lbrynet.core.Peer import Peer
from lbrynet.core.PeerManager import PeerManager
from lbrynet.core.Error import ConnectionClosedBeforeResponseError, NoResponseError

from twisted.trial import unittest
from twisted.internet import defer, reactor, task
from twisted.internet.task import deferLater
from twisted.internet.protocol import Protocol, ServerFactory
from lbrynet import conf
from lbrynet.interfaces  import IQueryHandlerFactory, IQueryHandler, IRequestCreator

from zope.interface import implements

PEER_PORT = 5551
LOCAL_HOST = '127.0.0.1'

class MocDownloader(object):
    def insufficient_funds(self):
        pass

class MocRequestCreator(object):
    implements(IRequestCreator)
    def __init__(self, peers_to_return):
        self.peers_to_return = peers_to_return
        self.sent_request = False

    def send_next_request(self, peer, protocol):
        if self.sent_request is True:
            return defer.succeed(False)
        response_identifier = 'moc_request'
        r_dict = {'moc_request':0}
        request = ClientRequest(r_dict, response_identifier)
        d = protocol.add_request(request) # ClientRequest here
        d.addErrback(self.request_err, peer)
        d.addCallback(self.request_success)
        self.sent_request = True
        return defer.succeed(True)

    def request_success(self, suc):
        pass

    def request_err(self, err, peer):
        if isinstance(err.value, NoResponseError):
            return err

    def get_new_peers(self):
        return self.peers_to_return

class MocFunctionalQueryHandler(object):
    implements(IQueryHandler)

    def __init__(self, clock, is_good=True, is_delayed=False):
        self.query_identifiers = ['moc_request']
        self.is_good = is_good
        self.is_delayed = is_delayed
        self.clock = clock

    def register_with_request_handler(self, request_handler, peer):
        request_handler.register_query_handler(self, self.query_identifiers)

    def handle_queries(self, queries):
        if self.query_identifiers[0] in queries:
            if self.is_delayed:
                out = deferLater(self.clock, 10, lambda: {'moc_request':0})
                self.clock.advance(10)
                return out
            if self.is_good:
                return defer.succeed({'moc_request':0})
            else:
                return defer.succeed({'bad_request':0})
        else:
            return defer.succeed({})


class MocQueryHandlerFactory(object):
    implements(IQueryHandlerFactory)
    # is is_good, the query handler works as expectd,
    # is is_delayed, the query handler will delay its resposne
    def __init__(self, clock, is_good=True, is_delayed=False):
        self.is_good = is_good
        self.is_delayed = is_delayed
        self.clock = clock
    def build_query_handler(self):
        return MocFunctionalQueryHandler(self.clock, self.is_good, self.is_delayed)

    def get_primary_query_identifier(self):
        return 'moc_query'

    def get_description(self):
        return "This is a Moc Query"


class MocServerProtocolFactory(ServerFactory):
    protocol = ServerProtocol
    def __init__(self, clock, is_good=True, is_delayed=False, has_moc_query_handler=True):
        self.rate_limiter = RateLimiter()
        query_handler_factory = MocQueryHandlerFactory(clock, is_good, is_delayed)
        if has_moc_query_handler:
            self.query_handler_factories = {
                query_handler_factory.get_primary_query_identifier():query_handler_factory
            }
        else:
            self.query_handler_factories = {}
        self.peer_manager = PeerManager()


class TestIntegrationConnectionManager(unittest.TestCase):
    def setUp(self):

        conf.initialize_settings()

        self.TEST_PEER = Peer(LOCAL_HOST, PEER_PORT)
        self.downloader = MocDownloader()
        self.rate_limiter = RateLimiter()
        self.primary_request_creator = MocRequestCreator([self.TEST_PEER])
        self.connection_manager = ConnectionManager(self.downloader, self.rate_limiter,
                                                    [self.primary_request_creator], [])

        self.clock = task.Clock()
        self.connection_manager.callLater = self.clock.callLater
        self.connection_manager._start()
        self.server_port = None

    def tearDown(self):
        if self.server_port is not None:
            self.server_port.stopListening()
        self.connection_manager.stop()
        conf.settings = None

    @defer.inlineCallbacks
    def test_success(self):
        # test to see that if we setup a server, we get a connection
        self.server = MocServerProtocolFactory(self.clock)
        self.server_port = reactor.listenTCP(PEER_PORT, self.server, interface=LOCAL_HOST)
        yield self.connection_manager.manage(schedule_next_call=False)
        self.assertEqual(1, self.connection_manager.num_peer_connections())
        connection_made = yield self.connection_manager._peer_connections[self.TEST_PEER].factory.connection_was_made_deferred
        self.assertEqual(0, self.connection_manager.num_peer_connections())
        self.assertTrue(connection_made)
        self.assertEqual(1, self.TEST_PEER.success_count)
        self.assertEqual(0, self.TEST_PEER.down_count)

    @defer.inlineCallbacks
    def test_bad_server(self):
        # test to see that if we setup a server that returns an improper reply
        # we don't get a connection
        self.server = MocServerProtocolFactory(self.clock, is_good=False)
        self.server_port = reactor.listenTCP(PEER_PORT, self.server, interface=LOCAL_HOST)
        yield self.connection_manager.manage(schedule_next_call=False)
        self.assertEqual(1, self.connection_manager.num_peer_connections())
        connection_made = yield self.connection_manager._peer_connections[self.TEST_PEER].factory.connection_was_made_deferred
        self.assertEqual(0, self.connection_manager.num_peer_connections())
        self.assertTrue(connection_made)
        self.assertEqual(0, self.TEST_PEER.success_count)
        self.assertEqual(1, self.TEST_PEER.down_count)

    @defer.inlineCallbacks
    def test_non_existing_server(self):
        # Test to see that if we don't setup a server, we don't get a connection
        yield self.connection_manager.manage(schedule_next_call=False)
        self.assertEqual(1, self.connection_manager.num_peer_connections())
        connection_made = yield self.connection_manager._peer_connections[self.TEST_PEER].factory.connection_was_made_deferred
        self.assertEqual(0, self.connection_manager.num_peer_connections())
        self.assertFalse(connection_made)
        self.assertEqual(0, self.connection_manager.num_peer_connections())
        self.assertEqual(0, self.TEST_PEER.success_count)
        self.assertEqual(1, self.TEST_PEER.down_count)

    @defer.inlineCallbacks
    def test_parallel_connections(self):
        # Test to see that we make new connection for each manage call,
        # without it waiting for the connection to complete
        test_peer2 = Peer(LOCAL_HOST, PEER_PORT+1)
        self.primary_request_creator.peers_to_return = [self.TEST_PEER, test_peer2]
        yield self.connection_manager.manage(schedule_next_call=False)
        self.assertEqual(1, self.connection_manager.num_peer_connections())
        yield self.connection_manager.manage(schedule_next_call=False)
        self.assertEqual(2, self.connection_manager.num_peer_connections())
        self.assertIn(self.TEST_PEER, self.connection_manager._peer_connections)
        self.assertIn(test_peer2, self.connection_manager._peer_connections)
        connection_made = yield self.connection_manager._peer_connections[self.TEST_PEER].factory.connection_was_made_deferred
        self.assertFalse(connection_made)
        self.assertEqual(1, self.connection_manager.num_peer_connections())
        self.assertEqual(0, self.TEST_PEER.success_count)
        self.assertEqual(1, self.TEST_PEER.down_count)
        connection_made = yield self.connection_manager._peer_connections[test_peer2].factory.connection_was_made_deferred
        self.assertFalse(connection_made)
        self.assertEqual(0, self.connection_manager.num_peer_connections())
        self.assertEqual(0, test_peer2.success_count)
        self.assertEqual(1, test_peer2.down_count)


    @defer.inlineCallbacks
    def test_stop(self):
        # test to see that when we call stop, the ConnectionManager waits for the
        # current manage call to finish, closes connections,
        # and removes scheduled manage calls
        self.connection_manager.manage(schedule_next_call=True)
        yield self.connection_manager.stop()
        self.assertEqual(0, self.TEST_PEER.success_count)
        self.assertEqual(1, self.TEST_PEER.down_count)
        self.assertEqual(0, self.connection_manager.num_peer_connections())
        self.assertEqual(None, self.connection_manager._next_manage_call)


