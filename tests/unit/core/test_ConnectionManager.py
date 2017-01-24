from lbrynet.core.client.ConnectionManager import ConnectionManager
from lbrynet.core.client.ClientRequest import ClientRequest
from lbrynet.core.server.ServerProtocol import ServerProtocol
from lbrynet.core.RateLimiter import RateLimiter
from lbrynet.core.Peer import Peer
from lbrynet.core.PeerManager import PeerManager
from twisted.trial import unittest
from twisted.internet import defer,reactor
from twisted.internet.protocol import Protocol,ServerFactory
from lbrynet import conf
from lbrynet.interfaces  import IQueryHandlerFactory,IQueryHandler

from zope.interface import implements
conf.initialize_settings()


class MocDownloader(object):
    def insufficient_funds(self):
        pass

class MocRequestCreator(object):
    TEST_PEER = Peer('0.0.0.0',3333)
    def send_next_request(self, peer, protocol):
        print("WOOO")
        protocol.add_request('moc_query') # ClientRequest here 
    def get_new_peers(self):
        return [Peer('0.0.0.0',3333)]

class MocQueryHandler(object):
    implements(IQueryHandler)

    def __init__(self):
        self.query_identifiers = [ 'moc_query' ]
    ######### IQueryHandler #########

    def register_with_request_handler(self, request_handler, peer):
        request_handler.register_query_handler(self, self.query_identifiers)

    def handle_queries(self, queries):
        if self.query_identifiers[0] in queries:
        	return defer.succeed("Success")

class MocQueryHandlerFactory(object):
    implements(IQueryHandlerFactory)

    def build_query_handler(self):
        q_h = MocQueryHandler()
        return q_h

    def get_primary_query_identifier(self):
        return 'moc_query'

    def get_description(self):
        return "This is a Moc Query"



class MocServerProtocolFactory(ServerFactory):
    protocol = ServerProtocol
    def __init__(self):
        self.rate_limiter = RateLimiter()
        query_handler_factory = MocQueryHandlerFactory()
        self.query_handler_factories = {
            query_handler_factory.get_primary_query_identifier():query_handler_factory
        }

        self.peer_manager = PeerManager() 


# Some simple tests, for functionality not dependent on other classes
class TestConnectionManagerBasic(unittest.TestCase):
    def setUp(self):

        self.downloader = MocDownloader()
        self.rate_limiter = RateLimiter()
        self.primary_request_creator  = MocRequestCreator()
        self.connection_manager = ConnectionManager(self.downloader, self.rate_limiter,
                    [self.primary_request_creator], [])

        self.connection_manager._start()
    @defer.inlineCallbacks
    def test_get_new_peers(self):

        peers = yield self.connection_manager._get_new_peers( [self.primary_request_creator] )
        self.assertEqual(1,len(peers))

    def test_connect_to_peer(self):
        self.assertEqual(0, self.connection_manager.num_connected_peers())
        self.connection_manager._connect_to_peer(MocRequestCreator.TEST_PEER)
        self.assertEqual(1, self.connection_manager.num_connected_peers())

    @defer.inlineCallbacks
    def test_manage(self):
        @defer.inlineCallbacks
        def manage_test(self):
            if len(self._peer_connections) < conf.settings['max_connections_per_stream']:
                try:
                    ordered_request_creators = self._rank_request_creator_connections()
                    peers = yield self._get_new_peers(ordered_request_creators)
                    peer = self._pick_best_peer(peers)
                    yield self._connect_to_peer(peer)
                except Exception:
                    # log this otherwise it will just end up as an unhandled error in deferred
                    log.exception('Something bad happened picking a peer')


        self.rate_limiter = RateLimiter()
        self.downloader = MocDownloader()
        self.primary_request_creator  = MocRequestCreator()
        self.connection_manager = ConnectionManager(self.downloader, self.rate_limiter,
                    [self.primary_request_creator], [])

        SERVER_PORT = 3333
        self.server = MocServerProtocolFactory()
        server_port = reactor.listenTCP(SERVER_PORT,self.server)
        self.connection_manager._start()
        d = yield manage_test(self.connection_manager)
        self.assertEqual(self.connection_manager.num_connected_peers(),1)
        
        d = yield manage_test(self.connection_manager)
        self.assertEqual(self.connection_manager.num_connected_peers(),1)


        server_port.stopListening()
