import mock
import json
import random
from os import path

from twisted.internet import defer
from twisted.trial import unittest

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
    daemon.wallet = mock.Mock(spec=Wallet.LBRYumWallet)
    daemon.wallet.wallet = mock.Mock(spec=NewWallet)
    daemon.wallet.wallet.use_encryption = False
    daemon.wallet.network = FakeNetwork()
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
    daemon.wallet.resolve = lambda *_: defer.succeed(
        {"test": {'claim': {'value': migrated.claim_dict}}})
    return daemon


class TestCostEst(unittest.TestCase):
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


class TestJsonRpc(unittest.TestCase):
    def setUp(self):
        def noop():
            return None

        mock_conf_settings(self)
        util.resetTime(self)
        self.test_daemon = get_test_daemon()
        self.test_daemon.wallet.is_first_run = False
        self.test_daemon.wallet.get_best_blockhash = noop

    def test_status(self):
        d = defer.maybeDeferred(self.test_daemon.jsonrpc_status)
        d.addCallback(lambda status: self.assertDictContainsSubset({'is_running': False}, status))

    @unittest.skipIf(is_android(),
                     'Test cannot pass on Android because PYTHONOPTIMIZE removes the docstrings.')
    def test_help(self):
        d = defer.maybeDeferred(self.test_daemon.jsonrpc_help, command='status')
        d.addCallback(lambda result: self.assertSubstring('daemon status', result['help']))
        # self.assertSubstring('daemon status', d.result)


