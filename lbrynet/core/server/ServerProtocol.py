import logging
from twisted.internet import interfaces, error
from twisted.internet.protocol import Protocol, ServerFactory
from twisted.python import failure
from zope.interface import implements
from lbrynet.core.server.ServerRequestHandler import ServerRequestHandler


log = logging.getLogger(__name__)


class ServerProtocol(Protocol):
    """ServerProtocol needs to:

    1) Receive requests from its transport
    2) Pass those requests on to its request handler
    3) Tell the request handler to pause/resume producing
    4) Tell its transport to pause/resume producing
    5) Hang up when the request handler is done producing
    6) Tell the request handler to stop producing if the connection is lost
    7) Upon creation, register with the rate limiter
    8) Upon connection loss, unregister with the rate limiter
    9) Report all uploaded and downloaded bytes to the rate limiter
    10) Pause/resume production when told by the rate limiter
    """

    implements(interfaces.IConsumer)

    #Protocol stuff

    def connectionMade(self):
        log.debug("Got a connection")
        peer_info = self.transport.getPeer()
        self.peer = self.factory.peer_manager.get_peer(peer_info.host, peer_info.port)
        self.request_handler = ServerRequestHandler(self)
        for query_handler_factory, enabled in self.factory.query_handler_factories.iteritems():
            if enabled is True:
                query_handler = query_handler_factory.build_query_handler()
                query_handler.register_with_request_handler(self.request_handler, self.peer)
        log.debug("Setting the request handler")
        self.factory.rate_limiter.register_protocol(self)

    def connectionLost(self, reason=failure.Failure(error.ConnectionDone())):
        if self.request_handler is not None:
            self.request_handler.stopProducing()
        self.factory.rate_limiter.unregister_protocol(self)
        if not reason.check(error.ConnectionDone):
            log.warning("Closing a connection. Reason: %s", reason.getErrorMessage())

    def dataReceived(self, data):
        log.debug("Receiving %s bytes of data from the transport", str(len(data)))
        self.factory.rate_limiter.report_dl_bytes(len(data))
        if self.request_handler is not None:
            self.request_handler.data_received(data)

    #IConsumer stuff

    def registerProducer(self, producer, streaming):
        log.debug("Registering the producer")
        assert streaming is True

    def unregisterProducer(self):
        self.request_handler = None
        self.transport.loseConnection()

    def write(self, data):
        log.debug("Writing %s bytes of data to the transport", str(len(data)))
        self.transport.write(data)
        self.factory.rate_limiter.report_ul_bytes(len(data))

    #Rate limiter stuff

    def throttle_upload(self):
        if self.request_handler is not None:
            self.request_handler.pauseProducing()

    def unthrottle_upload(self):
        if self.request_handler is not None:
            self.request_handler.resumeProducing()

    def throttle_download(self):
        self.transport.pauseProducing()

    def unthrottle_download(self):
        self.transport.resumeProducing()


class ServerProtocolFactory(ServerFactory):
    protocol = ServerProtocol

    def __init__(self, rate_limiter, query_handler_factories, peer_manager):
        self.rate_limiter = rate_limiter
        self.query_handler_factories = query_handler_factories
        self.peer_manager = peer_manager