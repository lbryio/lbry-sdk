import binascii
import logging

from zope.interface import implements
from twisted.internet import defer, reactor
from lbrynet.interfaces import IPeerFinder
from lbrynet.core.utils import short_hash


log = logging.getLogger(__name__)


class DHTPeerFinder(object):
    """This class finds peers which have announced to the DHT that they have certain blobs"""
    implements(IPeerFinder)

    def __init__(self, dht_node, peer_manager):
        """
        dht_node - an instance of dht.Node class
        peer_manager - an instance of PeerManager class
        """
        self.dht_node = dht_node
        self.peer_manager = peer_manager
        self.peers = []
        self.next_manage_call = None

    def run_manage_loop(self):
        self._manage_peers()
        self.next_manage_call = reactor.callLater(60, self.run_manage_loop)

    def stop(self):
        log.info("Stopping DHT peer finder.")
        if self.next_manage_call is not None and self.next_manage_call.active():
            self.next_manage_call.cancel()
            self.next_manage_call = None

    def _manage_peers(self):
        pass

    @defer.inlineCallbacks
    def find_peers_for_blob(self, blob_hash, timeout=None, filter_self=False):
        """
        Find peers for blob in the DHT
        blob_hash (str): blob hash to look for
        timeout (int): seconds to timeout after
        filter_self (bool): if True, and if a peer for a blob is itself, filter it
                from the result

        Returns:
        list of peers for the blob
        """
        def _trigger_timeout():
            if not finished_deferred.called:
                log.debug("Peer search for %s timed out", short_hash(blob_hash))
                finished_deferred.cancel()

        bin_hash = binascii.unhexlify(blob_hash)
        finished_deferred = self.dht_node.getPeersForBlob(bin_hash)

        if timeout is not None:
            reactor.callLater(timeout, _trigger_timeout)

        try:
            peer_list = yield finished_deferred
        except defer.CancelledError:
            peer_list = []

        peers = set(peer_list)
        good_peers = []
        for host, port in peers:
            if filter_self and (host, port) == (self.dht_node.externalIP, self.dht_node.peerPort):
                continue
            peer = self.peer_manager.get_peer(host, port)
            if peer.is_available() is True:
                good_peers.append(peer)

        defer.returnValue(good_peers)

    def get_most_popular_hashes(self, num_to_return):
        return self.dht_node.get_most_popular_hashes(num_to_return)
