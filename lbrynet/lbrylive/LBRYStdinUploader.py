# pylint: skip-file
# This file is not maintained, but might be used in the future
#
import logging
import sys
from lbrynet.lbrylive.LiveStreamCreator import StdOutLiveStreamCreator
from lbrynet.core.BlobManager import TempBlobManager
from lbrynet.core.Session import LBRYSession
from lbrynet.core.server.BlobAvailabilityHandler import BlobAvailabilityHandlerFactory
from lbrynet.core.server.BlobRequestHandler import BlobRequestHandlerFactory
from lbrynet.core.server.ServerProtocol import ServerProtocolFactory
from lbrynet.lbrylive.PaymentRateManager import BaseLiveStreamPaymentRateManager
from lbrynet.lbrylive.LiveStreamMetadataManager import DBLiveStreamMetadataManager
from lbrynet.lbrylive.server.LiveBlobInfoQueryHandler import CryptBlobInfoQueryHandlerFactory
from lbrynet.dht.node import Node
from twisted.internet import defer, task


class LBRYStdinUploader():
    """This class reads from standard in, creates a stream, and makes it available on the network."""
    def __init__(self, peer_port, dht_node_port, known_dht_nodes,
                 stream_info_manager_class=DBLiveStreamMetadataManager, blob_manager_class=TempBlobManager):
        """
        @param peer_port: the network port on which to listen for peers

        @param dht_node_port: the network port on which to listen for nodes in the DHT

        @param known_dht_nodes: a list of (ip_address, dht_port) which will be used to join the DHT network
        """
        self.peer_port = peer_port
        self.lbry_server_port = None
        self.session = LBRYSession(blob_manager_class=blob_manager_class,
                                   stream_info_manager_class=stream_info_manager_class,
                                   dht_node_class=Node, dht_node_port=dht_node_port,
                                   known_dht_nodes=known_dht_nodes, peer_port=self.peer_port,
                                   use_upnp=False)
        self.payment_rate_manager = BaseLiveStreamPaymentRateManager()

    def start(self):
        """Initialize the session and start listening on the peer port"""
        d = self.session.setup()
        d.addCallback(lambda _: self._start())

        return d

    def _start(self):
        self._start_server()
        return True

    def _start_server(self):
        query_handler_factories = [
            CryptBlobInfoQueryHandlerFactory(self.stream_info_manager, self.session.wallet,
                                             self.payment_rate_manager),
            BlobAvailabilityHandlerFactory(self.session.blob_manager),
            BlobRequestHandlerFactory(self.session.blob_manager, self.session.wallet,
                                      self.payment_rate_manager),
            self.session.wallet.get_wallet_info_query_handler_factory()
        ]

        self.server_factory = ServerProtocolFactory(self.session.rate_limiter,
                                                    query_handler_factories,
                                                    self.session.peer_manager)
        from twisted.internet import reactor
        self.lbry_server_port = reactor.listenTCP(self.peer_port, self.server_factory)

    def start_live_stream(self, stream_name):
        """Create the stream and start reading from stdin

        @param stream_name: a string, the suggested name of this stream
        """
        stream_creator_helper = StdOutLiveStreamCreator(stream_name, self.session.blob_manager,
                                                        self.stream_info_manager)
        d = stream_creator_helper.create_and_publish_stream_descriptor()

        def print_sd_hash(sd_hash):
            print "Stream descriptor hash:", sd_hash

        d.addCallback(print_sd_hash)
        d.addCallback(lambda _: stream_creator_helper.start_streaming())
        return d

    def shut_down(self):
        """End the session and stop listening on the server port"""
        d = self.session.shut_down()
        d.addCallback(lambda _: self._shut_down())
        return d

    def _shut_down(self):
        if self.lbry_server_port is not None:
            d = defer.maybeDeferred(self.lbry_server_port.stopListening)
        else:
            d = defer.succeed(True)
        return d


def launch_stdin_uploader():

    from twisted.internet import reactor

    logging.basicConfig(level=logging.WARNING, filename="ul.log")
    if len(sys.argv) == 4:
        uploader = LBRYStdinUploader(int(sys.argv[2]), int(sys.argv[3]), [])
    elif len(sys.argv) == 6:
        uploader = LBRYStdinUploader(int(sys.argv[2]), int(sys.argv[3]), [(sys.argv[4], int(sys.argv[5]))])
    else:
        print "Usage: lbrynet-stdin-uploader <stream_name> <peer_port> <dht_node_port>" \
              " [<dht_bootstrap_host> <dht_bootstrap port>]"
        sys.exit(1)

    def start_stdin_uploader():
        return uploader.start_live_stream(sys.argv[1])

    def shut_down():
        logging.debug("Telling the reactor to stop in 60 seconds")
        reactor.callLater(60, reactor.stop)

    d = task.deferLater(reactor, 0, uploader.start)
    d.addCallback(lambda _: start_stdin_uploader())
    d.addCallback(lambda _: shut_down())
    reactor.addSystemEventTrigger('before', 'shutdown', uploader.shut_down)
    reactor.run()
