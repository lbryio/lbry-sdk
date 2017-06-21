import logging
from zope.interface import implements
from lbrynet import interfaces
from lbrynet.core.BlobInfo import BlobInfo
from lbrynet.core.client.BlobRequester import BlobRequester
from lbrynet.core.client.ConnectionManager import ConnectionManager
from lbrynet.core.client.DownloadManager import DownloadManager
from lbrynet.core.Error import InvalidBlobHashError, DownloadTimeoutError
from lbrynet.core.utils import is_valid_blobhash, safe_start_looping_call, safe_stop_looping_call
from twisted.python.failure import Failure
from twisted.internet import defer
from twisted.internet.task import LoopingCall

log = logging.getLogger(__name__)


class SingleBlobMetadataHandler(object):
    implements(interfaces.IMetadataHandler)

    def __init__(self, blob_hash, download_manager):
        self.blob_hash = blob_hash
        self.download_manager = download_manager

    ######## IMetadataHandler #########

    def get_initial_blobs(self):
        log.debug("Returning the blob info")
        return defer.succeed([BlobInfo(self.blob_hash, 0, None)])

    def final_blob_num(self):
        return 0


class SingleProgressManager(object):
    def __init__(self, download_manager, finished_callback, timeout_callback, timeout):
        self.finished_callback = finished_callback
        self.timeout_callback = timeout_callback
        self.download_manager = download_manager

        self.timeout = timeout
        self.timeout_counter = 0
        self.checker = LoopingCall(self._check_if_finished)

    def start(self):
        safe_start_looping_call(self.checker, 1)
        return defer.succeed(True)

    def stop(self):
        safe_stop_looping_call(self.checker)
        return defer.succeed(True)

    def _check_if_finished(self):
        if self.stream_position() == 1:
            blob_downloaded = self.download_manager.blobs[0]
            log.debug("The blob %s has been downloaded. Calling the finished callback", str(blob_downloaded))
            safe_stop_looping_call(self.checker)
            self.finished_callback(blob_downloaded)
        elif self.timeout is not None:
            self.timeout_counter += 1
            if self.timeout_counter >= self.timeout:
                safe_stop_looping_call(self.checker)
                self.timeout_callback()

    def stream_position(self):
        blobs = self.download_manager.blobs
        if blobs and blobs[0].is_validated():
            return 1
        return 0

    def needed_blobs(self):
        blobs = self.download_manager.blobs
        assert len(blobs) == 1
        return [b for b in blobs.itervalues() if not b.is_validated()]


class DummyBlobHandler(object):
    def __init__(self):
        pass

    def handle_blob(self, blob, blob_info):
        pass


class StandaloneBlobDownloader(object):
    def __init__(self, blob_hash, blob_manager, peer_finder,
                 rate_limiter, payment_rate_manager, wallet,
                 timeout=None):
        self.blob_hash = blob_hash
        self.blob_manager = blob_manager
        self.peer_finder = peer_finder
        self.rate_limiter = rate_limiter
        self.payment_rate_manager = payment_rate_manager
        self.wallet = wallet
        self.timeout = timeout
        self.download_manager = None
        self.finished_deferred = None

    def download(self):
        if not is_valid_blobhash(self.blob_hash):
            return defer.fail(Failure(InvalidBlobHashError(self.blob_hash)))

        def cancel_download(d):
            self.stop()

        self.finished_deferred = defer.Deferred(canceller=cancel_download)
        self.download_manager = DownloadManager(self.blob_manager)
        self.download_manager.blob_requester = BlobRequester(self.blob_manager, self.peer_finder,
                                                             self.payment_rate_manager, self.wallet,
                                                             self.download_manager)
        self.download_manager.blob_info_finder = SingleBlobMetadataHandler(self.blob_hash,
                                                                           self.download_manager)
        self.download_manager.progress_manager = SingleProgressManager(self.download_manager,
                                                                       self._blob_downloaded,
                                                                       self._download_timedout,
                                                                       self.timeout)
        self.download_manager.blob_handler = DummyBlobHandler()
        self.download_manager.wallet_info_exchanger = self.wallet.get_info_exchanger()
        self.download_manager.connection_manager = ConnectionManager(
            self, self.rate_limiter,
            [self.download_manager.blob_requester],
            [self.download_manager.wallet_info_exchanger]
        )
        d = self.download_manager.start_downloading()
        d.addCallback(lambda _: self.finished_deferred)
        return d

    def stop(self):
        return self.download_manager.stop_downloading()

    def _blob_downloaded(self, blob):
        self.stop()
        if not self.finished_deferred.called:
            self.finished_deferred.callback(blob)

    def _download_timedout(self):
        self.stop()
        if not self.finished_deferred.called:
            self.finished_deferred.errback(DownloadTimeoutError(self.blob_hash))

    def insufficient_funds(self, err):
        self.stop()
        if not self.finished_deferred.called:
            self.finished_deferred.errback(err)
