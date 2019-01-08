import types
from unittest import mock
from twisted.trial import unittest
from twisted.internet import defer

from lbrynet.blob_exchange.price_negotiation import payment_rate_manager
from lbrynet.error import DownloadDataTimeout, DownloadSDTimeout
from lbrynet.stream.descriptor import StreamDescriptorIdentifier
from lbrynet.blob.blob_manager import BlobFileManager
from lbrynet.staging.old_blob_client import DownloadManager
from lbrynet.staging.rate_limiter import RateLimiter
from lbrynet.staging import Downloader
from lbrynet.extras.daemon import ExchangeRateManager
from lbrynet.storage import SQLiteStorage
from lbrynet.staging.PeerFinder import DummyPeerFinder
from lbrynet.staging.EncryptedFileStatusReport import EncryptedFileStatusReport
from lbrynet.staging.EncryptedFileDownloader import ManagedEncryptedFileDownloader
from lbrynet.extras.wallet import LbryWalletManager

from tests.mocks import mock_conf_settings


class MocDownloader:
    def __init__(self):
        self.finish_deferred = defer.Deferred(None)
        self.stop_called = False
        self.file_name = 'test'
        self.name = 'test'
        self.num_completed = 0
        self.num_known = 1
        self.running_status = ManagedEncryptedFileDownloader.STATUS_RUNNING

    @defer.inlineCallbacks
    def status(self):
        out = yield EncryptedFileStatusReport(
            self.name, self.num_completed, self.num_known, self.running_status)
        defer.returnValue(out)

    def start(self):
        return self.finish_deferred

    def stop(self):
        self.stop_called = True
        self.finish_deferred.callback(True)


def moc_initialize(self, stream_info):
    self.sd_hash = "d5169241150022f996fa7cd6a9a1c421937276a3275eb912" \
                   "790bd07ba7aec1fac5fd45431d226b8fb402691e79aeb24b"
    return None


def moc_download_sd_blob(self):
    return None


def moc_download(self, sd_blob, name, txid, nout, key_fee, file_name):
    self.pay_key_fee(key_fee, name)
    self.downloader = MocDownloader()
    self.downloader.start()


def moc_pay_key_fee(d):
    def _moc_pay_key_fee(self, key_fee, name):
        d.callback(True)
    return _moc_pay_key_fee


class GetStreamTests(unittest.TestCase):

    def init_getstream_with_mocs(self):
        mock_conf_settings(self)

        sd_identifier = mock.Mock(spec=StreamDescriptorIdentifier)
        wallet = mock.Mock(spec=LbryWalletManager)
        prm = mock.Mock(spec=payment_rate_manager.NegotiatedPaymentRateManager)
        exchange_rate_manager = mock.Mock(spec=ExchangeRateManager)
        storage = mock.Mock(spec=SQLiteStorage)
        peer_finder = DummyPeerFinder()
        blob_manager = mock.Mock(spec=BlobFileManager)
        max_key_fee = {'currency': "LBC", 'amount': 10, 'address': ''}
        disable_max_key_fee = False
        data_rate = {'currency': "LBC", 'amount': 0, 'address': ''}
        getstream = Downloader.GetStream(
            sd_identifier, wallet, exchange_rate_manager, blob_manager, peer_finder, RateLimiter(), prm,
            storage, max_key_fee, disable_max_key_fee, timeout=3, data_rate=data_rate
        )
        getstream.download_manager = mock.Mock(spec=DownloadManager)
        return getstream

    @defer.inlineCallbacks
    def test_init_exception(self):
        """
        test that if initialization would fail, by giving it invalid
        stream_info, that an exception is thrown
        """

        getstream = self.init_getstream_with_mocs()
        name = 'test'
        stream_info = None

        with self.assertRaises(AttributeError):
            yield getstream.start(stream_info, name, "deadbeef" * 12, 0)

    @defer.inlineCallbacks
    def test_sd_blob_download_timeout(self):
        """
        test that if download_sd_blob fails due to timeout,
        DownloadTimeoutError is raised
        """
        def download_sd_blob(self):
            raise DownloadSDTimeout(self)

        called_pay_fee = defer.Deferred()

        getstream = self.init_getstream_with_mocs()
        getstream._initialize = types.MethodType(moc_initialize, getstream)
        getstream._download_sd_blob = types.MethodType(download_sd_blob, getstream)
        getstream._download = types.MethodType(moc_download, getstream)
        getstream.pay_key_fee = types.MethodType(moc_pay_key_fee(called_pay_fee), getstream)
        name = 'test'
        stream_info = None
        with self.assertRaises(DownloadSDTimeout):
            yield getstream.start(stream_info, name, "deadbeef" * 12, 0)
        self.assertFalse(called_pay_fee.called)

    @defer.inlineCallbacks
    def test_timeout(self):
        """
        test that timeout (set to 3 here) exception is raised
        when download times out while downloading first blob, and key fee is paid
        """
        called_pay_fee = defer.Deferred()

        getstream = self.init_getstream_with_mocs()
        getstream._initialize = types.MethodType(moc_initialize, getstream)
        getstream._download_sd_blob = types.MethodType(moc_download_sd_blob, getstream)
        getstream._download = types.MethodType(moc_download, getstream)
        getstream.pay_key_fee = types.MethodType(moc_pay_key_fee(called_pay_fee), getstream)
        name = 'test'
        stream_info = None
        start = getstream.start(stream_info, name, "deadbeef" * 12, 0)
        with self.assertRaises(DownloadDataTimeout):
            yield start

    @defer.inlineCallbacks
    def test_finish_one_blob(self):
        """
        test that if we have 1 completed blob, start() returns
        and key fee is paid
        """
        called_pay_fee = defer.Deferred()

        getstream = self.init_getstream_with_mocs()
        getstream._initialize = types.MethodType(moc_initialize, getstream)

        getstream._download_sd_blob = types.MethodType(moc_download_sd_blob, getstream)
        getstream._download = types.MethodType(moc_download, getstream)
        getstream.pay_key_fee = types.MethodType(moc_pay_key_fee(called_pay_fee), getstream)
        name = 'test'
        stream_info = None
        self.assertFalse(getstream.wrote_data)
        getstream.data_downloading_deferred.callback(None)
        yield getstream.start(stream_info, name, "deadbeef" * 12, 0)
        self.assertTrue(getstream.wrote_data)

        # self.assertTrue(getstream.pay_key_fee_called)

    # @defer.inlineCallbacks
    # def test_finish_stopped_downloader(self):
    #     """
    #     test that if we have a stopped downloader, beforfe a blob is downloaded,
    #     start() returns
    #     """
    #     getstream  = self.init_getstream_with_mocs()
    #     getstream._initialize = types.MethodType(moc_initialize, getstream)
    #     getstream._download_sd_blob = types.MethodType(moc_download_sd_blob, getstream)
    #     getstream._download = types.MethodType(moc_download, getstream)
    #     name='test'
    #     stream_info = None
    #     start = getstream.start(stream_info,name)
    #
    #     getstream.downloader.running_status = ManagedEncryptedFileDownloader.STATUS_STOPPED
    #     self.clock.advance(1)
    #     downloader, f_deferred = yield start
