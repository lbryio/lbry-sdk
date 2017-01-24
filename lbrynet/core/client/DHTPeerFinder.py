import binascii
import logging

from zope.interface import implements
from lbrynet.interfaces import IPeerFinder
from lbrynet import conf
from lbrynet.core.Peer import Peer,PeerSet

log = logging.getLogger(__name__)


class DHTPeerFinder(object):
    """This class finds peers which have announced to the DHT that they have certain blobs"""
    implements(IPeerFinder)

    def __init__(self, dht_node, peer_manager):
        self.dht_node = dht_node
        self.peer_manager = peer_manager
        self.peers = []
        self.next_manage_call = None

    def run_manage_loop(self):

        from twisted.internet import reactor

        self._manage_peers()
        self.next_manage_call = reactor.callLater(60, self.run_manage_loop)

    def stop(self):
        log.info("Stopping %s", self)
        if self.next_manage_call is not None and self.next_manage_call.active():
            self.next_manage_call.cancel()
            self.next_manage_call = None

    def _manage_peers(self):
        pass

    def find_peers_for_blob(self, blob_hash):
        bin_hash = binascii.unhexlify(blob_hash)

        def filter_peers(peer_list):
            peers = set(peer_list)
            good_peers = PeerSet()
            for host, port in peers:
                peer = self.peer_manager.get_peer(host, port)
                if peer.is_available() is True:
                    good_peers.add(peer)
            return good_peers

        def add_default_peers(peers):
            for host, port in conf.settings['known_blob_peers']:
                peer = self.peer_manager.get_peer(host,port)
                peers.add(peer)
            return peers

        d = self.dht_node.getPeersForBlob(bin_hash)
        d.addCallback(filter_peers)
        d.addCallback(add_default_peers)
        return d

    def get_most_popular_hashes(self, num_to_return):
        return self.dht_node.get_most_popular_hashes(num_to_return)
