import binascii
from lbrynet.core.DownloadOption import DownloadOption
from lbrynet.cryptstream.client.CryptStreamDownloader import CryptStreamDownloader
from zope.interface import implements
from lbrynet.lbrylive.client.LiveStreamMetadataHandler import LiveStreamMetadataHandler
from lbrynet.lbrylive.client.LiveStreamProgressManager import LiveStreamProgressManager
import os
from lbrynet.lbrylive.StreamDescriptor import save_sd_info
from lbrynet.lbrylive.PaymentRateManager import LiveStreamPaymentRateManager
from twisted.internet import defer, threads  # , process
from lbrynet.interfaces import IStreamDownloaderFactory


class LiveStreamDownloader(CryptStreamDownloader):

    def __init__(self, stream_hash, peer_finder, rate_limiter, blob_manager, stream_info_manager,
                 payment_rate_manager, wallet, upload_allowed):
        CryptStreamDownloader.__init__(self, peer_finder, rate_limiter, blob_manager,
                                       payment_rate_manager, wallet, upload_allowed)
        self.stream_hash = stream_hash
        self.stream_info_manager = stream_info_manager
        self.public_key = None

    def set_stream_info(self):
        if self.public_key is None and self.key is None:

            d = self.stream_info_manager.get_stream_info(self.stream_hash)

            def set_stream_info(stream_info):
                public_key, key, stream_name = stream_info
                self.public_key = public_key
                self.key = binascii.unhexlify(key)
                self.stream_name = binascii.unhexlify(stream_name)

            d.addCallback(set_stream_info)
            return d
        else:
            return defer.succeed(True)


class LBRYLiveStreamDownloader(LiveStreamDownloader):
    def __init__(self, stream_hash, peer_finder, rate_limiter, blob_manager, stream_info_manager,
                 payment_rate_manager, wallet, upload_allowed):
        LiveStreamDownloader.__init__(self, stream_hash, peer_finder, rate_limiter, blob_manager,
                                      stream_info_manager, payment_rate_manager, wallet, upload_allowed)

        #self.writer = process.ProcessWriter(reactor, self, 'write', 1)

    def _get_metadata_handler(self, download_manager):
        return LiveStreamMetadataHandler(self.stream_hash, self.stream_info_manager,
                                         self.peer_finder, self.public_key, False,
                                         self.payment_rate_manager, self.wallet, download_manager, 10)

    def _get_progress_manager(self, download_manager):
        return LiveStreamProgressManager(self._finished_downloading, self.blob_manager, download_manager,
                                         delete_blob_after_finished=True, download_whole=False,
                                         max_before_skip_ahead=10)

    def _get_write_func(self):
        def write_func(data):
            if self.stopped is False:
                #self.writer.write(data)
                pass
        return write_func


class FullLiveStreamDownloader(LiveStreamDownloader):
    def __init__(self, stream_hash, peer_finder, rate_limiter, blob_manager, stream_info_manager,
                 payment_rate_manager, wallet, upload_allowed):
        LiveStreamDownloader.__init__(self, stream_hash, peer_finder, rate_limiter,
                                      blob_manager, stream_info_manager, payment_rate_manager,
                                      wallet, upload_allowed)
        self.file_handle = None
        self.file_name = None

    def set_stream_info(self):
        d = LiveStreamDownloader.set_stream_info(self)

        def set_file_name_if_unset():
            if not self.file_name:
                if not self.stream_name:
                    self.stream_name = "_"
                self.file_name = os.path.basename(self.stream_name)

        d.addCallback(lambda _: set_file_name_if_unset())
        return d

    def stop(self):
        d = self._close_file()
        d.addBoth(lambda _: LiveStreamDownloader.stop(self))
        return d

    def _start(self):
        if self.file_handle is None:
            d = self._open_file()
        else:
            d = defer.succeed(True)
        d.addCallback(lambda _: LiveStreamDownloader._start(self))
        return d

    def _open_file(self):
        def open_file():
            self.file_handle = open(self.file_name, 'wb')
        return threads.deferToThread(open_file)

    def _get_metadata_handler(self, download_manager):
        return LiveStreamMetadataHandler(self.stream_hash, self.stream_info_manager,
                                         self.peer_finder, self.public_key, True,
                                         self.payment_rate_manager, self.wallet, download_manager)

    def _get_primary_request_creators(self, download_manager):
        return [download_manager.blob_requester, download_manager.blob_info_finder]

    def _get_write_func(self):
        def write_func(data):
            if self.stopped is False:
                self.file_handle.write(data)
        return write_func

    def _close_file(self):
        def close_file():
            if self.file_handle is not None:
                self.file_handle.close()
                self.file_handle = None
        return threads.deferToThread(close_file)


class FullLiveStreamDownloaderFactory(object):

    implements(IStreamDownloaderFactory)

    def __init__(self, peer_finder, rate_limiter, blob_manager, stream_info_manager, wallet,
                 default_payment_rate_manager):
        self.peer_finder = peer_finder
        self.rate_limiter = rate_limiter
        self.blob_manager = blob_manager
        self.stream_info_manager = stream_info_manager
        self.wallet = wallet
        self.default_payment_rate_manager = default_payment_rate_manager

    def get_downloader_options(self, sd_validator, payment_rate_manager):
        options = [
            DownloadOption(
                [float, None],
                "rate which will be paid for data (None means use application default)",
                "data payment rate",
                None
            ),
            DownloadOption(
                [float, None],
                "rate which will be paid for metadata (None means use application default)",
                "metadata payment rate",
                None
            ),
            DownloadOption(
                [bool],
                "allow reuploading data downloaded for this file",
                "allow upload",
                True
            ),
        ]
        return options

    def make_downloader(self, sd_validator, options, payment_rate_manager):
        # TODO: check options for payment rate manager parameters
        payment_rate_manager = LiveStreamPaymentRateManager(self.default_payment_rate_manager,
                                                            payment_rate_manager)
        d = save_sd_info(self.stream_info_manager, sd_validator.raw_info)

        def create_downloader(stream_hash):
            stream_downloader = FullLiveStreamDownloader(stream_hash, self.peer_finder, self.rate_limiter,
                                                         self.blob_manager, self.stream_info_manager,
                                                         payment_rate_manager, self.wallet, True)
            # TODO: change upload_allowed=True above to something better
            d = stream_downloader.set_stream_info()
            d.addCallback(lambda _: stream_downloader)
            return d

        d.addCallback(create_downloader)
        return d