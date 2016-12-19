import logging
import random
import time

from twisted.internet import defer
from twisted.internet.task import LoopingCall
from decimal import Decimal

log = logging.getLogger(__name__)


class BlobAvailabilityTracker(object):
    """
    Class to track peer counts for known blobs, and to discover new popular blobs

    Attributes:
        availability (dict): dictionary of peers for known blobs
    """

    def __init__(self, blob_manager, peer_finder, dht_node):
        self.availability = {}
        self._last_mean_availability = Decimal(0.0)
        self._blob_manager = blob_manager
        self._peer_finder = peer_finder
        self._dht_node = dht_node
        self._check_popular = LoopingCall(self._update_most_popular)
        self._check_mine = LoopingCall(self._update_mine)

    def start(self):
        log.info("Starting %s", self)
        self._check_popular.start(30)
        self._check_mine.start(600)

    def stop(self):
        log.info("Stopping %s", self)
        if self._check_popular.running:
            self._check_popular.stop()
        if self._check_mine.running:
            self._check_mine.stop()

    def get_blob_availability(self, blob):
        def _get_peer_count(peers):
            have_blob = sum(1 for peer in peers if peer.is_available())
            return {blob: have_blob}

        d = self._peer_finder.find_peers_for_blob(blob)
        d.addCallback(_get_peer_count)
        return d

    def get_availability_for_blobs(self, blobs):
        dl = [self.get_blob_availability(blob) for blob in blobs if blob]
        d = defer.DeferredList(dl)
        d.addCallback(lambda results: [val for success, val in results if success])
        return d

    @property
    def last_mean_availability(self):
        return max(Decimal(0.01), self._last_mean_availability)


    def _update_peers_for_blob(self, blob):
        def _save_peer_info(blob_hash, peers):
            v = {blob_hash: peers}
            self.availability.update(v)
            return v

        d = self._peer_finder.find_peers_for_blob(blob)
        d.addCallback(lambda r: [[c.host, c.port, c.is_available()] for c in r])
        d.addCallback(lambda peers: _save_peer_info(blob, peers))
        return d

    def _get_most_popular(self):
        dl = []
        for (hash, _) in self._dht_node.get_most_popular_hashes(100):
            encoded = hash.encode('hex')
            dl.append(self._update_peers_for_blob(encoded))
        return defer.DeferredList(dl)

    def _update_most_popular(self):
        d = self._get_most_popular()
        d.addCallback(lambda _: self._set_mean_peers())

    def _update_mine(self):
        def _get_peers(blobs):
            dl = []
            for hash in blobs:
                dl.append(self._update_peers_for_blob(hash))
            return defer.DeferredList(dl)

        def sample(blobs):
            sample_size = min(len(blobs), 100)
            return random.sample(blobs, sample_size)

        start = time.time()
        log.debug('==> Updating the peers for my blobs')
        d = self._blob_manager.get_all_verified_blobs()
        # as far as I can tell, this only is used to set _last_mean_availability
        # which... seems like a very expensive operation for such little payoff.
        # so taking a sample should get about the same effect as querying the entire
        # list of blobs
        d.addCallback(sample)
        d.addCallback(_get_peers)
        d.addCallback(lambda _: self._set_mean_peers())
        d.addCallback(lambda _: log.debug('<== Done updating peers for my blobs. Took %s seconds',
                                          time.time() - start))
        # although unused, need to return or else the looping call
        # could overrun on a previous call
        return d

    def _set_mean_peers(self):
        num_peers = [len(self.availability[blob]) for blob in self.availability]
        mean = Decimal(sum(num_peers)) / Decimal(max(1, len(num_peers)))
        self._last_mean_availability = mean
