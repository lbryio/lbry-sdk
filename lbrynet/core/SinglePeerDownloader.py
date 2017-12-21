import logging
import shutil
import tempfile

from twisted.internet import defer, threads, reactor

from lbrynet.blob import BlobFile
from lbrynet.core.BlobManager import DiskBlobManager
from lbrynet.core.HashAnnouncer import DummyHashAnnouncer
from lbrynet.core.RateLimiter import DummyRateLimiter
from lbrynet.core.PaymentRateManager import OnlyFreePaymentsManager
from lbrynet.core.PeerFinder import DummyPeerFinder
from lbrynet.core.client.BlobRequester import BlobRequester
from lbrynet.core.client.StandaloneBlobDownloader import StandaloneBlobDownloader
from lbrynet.core.client.ConnectionManager import ConnectionManager

log = logging.getLogger(__name__)


class TempBlobManager(DiskBlobManager):
    def stop(self):
        self.db_conn.close()
        return defer.succeed(True)


class SinglePeerFinder(DummyPeerFinder):
    def __init__(self, peer):
        DummyPeerFinder.__init__(self)
        self.peer = peer

    def find_peers_for_blob(self, blob_hash, timeout=None, filter_self=False):
        return defer.succeed([self.peer])


class BlobCallback(BlobFile):
    def __init__(self, blob_dir, blob_hash, timeout):
        BlobFile.__init__(self, blob_dir, blob_hash)
        self.callback = defer.Deferred()
        reactor.callLater(timeout, self._cancel)

    def _cancel(self):
        if not self.callback.called:
            self.callback.callback(False)

    def save_verified_blob(self, writer):
        result = BlobFile.save_verified_blob(self, writer)
        if not self.callback.called:
            self.callback.callback(True)
        return result


class SingleBlobDownloadManager(object):
    def __init__(self, blob):
        self.blob = blob

    def needed_blobs(self):
        if self.blob.verified:
            return []
        else:
            return [self.blob]

    def get_head_blob_hash(self):
        return self.blob.blob_hash


class SinglePeerDownloader(object):
    def __init__(self):
        self._payment_rate_manager = OnlyFreePaymentsManager()
        self._announcer = DummyHashAnnouncer()
        self._rate_limiter = DummyRateLimiter()
        self._wallet = None
        self._blob_manager = None

    def setup(self, wallet, blob_manager=None):
        if not self._wallet:
            self._wallet = wallet
        if not self._blob_manager:
            self._blob_manager = blob_manager

    @defer.inlineCallbacks
    def download_blob_from_peer(self, peer, timeout, blob_hash, blob_manager):
        log.debug("Try to download %s from %s", blob_hash, peer.host)
        blob_manager = blob_manager
        blob = BlobCallback(blob_manager.blob_dir, blob_hash, timeout)
        download_manager = SingleBlobDownloadManager(blob)
        peer_finder = SinglePeerFinder(peer)
        requester = BlobRequester(blob_manager, peer_finder, self._payment_rate_manager,
                                  self._wallet, download_manager)
        downloader = StandaloneBlobDownloader(blob_hash, blob_manager, peer_finder,
                                              self._rate_limiter, self._payment_rate_manager,
                                              self._wallet, timeout=timeout)
        info_exchanger = self._wallet.get_info_exchanger()
        connection_manager = ConnectionManager(downloader, self._rate_limiter, [requester],
                                               [info_exchanger])
        connection_manager.start()
        result = yield blob.callback
        if not result:
            log.debug("Failed to downloaded %s from %s", blob_hash[:16], peer.host)
            yield connection_manager.stop()
        defer.returnValue(result)

    @defer.inlineCallbacks
    def download_temp_blob_from_peer(self, peer, timeout, blob_hash):
        tmp_dir = yield threads.deferToThread(tempfile.mkdtemp)
        tmp_blob_manager = TempBlobManager(self._announcer, tmp_dir, tmp_dir)
        try:
            result = yield self.download_blob_from_peer(peer, timeout, blob_hash, tmp_blob_manager)
        finally:
            yield tmp_blob_manager.stop()
            yield threads.deferToThread(shutil.rmtree, tmp_dir)
        defer.returnValue(result)
