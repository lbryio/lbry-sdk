import logging
from zope.interface import implements
from lbrynet import interfaces
from lbrynet.core.BlobInfo import BlobInfo
from lbrynet.core.client.BlobRequester import BlobRequester
from lbrynet.core.client.ConnectionManager import ConnectionManager
from lbrynet.core.client.DownloadManager import DownloadManager
from lbrynet.core.Error import InvalidBlobHashError
from lbrynet.core.utils import is_valid_blobhash
from twisted.python.failure import Failure
from twisted.internet import defer


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
    def __init__(self, finished_callback, download_manager):
        self.finished_callback = finished_callback
        self.finished = False
        self.download_manager = download_manager
        self._next_check_if_finished = None

    def start(self):

        from twisted.internet import reactor

        assert self._next_check_if_finished is None
        self._next_check_if_finished = reactor.callLater(0, self._check_if_finished)
        return defer.succeed(True)

    def stop(self):
        if self._next_check_if_finished is not None:
            self._next_check_if_finished.cancel()
            self._next_check_if_finished = None
        return defer.succeed(True)

    def _check_if_finished(self):

        from twisted.internet import reactor

        self._next_check_if_finished = None
        if self.finished is False:
            if self.stream_position() == 1:
                self.blob_downloaded(self.download_manager.blobs[0], 0)
            else:
                self._next_check_if_finished = reactor.callLater(1, self._check_if_finished)

    def stream_position(self):
        blobs = self.download_manager.blobs
        if blobs and blobs[0].is_validated():
            return 1
        return 0

    def needed_blobs(self):
        blobs = self.download_manager.blobs
        assert len(blobs) == 1
        return [b for b in blobs.itervalues() if not b.is_validated()]

    def blob_downloaded(self, blob, blob_num):

        from twisted.internet import reactor

        log.debug("The blob %s has been downloaded. Calling the finished callback", str(blob))
        if self.finished is False:
            self.finished = True
            reactor.callLater(0, self.finished_callback, blob)


class DummyBlobHandler(object):
    def __init__(self):
        pass

    def handle_blob(self, blob, blob_info):
        pass


class StandaloneBlobDownloader(object):
    def __init__(self, blob_hash, blob_manager, peer_finder,
                 rate_limiter, payment_rate_manager, wallet):
        self.blob_hash = blob_hash
        self.blob_manager = blob_manager
        self.peer_finder = peer_finder
        self.rate_limiter = rate_limiter
        self.payment_rate_manager = payment_rate_manager
        self.wallet = wallet
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
        self.download_manager.progress_manager = SingleProgressManager(self._blob_downloaded,
                                                                       self.download_manager)
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

    def insufficient_funds(self, err):
        self.stop()
        if not self.finished_deferred.called:
            self.finished_deferred.errback(err)
