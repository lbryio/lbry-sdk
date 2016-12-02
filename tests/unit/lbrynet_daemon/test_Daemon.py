import mock
import requests
from tests.mocks import BlobAvailabilityTracker as DummyBlobAvailabilityTracker
from tests import util
from twisted.internet import defer
from twisted.trial import unittest
from lbrynet.lbrynet_daemon import Daemon
from lbrynet.core import Session, PaymentRateManager
from lbrynet.lbrynet_daemon.Daemon import Daemon as LBRYDaemon
from lbrynet.lbrynet_daemon import ExchangeRateManager
from lbrynet import conf


class MiscTests(unittest.TestCase):
    def test_get_lbrynet_version_from_github(self):
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
            self.assertEqual('0.3.8', Daemon.get_lbrynet_version_from_github())

    def test_error_is_thrown_if_prerelease(self):
        response = mock.create_autospec(requests.Response)
        response.json.return_value = {
            "tag_name": "v0.3.8",
            "prerelease": True
        }
        with mock.patch('lbrynet.lbrynet_daemon.Daemon.requests') as req:
            req.get.return_value = response
            with self.assertRaises(Exception):
                Daemon.get_lbrynet_version_from_github()

    def test_error_is_thrown_when_version_cant_be_parsed(self):
        with self.assertRaises(Exception):
            Daemon.get_version_from_tag('garbage')


def get_test_daemon(data_rate=conf.settings.data_rate, generous=True, with_fee=False):
    rates = {
                'BTCLBC': {'spot': 3.0, 'ts': util.DEFAULT_ISO_TIME + 1},
                'USDBTC': {'spot': 2.0, 'ts': util.DEFAULT_ISO_TIME + 2}
            }
    daemon = LBRYDaemon(None, None)
    daemon.session = mock.Mock(spec=Session.Session)
    daemon.exchange_rate_manager = ExchangeRateManager.DummyExchangeRateManager(rates)
    base_prm = PaymentRateManager.BasePaymentRateManager(rate=data_rate)
    prm = PaymentRateManager.NegotiatedPaymentRateManager(base_prm, DummyBlobAvailabilityTracker(), generous=generous)
    daemon.session.payment_rate_manager = prm
    metadata = {
        "author": "extra",
        "content_type": "video/mp4",
        "description": "How did the ancient civilization of Sumer first develop the concept of the written word? It all began with simple warehouse tallies in the temples, but as the scribes sought more simple ways to record information, those tallies gradually evolved from pictograms into cuneiform text which could be used to convey complex, abstract, or even lyrical ideas.",
        "language": "en",
        "license": "Creative Commons Attribution 3.0 United States",
        "license_url": "https://creativecommons.org/licenses/by/3.0/us/legalcode",
        "nsfw": False,
        "sources": {
            "lbry_sd_hash": "d2b8b6e907dde95245fe6d144d16c2fdd60c4e0c6463ec98b85642d06d8e9414e8fcfdcb7cb13532ec5454fb8fe7f280"},
        "thumbnail": "http://i.imgur.com/HFSRkKw.png",
        "title": "The History of Writing - Where the Story Begins",
        "ver": "0.0.3"
    }
    if with_fee:
        metadata.update({"fee": {"USD": {"address": "bQ6BGboPV2SpTMEP7wLNiAcnsZiH8ye6eA", "amount": 0.75}}})
    daemon._resolve_name = lambda x: defer.succeed(metadata)
    return daemon


class TestCostEst(unittest.TestCase):
    def setUp(self):
        util.resetTime(self)

    def test_cost_est_with_fee_and_generous(self):
        size = 10000000
        fake_fee_amount = 4.5
        daemon = get_test_daemon(generous=True, with_fee=True)
        self.assertEquals(daemon.get_est_cost("test", size).result, fake_fee_amount)

    def test_cost_est_with_fee_and_not_generous(self):
        size = 10000000
        fake_fee_amount = 4.5
        data_rate = conf.settings.data_rate
        daemon = get_test_daemon(generous=False, with_fee=True)
        self.assertEquals(daemon.get_est_cost("test", size).result, (size / (10**6) * data_rate) + fake_fee_amount)

    def test_data_cost_with_generous(self):
        size = 10000000
        daemon = get_test_daemon(generous=True)
        self.assertEquals(daemon.get_est_cost("test", size).result, 0.0)

    def test_data_cost_with_non_generous(self):
        size = 10000000
        data_rate = conf.settings.data_rate
        daemon = get_test_daemon(generous=False)
        self.assertEquals(daemon.get_est_cost("test", size).result, (size / (10**6) * data_rate))
