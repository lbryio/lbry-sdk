import logging

from zope.interface import Interface, Attribute
from twisted.internet import defer
from twisted.internet.task import LoopingCall
from lbrynet.conf import MIN_BLOB_DATA_PAYMENT_RATE as min_price

log = logging.getLogger(__name__)

base_price = min_price * 10

# how heavily to value blobs towards the front of the stream
alpha = 1.0


def frontload(index):
    """
    Get frontload multipler

    @param index: blob position in stream
    @return: frontload multipler
    """

    return 2.0 - (alpha**index)


def calculate_price(mean_availability, availability, index_position=0):
    """
    Calculate mean availability weighted price for a blob

    @param mean_availability: sum of blob availabilities over the number of known blobs
    @param availability: number of known peers for blob
    @param index_position: blob index position in stream
    @return: price
    """

    price = max(min_price, base_price * (mean_availability/max(1, availability)) * frontload(index_position))
    return price


class BlobPriceAndAvailabilityTracker(object):
    """
    Class to track peer counts for known blobs and update price targets

    Attributes:
        prices (dist): dictionary of blob prices
        availability (dict): dictionary of peers for known blobs
    """

    def __init__(self, blob_manager, peer_finder, dht_node):
        self.availability = {}
        self.prices = {}
        self._blob_manager = blob_manager
        self._peer_finder = peer_finder
        self._dht_node = dht_node
        self._check_popular = LoopingCall(self._update_most_popular)
        self._check_mine = LoopingCall(self._update_mine)

    def start(self):
        log.info("Starting blob tracker")
        self._check_popular.start(30)
        self._check_mine.start(120)

    def stop(self):
        if self._check_popular.running:
            self._check_popular.stop()
        if self._check_mine.running:
            self._check_mine.stop()

    def _update_peers_for_blob(self, blob):
        def _save_peer_info(blob_hash, peers):
            v = {blob_hash: peers}
            self.availability.update(v)

            new_price = self._get_price(blob)
            self.prices.update({blob: new_price})
            return v

        d = self._peer_finder.find_peers_for_blob(blob)
        d.addCallback(lambda r: [[c.host, c.port, c.is_available()] for c in r])
        d.addCallback(lambda peers: _save_peer_info(blob, peers))
        return d

    def _update_most_popular(self):
        def _get_most_popular():
            dl = []
            for (hash, _) in self._dht_node.get_most_popular_hashes(100):
                encoded = hash.encode('hex')
                dl.append(self._update_peers_for_blob(encoded))
            return defer.DeferredList(dl)
        d = _get_most_popular()

    def _update_mine(self):
        def _get_peers(blobs):
            dl = []
            for hash in blobs:
                dl.append(self._update_peers_for_blob(hash))
            return defer.DeferredList(dl)
        d = self._blob_manager.get_all_verified_blobs()
        d.addCallback(_get_peers)

    def _get_mean_peers(self):
        num_peers = [len(self.availability[blob]) for blob in self.availability]
        mean = float(sum(num_peers)) / float(max(1, len(num_peers)))
        return mean

    def _get_price(self, blob):
        mean_available = self._get_mean_peers()
        blob_availability = len(self.availability.get(blob, []))
        price = calculate_price(mean_available, blob_availability)
        return price