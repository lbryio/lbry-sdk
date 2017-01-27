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
from twisted.internet import defer,reactor,task
from twisted.internet.task import deferLater
from twisted.internet.protocol import Protocol,ServerFactory
from lbrynet import conf
from lbrynet.interfaces  import IQueryHandlerFactory,IQueryHandler,IRequestCreator

from zope.interface import implements
conf.initialize_settings()

# Set up logging if debugging is necessary for writing more tests
LOG_TO_CONSOLE = False
if LOG_TO_CONSOLE:
    handler = logging.StreamHandler(sys.stdout)
    logging.basicConfig()
    logger = logging.getLogger()
    logger.setLevel(0)
    log_support.configure_console()
    log_support.configure_twisted()


PEER_PORT = 5551
LOCAL_HOST = '127.0.0.1'

class MocDownloader(object):
    def insufficient_funds(self):
        pass

class MocRequestCreator(object):
    implements(IRequestCreator)
    def __init__(self, peer_to_return):
        self.peer_to_return = peer_to_return
        self.sent_request = False

    def send_next_request(self, peer, protocol):
        if self.sent_request is True:
            return defer.succeed(False)
        response_identifier = 'moc_request'
        r_dict = {'moc_request':0}
        request=ClientRequest(r_dict,response_identifier)
        d = protocol.add_request(request) # ClientRequest here
        """
         If connection timed out, goes here with twisted.internet.error.ConnectionAborted
         a) clientprotocol, timeoutConnection
         b) clientprotocol connectionLost - this adds errback to any outstanding responses
         c) if there is no errback handler, error gets propagated
         If bad response returns lbrynet.core.Error.NoResponseError
         a) clientprotocol._handle_response
           if there is no response deferreds for it adds errback NoResponseError
           if response has errback, it calls transport.loseConnection()
           Note that the response handler could possibly swallow the error here
        """
        d.addErrback(self.request_err,peer)
        d.addCallback(self.request_success)
        self.sent_request = True
        return defer.succeed(True)

    def request_success(self,suc):
        pass

    def request_err(self,err,peer):
        if isinstance(err.value,NoResponseError):
            return err

    def get_new_peers(self):
        return [self.peer_to_return]

class MocFunctionalQueryHandler(object):
    implements(IQueryHandler)

    def __init__(self, clock, is_good=True,is_delayed=False):
        self.query_identifiers = [ 'moc_request' ]
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
    def __init__(self,clock,is_good=True,is_delayed=False):
        self.is_good = is_good
        self.is_delayed = is_delayed
        self.clock = clock
    def build_query_handler(self):
        return MocFunctionalQueryHandler(self.clock,self.is_good,self.is_delayed)

    def get_primary_query_identifier(self):
        return 'moc_query'

    def get_description(self):
        return "This is a Moc Query"


class MocServerProtocolFactory(ServerFactory):
    protocol = ServerProtocol
    def __init__(self, clock, is_good=True, is_delayed= False, has_moc_query_handler=True):
        self.rate_limiter = RateLimiter()
        query_handler_factory = MocQueryHandlerFactory(clock, is_good,is_delayed)
        if has_moc_query_handler:
            self.query_handler_factories = {
                query_handler_factory.get_primary_query_identifier():query_handler_factory
            }
        else:
            self.query_handler_factories = {}
        self.peer_manager = PeerManager()


# Setup a server so that ConnectionManager can connect to it
class TestIntegrationConnectionManager(unittest.TestCase):
    def setUp(self):
        self.TEST_PEER = Peer(LOCAL_HOST,PEER_PORT)
        self.downloader = MocDownloader()
        self.rate_limiter = RateLimiter()
        self.primary_request_creator  = MocRequestCreator(self.TEST_PEER)
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


    @defer.inlineCallbacks
    def test_success(self):
        # test to see that if we setup a server, we get a connection
        self.server = MocServerProtocolFactory(self.clock)
        self.server_port = reactor.listenTCP(PEER_PORT,self.server,interface=LOCAL_HOST)

        d = yield self.connection_manager._manage()
        self.assertEqual(1, self.TEST_PEER.success_count)


    @defer.inlineCallbacks
    def test_bad_server(self):
        # test to see that if we setup a server that returns an improper reply
        # we don't get a connection
        self.server = MocServerProtocolFactory(self.clock, is_good=False)
        self.server_port = reactor.listenTCP(PEER_PORT,self.server,interface=LOCAL_HOST)

        d = yield self.connection_manager._manage()
        self.assertEqual(0, self.TEST_PEER.success_count)
        self.assertEqual(1, self.TEST_PEER.down_count)

    @defer.inlineCallbacks
    def test_non_existing_server(self):
        # Test to see that if we don't setup a server, we don't get a connection
        d = yield self.connection_manager._manage()
        self.assertEqual(0, self.connection_manager.num_peer_connections())
        self.assertEqual(0,self.TEST_PEER.success_count)
        self.assertEqual(1,self.TEST_PEER.down_count)

