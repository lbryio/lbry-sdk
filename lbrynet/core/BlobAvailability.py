import logging

from twisted.internet import defer
from twisted.internet.task import LoopingCall
from lbrynet.core.PeerFinder import DummyPeerFinder

log = logging.getLogger(__name__)


class BlobAvailabilityTracker(object):
    """
    Class to track peer counts for known blobs, and to discover new popular blobs

    Attributes:
        availability (dict): dictionary of peers for known blobs
    """

    def __init__(self, blob_manager, peer_finder, dht_node):
        self.availability = {}
        self.last_mean_availability = 0.0
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
        d.addCallback(lambda results: [r[1] for r in results])
        return d

    def _update_peers_for_blob(self, blob):
        def _save_peer_info(blob_hash, peers):
            v = {blob_hash: peers}
            self.availability.update(v)
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
        d.addCallback(lambda _: self._get_mean_peers())

    def _update_mine(self):
        def _get_peers(blobs):
            dl = []
            for hash in blobs:
                dl.append(self._update_peers_for_blob(hash))
            return defer.DeferredList(dl)

        d = self._blob_manager.get_all_verified_blobs()
        d.addCallback(_get_peers)
        d.addCallback(lambda _: self._get_mean_peers())

    def _get_mean_peers(self):
        num_peers = [len(self.availability[blob]) for blob in self.availability]
        mean = float(sum(num_peers)) / float(max(1, len(num_peers)))
        self.last_mean_availability = mean


class DummyBlobAvailabilityTracker(BlobAvailabilityTracker):
    """
    Class to track peer counts for known blobs, and to discover new popular blobs

    Attributes:
        availability (dict): dictionary of peers for known blobs
    """

    def __init__(self):
        self.availability = {
            '91dc64cf1ff42e20d627b033ad5e4c3a4a96856ed8a6e3fb4cd5fa1cfba4bf72eefd325f579db92f45f4355550ace8e7': ['1.2.3.4'],
            'b2e48bb4c88cf46b76adf0d47a72389fae0cd1f19ed27dc509138c99509a25423a4cef788d571dca7988e1dca69e6fa0': ['1.2.3.4', '1.2.3.4'],
            '6af95cd062b4a179576997ef1054c9d2120f8592eea045e9667bea411d520262cd5a47b137eabb7a7871f5f8a79c92dd': ['1.2.3.4', '1.2.3.4', '1.2.3.4'],
            '6d8017aba362e5c5d0046625a039513419810a0397d728318c328a5cc5d96efb589fbca0728e54fe5adbf87e9545ee07': ['1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4'],
            '5a450b416275da4bdff604ee7b58eaedc7913c5005b7184fc3bc5ef0b1add00613587f54217c91097fc039ed9eace9dd': ['1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4'],
            'd7c82e6cac093b3f16107d2ae2b2c75424f1fcad2c7fbdbe66e4a13c0b6bd27b67b3a29c403b82279ab0f7c1c48d6787': ['1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4'],
            '9dbda74a472a2e5861a5d18197aeba0f5de67c67e401124c243d2f0f41edf01d7a26aeb0b5fc9bf47f6361e0f0968e2c': ['1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4'],
            '8c70d5e2f5c3a6085006198e5192d157a125d92e7378794472007a61947992768926513fc10924785bdb1761df3c37e6': ['1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4'],
            'f99d24cd50d4bfd77c2598bfbeeb8415bf0feef21200bdf0b8fbbde7751a77b7a2c68e09c25465a2f40fba8eecb0b4e0': ['1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4'],
            'c84aa1fd8f5009f7c4e71e444e40d95610abc1480834f835eefb267287aeb10025880a3ce22580db8c6d92efb5bc0c9c': ['1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4', '1.2.3.4'],
        }
        self.last_mean_availability = 0.0
        self._blob_manager = None
        self._peer_finder = DummyPeerFinder()
        self._dht_node = None
        self._check_popular = None
        self._check_mine = None
        self._get_mean_peers()

    def start(self):
        pass

    def stop(self):
        pass
