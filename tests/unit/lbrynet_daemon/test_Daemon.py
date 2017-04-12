import mock
import json
import requests
from tests.mocks import BlobAvailabilityTracker as DummyBlobAvailabilityTracker
from tests import util
from twisted.internet import defer
from twisted.internet import reactor
from twisted.trial import unittest
from lbryschema.decode import smart_decode
from lbrynet.lbrynet_daemon import Daemon
from lbrynet.core import Session, PaymentRateManager, Wallet
from lbrynet.lbrynet_daemon.Daemon import Daemon as LBRYDaemon
from lbrynet.lbrynet_daemon import ExchangeRateManager
from lbrynet import conf
from tests.mocks import mock_conf_settings, FakeNetwork


class MiscTests(unittest.TestCase):
    def test_get_lbry_electron_client_version_from_github(self):
        response = mock.create_autospec(requests.Response)
        # don't need to mock out the entire response from the api
        # but at least need 'tag_name'
        response.json.return_value = {
            "url": "https://api.github.com/repos/lbryio/lbry/releases/3685199",
            "assets_url": "https://api.github.com/repos/lbryio/lbry/releases/3685199/assets",
            "html_url": "https://github.com/lbryio/lbry/releases/tag/v0.3.8",
            "id": 3685199,
            "tag_name": "v0.3.8",
            "prerelease": False
        }
        with mock.patch('lbrynet.lbrynet_daemon.Daemon.requests') as req:
            req.get.return_value = response
            rv = Daemon.CheckRemoteVersion()
            rv._get_lbry_electron_client_version()
            self.assertEqual('0.3.8', rv.version)

    def test_error_is_thrown_if_prerelease(self):
        response = mock.create_autospec(requests.Response)
        response.json.return_value = {
            "tag_name": "v0.3.8",
            "prerelease": True
        }
        with mock.patch('lbrynet.lbrynet_daemon.Daemon.requests') as req:
            req.get.return_value = response
            rv = Daemon.CheckRemoteVersion()
            with self.assertRaises(Exception):
                rv._get_lbry_electron_client_version()

    def test_error_is_thrown_when_version_cant_be_parsed(self):
        with self.assertRaises(Exception):
            Daemon.get_version_from_tag('garbage')


def get_test_daemon(data_rate=None, generous=True, with_fee=False):
    if data_rate is None:
        data_rate = conf.ADJUSTABLE_SETTINGS['data_rate'][1]

    rates = {
        'BTCLBC': {'spot': 3.0, 'ts': util.DEFAULT_ISO_TIME + 1},
        'USDBTC': {'spot': 2.0, 'ts': util.DEFAULT_ISO_TIME + 2}
    }
    daemon = LBRYDaemon(None, None)
    daemon.session = mock.Mock(spec=Session.Session)
    daemon.session.wallet = mock.Mock(spec=Wallet.LBRYumWallet)
    daemon.exchange_rate_manager = ExchangeRateManager.DummyExchangeRateManager(rates)
    base_prm = PaymentRateManager.BasePaymentRateManager(rate=data_rate)
    prm = PaymentRateManager.NegotiatedPaymentRateManager(base_prm, DummyBlobAvailabilityTracker(),
                                                          generous=generous)
    daemon.session.payment_rate_manager = prm
    metadata = {
        "author": "fake author",
        "language": "en",
        "content_type": "fake/format",
        "description": "fake description",
        "license": "fake license",
        "license_url": "fake license url",
        "nsfw": False,
        "sources": {
            "lbry_sd_hash": "d2b8b6e907dde95245fe6d144d16c2fdd60c4e0c6463ec98b85642d06d8e9414e8fcfdcb7cb13532ec5454fb8fe7f280"
        },
        "thumbnail": "fake thumbnail",
        "title": "fake title",
        "ver": "0.0.3"
    }
    if with_fee:
        metadata.update(
            {"fee": {"USD": {"address": "bQ6BGboPV2SpTMEP7wLNiAcnsZiH8ye6eA", "amount": 0.75}}})
    daemon._resolve_name = lambda _: defer.succeed(metadata)
    migrated = smart_decode(json.dumps(metadata))
    daemon.session.wallet.resolve_uri = lambda _: defer.succeed({'claim': {'value': migrated.claim_dict}})
    return daemon


class TestCostEst(unittest.TestCase):
    def setUp(self):
        mock_conf_settings(self)
        util.resetTime(self)

    def test_fee_and_generous_data(self):
        size = 10000000
        correct_result = 4.5
        daemon = get_test_daemon(generous=True, with_fee=True)
        print daemon.get_est_cost("test", size)
        self.assertEquals(daemon.get_est_cost("test", size).result, correct_result)

    def test_fee_and_ungenerous_data(self):
        size = 10000000
        fake_fee_amount = 4.5
        data_rate = conf.ADJUSTABLE_SETTINGS['data_rate'][1]
        correct_result = size / 10 ** 6 * data_rate + fake_fee_amount
        daemon = get_test_daemon(generous=False, with_fee=True)
        self.assertEquals(daemon.get_est_cost("test", size).result, correct_result)

    def test_generous_data_and_no_fee(self):
        size = 10000000
        correct_result = 0.0
        daemon = get_test_daemon(generous=True)
        self.assertEquals(daemon.get_est_cost("test", size).result, correct_result)

    def test_ungenerous_data_and_no_fee(self):
        size = 10000000
        data_rate = conf.ADJUSTABLE_SETTINGS['data_rate'][1]
        correct_result = size / 10 ** 6 * data_rate
        daemon = get_test_daemon(generous=False)
        self.assertEquals(daemon.get_est_cost("test", size).result, correct_result)


class TestJsonRpc(unittest.TestCase):
    def setUp(self):
        def noop():
            return None

        mock_conf_settings(self)
        util.resetTime(self)
        self.test_daemon = get_test_daemon()
        self.test_daemon.session.wallet = Wallet.LBRYumWallet(storage=Wallet.InMemoryStorage())
        self.test_daemon.session.wallet.network = FakeNetwork()
        self.test_daemon.session.wallet.get_best_blockhash = noop

    def test_status(self):
        d = defer.maybeDeferred(self.test_daemon.jsonrpc_status)
        d.addCallback(lambda status: self.assertDictContainsSubset({'is_running': False}, status))

    def test_help(self):
        d = defer.maybeDeferred(self.test_daemon.jsonrpc_help, command='status')
        d.addCallback(lambda result: self.assertSubstring('daemon status', result['help']))
        # self.assertSubstring('daemon status', d.result)
