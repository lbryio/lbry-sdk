import binascii
import logging

from twisted.internet import defer
from lbrynet import conf


log = logging.getLogger(__name__)


class DummyPeerFinder(object):
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
        self.peers = []

    @defer.inlineCallbacks
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
        bin_hash = binascii.unhexlify(blob_hash)
        finished_deferred = self.dht_node.iterativeFindValue(bin_hash)
        timeout = timeout or conf.settings['peer_search_timeout']
        if timeout:
            finished_deferred.addTimeout(timeout, self.dht_node.clock)
        try:
            peer_list = yield finished_deferred
        except defer.TimeoutError:
            log.warning("DHT timed out while looking peers for blob"
                        " %s after %s seconds.", blob_hash, timeout)
            peer_list = []

        peers = set(peer_list)
        results = []
        for node_id, host, port in peers:
            if filter_self and (host, port) == (self.dht_node.externalIP, self.dht_node.peerPort):
                continue
            results.append(self.peer_manager.get_peer(host, port))
        defer.returnValue(results)