class TestFileListSorting(unittest.TestCase):
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
        self.test_points_paid = [0.2, 2.9, 4.5, 4.5, 6.0, 6.0, 6.0, 6.8, 7.1, 9.2]
        self.test_file_names = ['also.mp3', 'better.css', 'call.mp3', 'pay.jpg',
                                'record.pages', 'sell.css', 'strategy.pages',
                                'thousand.pages', 'town.mov', 'vote.ppt']
        self.test_authors = ['angela41', 'edward70', 'fhart', 'johnrosales',
                             'lucasfowler', 'peggytorres', 'qmitchell',
                             'trevoranderson', 'xmitchell', 'zhangsusan']

    def test_sort_by_points_paid_no_direction_specified(self):
        sort_options = ['points_paid']
        deferred = defer.maybeDeferred(self.test_daemon.jsonrpc_file_list, sort=sort_options)
        file_list = self.successResultOf(deferred)
        self.assertEquals(self.test_points_paid, [f['points_paid'] for f in file_list])

    def test_sort_by_points_paid_ascending(self):
        sort_options = ['points_paid,asc']
        deferred = defer.maybeDeferred(self.test_daemon.jsonrpc_file_list, sort=sort_options)
        file_list = self.successResultOf(deferred)
        self.assertEquals(self.test_points_paid, [f['points_paid'] for f in file_list])

    def test_sort_by_points_paid_descending(self):
        sort_options = ['points_paid, desc']
        deferred = defer.maybeDeferred(self.test_daemon.jsonrpc_file_list, sort=sort_options)
        file_list = self.successResultOf(deferred)
        self.assertEquals(list(reversed(self.test_points_paid)), [f['points_paid'] for f in file_list])

    def test_sort_by_file_name_no_direction_specified(self):
        sort_options = ['file_name']
        deferred = defer.maybeDeferred(self.test_daemon.jsonrpc_file_list, sort=sort_options)
        file_list = self.successResultOf(deferred)
        self.assertEquals(self.test_file_names, [f['file_name'] for f in file_list])

    def test_sort_by_file_name_ascending(self):
        sort_options = ['file_name,\nasc']
        deferred = defer.maybeDeferred(self.test_daemon.jsonrpc_file_list, sort=sort_options)
        file_list = self.successResultOf(deferred)
        self.assertEquals(self.test_file_names, [f['file_name'] for f in file_list])

    def test_sort_by_file_name_descending(self):
        sort_options = ['\tfile_name,\n\tdesc']
        deferred = defer.maybeDeferred(self.test_daemon.jsonrpc_file_list, sort=sort_options)
        file_list = self.successResultOf(deferred)
        self.assertEquals(list(reversed(self.test_file_names)), [f['file_name'] for f in file_list])

    def test_sort_by_multiple_criteria(self):
        expected = ['file_name=record.pages, points_paid=9.2',
                     'file_name=vote.ppt, points_paid=7.1',
                     'file_name=strategy.pages, points_paid=6.8',
                     'file_name=also.mp3, points_paid=6.0',
                     'file_name=better.css, points_paid=6.0',
                     'file_name=town.mov, points_paid=6.0',
                     'file_name=sell.css, points_paid=4.5',
                     'file_name=thousand.pages, points_paid=4.5',
                     'file_name=call.mp3, points_paid=2.9',
                     'file_name=pay.jpg, points_paid=0.2']
        format_result = lambda f: 'file_name={}, points_paid={}'.format(f['file_name'], f['points_paid'])

        sort_options = ['file_name,asc', 'points_paid,desc']
        deferred = defer.maybeDeferred(self.test_daemon.jsonrpc_file_list, sort=sort_options)
        file_list = self.successResultOf(deferred)
        self.assertEquals(expected, map(format_result, file_list))

        # Check that the list is not sorted as expected when sorted only by file_name.
        sort_options = ['file_name,asc']
        deferred = defer.maybeDeferred(self.test_daemon.jsonrpc_file_list, sort=sort_options)
        file_list = self.successResultOf(deferred)
        self.assertNotEqual(expected, map(format_result, file_list))

        # Check that the list is not sorted as expected when sorted only by points_paid.
        sort_options = ['points_paid,desc']
        deferred = defer.maybeDeferred(self.test_daemon.jsonrpc_file_list, sort=sort_options)
        file_list = self.successResultOf(deferred)
        self.assertNotEqual(expected, map(format_result, file_list))

        # Check that the list is not sorted as expected when not sorted at all.
        deferred = defer.maybeDeferred(self.test_daemon.jsonrpc_file_list)
        file_list = self.successResultOf(deferred)
        self.assertNotEqual(expected, map(format_result, file_list))

    def test_sort_by_nested_field(self):
        extract_authors = lambda file_list: [f['metadata']['author'] for f in file_list]

        sort_options = ['metadata.author']
        deferred = defer.maybeDeferred(self.test_daemon.jsonrpc_file_list, sort=sort_options)
        file_list = self.successResultOf(deferred)
        self.assertEquals(self.test_authors, extract_authors(file_list))

        # Check that the list matches the expected in reverse when sorting in descending order.
        sort_options = ['metadata.author,desc']
        deferred = defer.maybeDeferred(self.test_daemon.jsonrpc_file_list, sort=sort_options)
        file_list = self.successResultOf(deferred)
        self.assertEquals(list(reversed(self.test_authors)), extract_authors(file_list))

        # Check that the list is not sorted as expected when not sorted at all.
        deferred = defer.maybeDeferred(self.test_daemon.jsonrpc_file_list)
        file_list = self.successResultOf(deferred)
        self.assertNotEqual(self.test_authors, extract_authors(file_list))

    def test_invalid_sort_produces_meaningful_errors(self):
        sort_options = ['meta.author']
        deferred = defer.maybeDeferred(self.test_daemon.jsonrpc_file_list, sort=sort_options)
        failure_assertion = self.assertFailure(deferred, Exception)
        exception = self.successResultOf(failure_assertion)
        expected_message = 'Failed to get "meta.author", key "meta" was not found.'
        self.assertEquals(expected_message, exception.message)

        sort_options = ['metadata.foo.bar']
        deferred = defer.maybeDeferred(self.test_daemon.jsonrpc_file_list, sort=sort_options)
        failure_assertion = self.assertFailure(deferred, Exception)
        exception = self.successResultOf(failure_assertion)
        expected_message = 'Failed to get "metadata.foo.bar", key "foo" was not found.'
        self.assertEquals(expected_message, exception.message)

    def _get_fake_lbry_files(self):
        return [self._get_fake_lbry_file() for _ in range(10)]

    def _get_fake_lbry_file(self):
        lbry_file = mock.Mock(spec=ManagedEncryptedFileDownloader)

        file_path = self.faker.file_path()
        stream_name = self.faker.file_name()
        channel_claim_id = self.faker.sha1()
        channel_name = self.faker.simple_profile()['username']
        faked_attributes = {
            'channel_claim_id': channel_claim_id,
            'channel_name': '@' + channel_name,
            'claim_id': self.faker.sha1(),
            'claim_name': '-'.join(self.faker.words(4)),
            'completed': self.faker.boolean(),
            'download_directory': path.dirname(file_path),
            'download_path': file_path,
            'file_name': path.basename(file_path),
            'key': self.faker.md5(),
            'metadata': {
                'author': channel_name,
                'nsfw': random.randint(0, 1) == 1,
            },
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
