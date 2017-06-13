import types
import mock
import json
from twisted.trial import unittest
from twisted.internet import defer

from lbryschema.claim import ClaimDict

from lbrynet.core import Session, PaymentRateManager, Wallet
from lbrynet.daemon import Downloader
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier,StreamMetadata
from lbrynet.lbry_file.client.EncryptedFileOptions import add_lbry_file_to_sd_identifier
from lbrynet.core.HashBlob import TempBlob
from lbrynet.core.BlobManager import TempBlobManager
from lbrynet.file_manager.EncryptedFileDownloader import ManagedEncryptedFileDownloaderFactory
from lbrynet.daemon.ExchangeRateManager import ExchangeRateManager

from tests.mocks import BlobAvailabilityTracker as DummyBlobAvailabilityTracker
from tests.mocks import ExchangeRateManager as DummyExchangeRateManager
from tests.mocks import BTCLBCFeed, USDBTCFeed
from tests.mocks import mock_conf_settings

class GetStreamTests(unittest.TestCase):

    def init_getstream_with_mocs(self):
        mock_conf_settings(self)
        sd_identifier = mock.Mock(spec=StreamDescriptorIdentifier)
        session = mock.Mock(spec=Session.Session)
        session.wallet = mock.Mock(spec=Wallet.LBRYumWallet)
        prm = mock.Mock(spec=PaymentRateManager.NegotiatedPaymentRateManager)
        session.payment_rate_manager = prm
        market_feeds = []
        rates={}
        exchange_rate_manager = DummyExchangeRateManager(market_feeds, rates)
        exchange_rate_manager = mock.Mock(spec=ExchangeRateManager)
        max_key_fee = {'currency':"LBC", 'amount':10, 'address':''}
        data_rate = {'currency':"LBC", 'amount':0, 'address':''}

        getstream = Downloader.GetStream(sd_identifier, session,
            exchange_rate_manager, max_key_fee, timeout=10, data_rate=data_rate)

        return getstream

    @defer.inlineCallbacks
    def test_init_exception(self):
        """
        test that if initialization would fail, by giving it invaild
        stream_info, that an exception is thrown
        """

        getstream = self.init_getstream_with_mocs()
        name = 'test'
        stream_info = None

        with self.assertRaises(AttributeError):
            yield getstream.start(stream_info,name)


