# pylint: skip-file
# This file is not maintained, but might be used in the future
#
import logging
import sys

from lbrynet.lbrylive.client.LiveStreamDownloader import LBRYLiveStreamDownloader
from lbrynet.core.BlobManager import TempBlobManager
from lbrynet.core.Session import LBRYSession
from lbrynet.core.client.StandaloneBlobDownloader import StandaloneBlobDownloader
from lbrynet.core.StreamDescriptor import BlobStreamDescriptorReader
from lbrynet.lbrylive.PaymentRateManager import BaseLiveStreamPaymentRateManager
from lbrynet.lbrylive.LiveStreamMetadataManager import DBLiveStreamMetadataManager
from lbrynet.lbrylive.StreamDescriptor import save_sd_info
from lbrynet.dht.node import Node
from twisted.internet import task


class LBRYStdoutDownloader():
    """This class downloads a live stream from the network and outputs it to standard out."""
    def __init__(self, dht_node_port, known_dht_nodes,
                 stream_info_manager_class=DBLiveStreamMetadataManager, blob_manager_class=TempBlobManager):
        """
        @param dht_node_port: the network port on which to listen for DHT node requests

        @param known_dht_nodes: a list of (ip_address, dht_port) which will be used to join the DHT network

        """

        self.session = LBRYSession(blob_manager_class=blob_manager_class,
                                   stream_info_manager_class=stream_info_manager_class,
                                   dht_node_class=Node, dht_node_port=dht_node_port, known_dht_nodes=known_dht_nodes,
                                   use_upnp=False)
        self.payment_rate_manager = BaseLiveStreamPaymentRateManager()

    def start(self):
        """Initialize the session"""
        d = self.session.setup()
        return d

    def read_sd_file(self, sd_blob):
        reader = BlobStreamDescriptorReader(sd_blob)
        return save_sd_info(self.stream_info_manager, reader, ignore_duplicate=True)

    def download_sd_file_from_hash(self, sd_hash):
        downloader = StandaloneBlobDownloader(sd_hash, self.session.blob_manager,
                                              self.session.peer_finder, self.session.rate_limiter,
                                              self.session.wallet)
        d = downloader.download()
        return d

    def start_download(self, sd_hash):
        """Start downloading the stream from the network and outputting it to standard out"""
        d = self.download_sd_file_from_hash(sd_hash)
        d.addCallbacks(self.read_sd_file)

        def start_stream(stream_hash):
            consumer = LBRYLiveStreamDownloader(stream_hash, self.session.peer_finder,
                                                self.session.rate_limiter, self.session.blob_manager,
                                                self.stream_info_manager, self.payment_rate_manager,
                                                self.session.wallet)
            return consumer.start()

        d.addCallback(start_stream)
        return d

    def shut_down(self):
        """End the session"""
        d = self.session.shut_down()
        return d


def launch_stdout_downloader():

    from twisted.internet import reactor

    logging.basicConfig(level=logging.WARNING, filename="dl.log")
    if len(sys.argv) == 3:
        downloader = LBRYStdoutDownloader(int(sys.argv[2]), [])
    elif len(sys.argv) == 5:
        downloader = LBRYStdoutDownloader(int(sys.argv[2]), [(sys.argv[3], int(sys.argv[4]))])
    else:
        print "Usage: lbrynet-stdout-downloader <sd_hash> <peer_port> <dht_node_port>" \
              " [<dht_bootstrap_host> <dht_bootstrap port>]"
        sys.exit(1)

    def start_stdout_downloader():
        return downloader.start_download(sys.argv[1])

    def print_error(err):
        logging.warning(err.getErrorMessage())

    def shut_down():
        reactor.stop()

    d = task.deferLater(reactor, 0, downloader.start)
    d.addCallback(lambda _: start_stdout_downloader())
    d.addErrback(print_error)
    d.addCallback(lambda _: shut_down())
    reactor.addSystemEventTrigger('before', 'shutdown', downloader.shut_down)
    reactor.run()
