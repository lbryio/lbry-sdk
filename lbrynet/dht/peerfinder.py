import binascii
import logging

from twisted.internet import defer
from lbrynet import conf


log = logging.getLogger(__name__)


class DummyPeerFinder:
    """This class finds peers which have announced to the DHT that they have certain blobs"""

    def find_peers_for_blob(self, blob_hash, timeout=None, filter_self=True):
        return defer.succeed([])


class DHTPeerFinder(DummyPeerFinder):
    """This class finds peers which have announced to the DHT that they have certain blobs"""
    #implements(IPeerFinder)

    def __init__(self, dht_node, peer_manager):
        """
        dht_node - an instance of dht.Node class
        peer_manager - an instance of PeerManager class
        """
        self.dht_node = dht_node
        self.peer_manager = peer_manager
        self.peers = {}
        self._ongoing_searchs = {}

    def find_peers_for_blob(self, blob_hash, timeout=None, filter_self=True):
        """
        Find peers for blob in the DHT
        blob_hash (str): blob hash to look for
        timeout (int): seconds to timeout after
        filter_self (bool): if True, and if a peer for a blob is itself, filter it
                from the result

        Returns:
        list of peers for the blob
        """
        self.peers.setdefault(blob_hash, {(self.dht_node.externalIP, self.dht_node.peerPort,)})
        if not blob_hash in self._ongoing_searchs or self._ongoing_searchs[blob_hash].called:
            self._ongoing_searchs[blob_hash] = self._execute_peer_search(blob_hash, timeout)
        peers = set(self._filter_self(blob_hash) if filter_self else self.peers[blob_hash])
        return defer.succeed([self.peer_manager.get_peer(*peer) for peer in peers])

    @defer.inlineCallbacks
    def _execute_peer_search(self, blob_hash, timeout):
        bin_hash = binascii.unhexlify(blob_hash)
        finished_deferred = self.dht_node.iterativeFindValue(bin_hash, exclude=self.peers[blob_hash])
        timeout = timeout or conf.settings['peer_search_timeout']
        if timeout:
            finished_deferred.addTimeout(timeout, self.dht_node.clock)
        try:
            peer_list = yield finished_deferred
            self.peers[blob_hash].update(set((host, port) for _, host, port in peer_list))
        except defer.TimeoutError:
            log.debug("DHT timed out while looking peers for blob %s after %s seconds", blob_hash, timeout)
        finally:
            del self._ongoing_searchs[blob_hash]

    def _filter_self(self, blob_hash):
        my_host, my_port = self.dht_node.externalIP, self.dht_node.peerPort
        return set((host, port) for host, port in self.peers[blob_hash] if (host, port) != (my_host, my_port))
