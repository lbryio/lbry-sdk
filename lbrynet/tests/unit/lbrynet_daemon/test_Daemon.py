import mock
import json
import unittest
from os import path

from twisted.internet import defer
from twisted import trial

from faker import Faker

from lbryschema.decode import smart_decode
from lbryum.wallet import NewWallet
from lbrynet import conf
from lbrynet.core import Session, PaymentRateManager, Wallet
from lbrynet.database.storage import SQLiteStorage
from lbrynet.daemon.Daemon import Daemon as LBRYDaemon
from lbrynet.file_manager.EncryptedFileManager import EncryptedFileManager
from lbrynet.file_manager.EncryptedFileDownloader import ManagedEncryptedFileDownloader

from lbrynet.tests import util
from lbrynet.tests.mocks import mock_conf_settings, FakeNetwork
from lbrynet.tests.mocks import BlobAvailabilityTracker as DummyBlobAvailabilityTracker
from lbrynet.tests.mocks import ExchangeRateManager as DummyExchangeRateManager
from lbrynet.tests.mocks import BTCLBCFeed, USDBTCFeed
from lbrynet.tests.util import is_android


import logging
logging.getLogger("lbryum").setLevel(logging.WARNING)


def get_test_daemon(data_rate=None, generous=True, with_fee=False):
    if data_rate is None:
        data_rate = conf.ADJUSTABLE_SETTINGS['data_rate'][1]

    rates = {
        'BTCLBC': {'spot': 3.0, 'ts': util.DEFAULT_ISO_TIME + 1},
        'USDBTC': {'spot': 2.0, 'ts': util.DEFAULT_ISO_TIME + 2}
    }
    daemon = LBRYDaemon(None)
    daemon.session = mock.Mock(spec=Session.Session)
    daemon.session.wallet = mock.Mock(spec=Wallet.LBRYumWallet)
    daemon.session.wallet.wallet = mock.Mock(spec=NewWallet)
    daemon.session.wallet.wallet.use_encryption = False
    daemon.session.wallet.network = FakeNetwork()
    daemon.session.storage = mock.Mock(spec=SQLiteStorage)
    market_feeds = [BTCLBCFeed(), USDBTCFeed()]
    daemon.exchange_rate_manager = DummyExchangeRateManager(market_feeds, rates)
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
            "lbry_sd_hash": 'd2b8b6e907dde95245fe6d144d16c2fdd60c4e0c6463ec98'
                            'b85642d06d8e9414e8fcfdcb7cb13532ec5454fb8fe7f280'
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
    daemon.session.wallet.resolve = lambda *_: defer.succeed(
        {"test": {'claim': {'value': migrated.claim_dict}}})
    return daemon


class TestCostEst(trial.unittest.TestCase):
    def setUp(self):
        mock_conf_settings(self)
        util.resetTime(self)

    def test_fee_and_generous_data(self):
        size = 10000000
        correct_result = 4.5
        daemon = get_test_daemon(generous=True, with_fee=True)
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


class TestJsonRpc(trial.unittest.TestCase):
    def setUp(self):
        def noop():
            return None

        mock_conf_settings(self)
        util.resetTime(self)
        self.test_daemon = get_test_daemon()
        self.test_daemon.session.wallet.is_first_run = False
        self.test_daemon.session.wallet.get_best_blockhash = noop

    def test_status(self):
        d = defer.maybeDeferred(self.test_daemon.jsonrpc_status)
        d.addCallback(lambda status: self.assertDictContainsSubset({'is_running': False}, status))

    @unittest.skipIf(is_android(),
                     'Test cannot pass on Android because PYTHONOPTIMIZE removes the docstrings.')
    def test_help(self):
        d = defer.maybeDeferred(self.test_daemon.jsonrpc_help, command='status')
        d.addCallback(lambda result: self.assertSubstring('daemon status', result['help']))
        # self.assertSubstring('daemon status', d.result)


