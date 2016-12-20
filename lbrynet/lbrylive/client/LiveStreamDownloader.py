# pylint: skip-file
import binascii
from lbrynet.core.StreamDescriptor import StreamMetadata
from lbrynet.cryptstream.client.CryptStreamDownloader import CryptStreamDownloader
from zope.interface import implements
from lbrynet.lbrylive.client.LiveStreamMetadataHandler import LiveStreamMetadataHandler
from lbrynet.lbrylive.client.LiveStreamProgressManager import LiveStreamProgressManager
import os
from lbrynet.lbrylive.StreamDescriptor import save_sd_info
from lbrynet.lbrylive.PaymentRateManager import LiveStreamPaymentRateManager
from twisted.internet import defer, threads  # , process
from lbrynet.interfaces import IStreamDownloaderFactory
from lbrynet.lbrylive.StreamDescriptor import LiveStreamType


class _LiveStreamDownloader(CryptStreamDownloader):

    def __init__(self, stream_hash, peer_finder, rate_limiter, blob_manager, stream_info_manager,
                 payment_rate_manager, wallet):
        CryptStreamDownloader.__init__(self, peer_finder, rate_limiter, blob_manager,
                                       payment_rate_manager, wallet)
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


class LiveStreamDownloader(_LiveStreamDownloader):
    def __init__(self, stream_hash, peer_finder, rate_limiter, blob_manager, stream_info_manager,
                 payment_rate_manager, wallet):
        _LiveStreamDownloader.__init__(self, stream_hash, peer_finder, rate_limiter, blob_manager,
                                      stream_info_manager, payment_rate_manager, wallet)


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
                pass
        return write_func


class FullLiveStreamDownloader(_LiveStreamDownloader):
    def __init__(self, stream_hash, peer_finder, rate_limiter, blob_manager, stream_info_manager,
                 payment_rate_manager, wallet):
        _LiveStreamDownloader.__init__(self, stream_hash, peer_finder, rate_limiter,
                                      blob_manager, stream_info_manager, payment_rate_manager,
                                      wallet)
        self.file_handle = None
        self.file_name = None

    def set_stream_info(self):
        d = _LiveStreamDownloader.set_stream_info(self)

        def set_file_name_if_unset():
            if not self.file_name:
                if not self.stream_name:
                    self.stream_name = "_"
                self.file_name = os.path.basename(self.stream_name)

        d.addCallback(lambda _: set_file_name_if_unset())
        return d

    def stop(self, err=None):
        d = self._close_file()
        d.addBoth(lambda _: _LiveStreamDownloader.stop(self, err))
        return d

    def _start(self):
        if self.file_handle is None:
            d = self._open_file()
        else:
            d = defer.succeed(True)
        d.addCallback(lambda _: _LiveStreamDownloader._start(self))
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

    def can_download(self, sd_validator):
        return True

    def make_downloader(self, metadata, options, payment_rate_manager):
        # TODO: check options for payment rate manager parameters
        prm = LiveStreamPaymentRateManager(self.default_payment_rate_manager,
                                                            payment_rate_manager)

        def save_source_if_blob(stream_hash):
            if metadata.metadata_source == StreamMetadata.FROM_BLOB:
                d = self.stream_info_manager.save_sd_blob_hash_to_stream(stream_hash, metadata.source_blob_hash)
            else:
                d = defer.succeed(True)
            d.addCallback(lambda _: stream_hash)
            return d

        d = save_sd_info(self.stream_info_manager, metadata.validator.raw_info)
        d.addCallback(save_source_if_blob)

        def create_downloader(stream_hash):
            stream_downloader = FullLiveStreamDownloader(stream_hash, self.peer_finder, self.rate_limiter,
                                                         self.blob_manager, self.stream_info_manager,
                                                         prm, self.wallet, True)
            d = stream_downloader.set_stream_info()
            d.addCallback(lambda _: stream_downloader)
            return d

        d.addCallback(create_downloader)
        return d


def add_full_live_stream_downloader_to_sd_identifier(session, stream_info_manager, sd_identifier,
                                                     base_live_stream_payment_rate_manager):
    downloader_factory = FullLiveStreamDownloaderFactory(session.peer_finder,
                                                         session.rate_limiter,
                                                         session.blob_manager,
                                                         stream_info_manager,
                                                         session.wallet,
                                                         base_live_stream_payment_rate_manager)
    sd_identifier.add_stream_downloader_factory(LiveStreamType, downloader_factory)
