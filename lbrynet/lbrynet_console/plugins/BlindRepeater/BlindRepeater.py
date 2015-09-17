from twisted.internet import defer
from twisted.python.failure import Failure
from lbrynet.core.client.BlobRequester import BlobRequester
from lbrynet.core.client.ConnectionManager import ConnectionManager
from lbrynet.core.client.DownloadManager import DownloadManager
from BlindMetadataHandler import BlindMetadataHandler
from BlindProgressManager import BlindProgressManager
from BlindBlobHandler import BlindBlobHandler
from collections import defaultdict
from interfaces import IBlobScorer
from zope.interface import implements


class PeerScoreBasedScorer(object):
    implements(IBlobScorer)

    def __init__(self):
        pass

    def score_blob(self, blob, blob_info):
        return blob_info.peer_score, 1


class LengthBasedScorer(object):
    implements(IBlobScorer)

    def __init__(self):
        pass

    def score_blob(self, blob, blob_info):
        return 0, 1.0 * blob.get_length() / 2**21


class BlindRepeater(object):
    def __init__(self, peer_finder, rate_limiter, blob_manager, info_manager, wallet, payment_rate_manager):
        self.peer_finder = peer_finder
        self.rate_limiter = rate_limiter
        self.blob_manager = blob_manager
        self.info_manager = info_manager
        self.wallet = wallet
        self.payment_rate_manager = payment_rate_manager
        self.download_manager = None
        self.progress_manager = None
        self.max_space = 0
        self.peers = defaultdict(int)
        self.approved_peers = set()
        self.stopped = True

    def setup(self):
        return defer.succeed(True)

    def start(self):
        if self.stopped is True:
            return self._start()
        else:
            return defer.fail(Failure(ValueError("The repeater is already running")))

    def stop(self):
        if self.stopped is False:
            return self._stop()
        else:
            return defer.fail(Failure(ValueError("The repeater is not running")))

    def status(self):
        if self.stopped is True:
            return "stopped"
        else:
            return "running"

    def set_max_space(self, max_space):
        self.max_space = max_space
        if self.progress_manager is not None:
            self.progress_manager.set_max_space(self.max_space)

    def add_approved_peer(self, peer):
        self.approved_peers.add(peer)

    def remove_approved_peer(self, peer):
        self.approved_peers.remove(peer)

    def _start(self):
        self.download_manager = DownloadManager(self.blob_manager, True)
        info_finder = BlindMetadataHandler(self.info_manager, self.peers, self.peer_finder,
                                           self.approved_peers, self.payment_rate_manager,
                                           self.wallet, self.download_manager)
        self.download_manager.blob_info_finder = info_finder
        blob_requester = BlobRequester(self.blob_manager, self.peer_finder, self.payment_rate_manager,
                                       self.wallet, self.download_manager)
        self.download_manager.blob_requester = blob_requester
        self.progress_manager = BlindProgressManager(self.blob_manager, self.peers, self.max_space,
                                                     [PeerScoreBasedScorer(), LengthBasedScorer()],
                                                     self.download_manager)
        self.download_manager.progress_manager = self.progress_manager
        self.download_manager.blob_handler = BlindBlobHandler()
        wallet_info_exchanger = self.wallet.get_info_exchanger()
        self.download_manager.wallet_info_exchanger = wallet_info_exchanger
        connection_manager = ConnectionManager(self, self.rate_limiter, [info_finder, blob_requester],
                                               [wallet_info_exchanger])
        self.download_manager.connection_manager = connection_manager
        d = defer.maybeDeferred(self.download_manager.start_downloading)
        d.addCallback(lambda _: self._update_status(stopped=False))
        return d

    def _stop(self):
        d = defer.maybeDeferred(self.download_manager.stop_downloading)
        d.addCallback(lambda _: self._update_status(stopped=True))
        return d

    def _update_status(self, stopped=True):
        self.stopped = stopped

    def insufficient_funds(self, err):
        return self.stop()