class TestFileListSorting(trial.unittest.TestCase):
    def setUp(self):
        mock_conf_settings(self)
        util.resetTime(self)
        self.faker = Faker('en_US')
        self.faker.seed(66410)
        self.test_daemon = get_test_daemon()
        self.test_daemon.lbry_file_manager = mock.Mock(spec=EncryptedFileManager)
        self.test_daemon.lbry_file_manager.lbry_files = self._get_fake_lbry_files()

        # Pre-sorted lists of prices and file names in ascending order produced by
        # faker with seed 66410. This seed was chosen becacuse it produces 3 results
        # 'points_paid' at 6.0 and 2 results at 4.5 to test multiple sort criteria.
        self.test_prices = [0.2, 2.9, 4.5, 4.5, 6.0, 6.0, 6.0, 6.8, 7.1, 9.2]
        self.test_file_names = ['also.mp3', 'better.css', 'call.mp3', 'pay.jpg',
                                'record.pages', 'sell.css', 'strategy.pages',
                                'thousand.pages', 'town.mov', 'vote.ppt']

    @defer.inlineCallbacks
    def test_sort_by_price_no_direction_specified(self):
        sort_options = ['price']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        received = [f['points_paid'] for f in file_list]
        self.assertEquals(self.test_prices, received)

    @defer.inlineCallbacks
    def test_sort_by_price_ascending(self):
        sort_options = ['price,asc']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        received = [f['points_paid'] for f in file_list]
        self.assertEquals(self.test_prices, received)

    @defer.inlineCallbacks
    def test_sort_by_price_descending(self):
        sort_options = ['price, desc']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        received = [f['points_paid'] for f in file_list]
        expected = list(reversed(self.test_prices))
        self.assertEquals(expected, received)

    @defer.inlineCallbacks
    def test_sort_by_name_no_direction_specified(self):
        sort_options = ['name']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        received = [f['file_name'] for f in file_list]
        self.assertEquals(self.test_file_names, received)

    @defer.inlineCallbacks
    def test_sort_by_name_ascending(self):
        sort_options = ['name,\nasc']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        received = [f['file_name'] for f in file_list]
        self.assertEquals(self.test_file_names, received)

    @defer.inlineCallbacks
    def test_sort_by_name_descending(self):
        sort_options = ['\tname,\n\tdesc']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        received = [f['file_name'] for f in file_list]
        expected = list(reversed(self.test_file_names))
        self.assertEquals(expected, received)

    @defer.inlineCallbacks
    def test_sort_by_multiple_criteria(self):
        sort_options = ['name,asc', 'price,desc']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        received = ['name={}, price={}'.format(f['file_name'], f['points_paid']) for f in file_list]
        expected = ['name=record.pages, price=9.2',
                     'name=vote.ppt, price=7.1',
                     'name=strategy.pages, price=6.8',
                     'name=also.mp3, price=6.0',
                     'name=better.css, price=6.0',
                     'name=town.mov, price=6.0',
                     'name=sell.css, price=4.5',
                     'name=thousand.pages, price=4.5',
                     'name=call.mp3, price=2.9',
                     'name=pay.jpg, price=0.2']
        self.assertEquals(expected, received)

        # Check that the list is not sorted as expected when sorted only by name.
        sort_options = ['name,asc']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        received = ['name={}, price={}'.format(f['file_name'], f['points_paid']) for f in file_list]
        self.assertNotEqual(expected, received)

        # Check that the list is not sorted as expected when sorted only by price.
        sort_options = ['price,desc']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        received = ['name={}, price={}'.format(f['file_name'], f['points_paid']) for f in file_list]
        self.assertNotEqual(expected, received)

        # Check that the list is not sorted as expected when not sorted at all.
        file_list = yield self.test_daemon.jsonrpc_file_list()
        received = ['name={}, price={}'.format(f['file_name'], f['points_paid']) for f in file_list]
        self.assertNotEqual(expected, received)

    def _get_fake_lbry_files(self):
        return [self._get_fake_lbry_file() for _ in range(10)]

    def _get_fake_lbry_file(self):
        lbry_file = mock.Mock(spec=ManagedEncryptedFileDownloader)

        file_path = self.faker.file_path()
        stream_name = self.faker.file_name()
        faked_attributes = {
            'channel_claim_id': self.faker.sha1(),
            'channel_name': '@' + self.faker.simple_profile()['username'],
            'claim_id': self.faker.sha1(),
            'claim_name': '-'.join(self.faker.words(4)),
            'completed': self.faker.boolean(),
            'download_directory': path.dirname(file_path),
            'download_path': file_path,
            'file_name': path.basename(file_path),
            'key': self.faker.md5(),
            'metadata': {},
            'mime_type': self.faker.mime_type(),
            'nout': abs(self.faker.pyint()),
            'outpoint': self.faker.md5() + self.faker.md5(),
            'points_paid': self.faker.pyfloat(left_digits=1, right_digits=1, positive=True),
            'sd_hash': self.faker.md5() + self.faker.md5() + self.faker.md5(),
            'stopped': self.faker.boolean(),
            'stream_hash': self.faker.md5() + self.faker.md5() + self.faker.md5(),
            'stream_name': stream_name,
            'suggested_file_name': stream_name,
            'txid': self.faker.md5() + self.faker.md5(),
            'written_bytes': self.faker.pyint(),
        }

        for key in faked_attributes:
            setattr(lbry_file, key, faked_attributes[key])

        return lbry_file
