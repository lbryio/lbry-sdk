import logging
from zope.interface import implements
from lbrynet.interfaces import IStreamDownloader
from lbrynet.core.client.BlobRequester import BlobRequester
from lbrynet.core.client.ConnectionManager import ConnectionManager
from lbrynet.core.client.DownloadManager import DownloadManager
from lbrynet.core.client.StreamProgressManager import FullStreamProgressManager
from lbrynet.cryptstream.client.CryptBlobHandler import CryptBlobHandler
from twisted.internet import defer
from twisted.python.failure import Failure


log = logging.getLogger(__name__)


class StartFailedError(Exception):
    pass


class AlreadyRunningError(Exception):
    pass


class AlreadyStoppedError(Exception):
    pass


class CurrentlyStoppingError(Exception):
    pass


class CurrentlyStartingError(Exception):
    pass


class CryptStreamDownloader(object):

    implements(IStreamDownloader)

    def __init__(self, peer_finder, rate_limiter, blob_manager,
                 payment_rate_manager, wallet):
        """Initialize a CryptStreamDownloader

        @param peer_finder: An object which implements the IPeerFinder
        interface. Used to look up peers by a hashsum.

        @param rate_limiter: An object which implements the IRateLimiter interface

        @param blob_manager: A BlobManager object

        @param payment_rate_manager: A NegotiatedPaymentRateManager object

        @param wallet: An object which implements the IWallet interface

        @return:

        """

        self.peer_finder = peer_finder
        self.rate_limiter = rate_limiter
        self.blob_manager = blob_manager
        self.payment_rate_manager = payment_rate_manager
        self.wallet = wallet
        self.key = None
        self.stream_name = None
        self.completed = False
        self.stopped = True
        self.stopping = False
        self.starting = False
        self.download_manager = None
        self.finished_deferred = None
        self.points_paid = 0.0
        self.blob_requester = None

    def __str__(self):
        return str(self.stream_name)

    def toggle_running(self):
        if self.stopped is True:
            return self.start()
        else:
            return self.stop()

    def start(self):
        if self.starting is True:
            raise CurrentlyStartingError()
        if self.stopping is True:
            raise CurrentlyStoppingError()
        if self.stopped is False:
            raise AlreadyRunningError()
        assert self.download_manager is None
        self.starting = True
        self.completed = False
        self.finished_deferred = defer.Deferred()
        d = self._start()
        d.addCallback(lambda _: self.finished_deferred)
        return d

    @defer.inlineCallbacks
    def stop(self, err=None):
        if self.stopped is True:
            raise AlreadyStoppedError()
        if self.stopping is True:
            raise CurrentlyStoppingError()
        assert self.download_manager is not None
        self.stopping = True
        success = yield self.download_manager.stop_downloading()
        self.stopping = False
        if success is True:
            self.stopped = True
            self._remove_download_manager()
        yield self._fire_completed_deferred(err)

    def _start_failed(self):

        def set_stopped():
            self.stopped = True
            self.stopping = False
            self.starting = False

        if self.download_manager is not None:
            d = self.download_manager.stop_downloading()
            d.addCallback(lambda _: self._remove_download_manager())
        else:
            d = defer.succeed(True)
        d.addCallback(lambda _: set_stopped())
        d.addCallback(lambda _: Failure(StartFailedError()))
        return d

    def _start(self):

        def check_start_succeeded(success):
            if success:
                self.starting = False
                self.stopped = False
                self.completed = False
                return True
            else:
                return self._start_failed()

        self.download_manager = self._get_download_manager()
        d = self.download_manager.start_downloading()
        d.addCallbacks(check_start_succeeded)
        return d

    def _get_download_manager(self):
        assert self.blob_requester is None
        download_manager = DownloadManager(self.blob_manager)
        # TODO: can we get rid of these circular references. I'm not
        #       smart enough to handle thinking about the interactions
        #       between them and have hope that there is a simpler way
        #       to accomplish what we want
        download_manager.blob_info_finder = self._get_metadata_handler(download_manager)
        download_manager.progress_manager = self._get_progress_manager(download_manager)
        download_manager.blob_handler = self._get_blob_handler(download_manager)
        download_manager.wallet_info_exchanger = self.wallet.get_info_exchanger()
        # blob_requester needs to be set before the connection manager is setup
        self.blob_requester = self._get_blob_requester(download_manager)
        download_manager.connection_manager = self._get_connection_manager(download_manager)
        return download_manager

    def _remove_download_manager(self):
        self.download_manager.blob_info_finder = None
        self.download_manager.progress_manager = None
        self.download_manager.blob_handler = None
        self.download_manager.wallet_info_exchanger = None
        self.blob_requester = None
        self.download_manager.connection_manager = None
        self.download_manager = None

    def _get_primary_request_creators(self, download_manager):
        return [self.blob_requester]

    def _get_secondary_request_creators(self, download_manager):
        return [download_manager.wallet_info_exchanger]

    def _get_metadata_handler(self, download_manager):
        pass

    def _get_blob_requester(self, download_manager):
        return BlobRequester(self.blob_manager, self.peer_finder,
                             self.payment_rate_manager, self.wallet,
                             download_manager)

    def _get_progress_manager(self, download_manager):
        return FullStreamProgressManager(self._finished_downloading,
                                         self.blob_manager, download_manager)

    def _get_write_func(self):
        pass

    def _get_blob_handler(self, download_manager):
        return CryptBlobHandler(self.key, self._get_write_func())

    def _get_connection_manager(self, download_manager):
        return ConnectionManager(self, self.rate_limiter,
                                 self._get_primary_request_creators(download_manager),
                                 self._get_secondary_request_creators(download_manager))

    def _fire_completed_deferred(self, err=None):
        self.finished_deferred, d = None, self.finished_deferred
        if d is not None:
            if err is not None:
                d.errback(err)
            else:
                value = self._get_finished_deferred_callback_value()
                d.callback(value)
        else:
            log.debug("Not firing the completed deferred because d is None")

    def _get_finished_deferred_callback_value(self):
        return None

    def _finished_downloading(self, finished):
        if finished is True:
            self.completed = True
        return self.stop()

    def insufficient_funds(self, err):
        return self.stop(err=err)
