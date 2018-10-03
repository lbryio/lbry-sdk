import mock
import json
import random
from os import path

from twisted.internet import defer
from twisted.trial import unittest

from faker import Faker

from lbryschema.decode import smart_decode
from lbrynet import conf
from lbrynet.database.storage import SQLiteStorage
from lbrynet.daemon.ComponentManager import ComponentManager
from lbrynet.daemon.Components import DATABASE_COMPONENT, DHT_COMPONENT, WALLET_COMPONENT, STREAM_IDENTIFIER_COMPONENT
from lbrynet.daemon.Components import HASH_ANNOUNCER_COMPONENT, REFLECTOR_COMPONENT, UPNP_COMPONENT, BLOB_COMPONENT
from lbrynet.daemon.Components import PEER_PROTOCOL_SERVER_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT
from lbrynet.daemon.Components import RATE_LIMITER_COMPONENT, HEADERS_COMPONENT, FILE_MANAGER_COMPONENT
from lbrynet.daemon.Daemon import Daemon as LBRYDaemon
from lbrynet.file_manager.EncryptedFileDownloader import ManagedEncryptedFileDownloader
from lbrynet.wallet.manager import LbryWalletManager
from torba.wallet import Wallet

from lbrynet.core.PaymentRateManager import OnlyFreePaymentsManager
from tests import util
from tests.mocks import mock_conf_settings, FakeNetwork, FakeFileManager
from tests.mocks import ExchangeRateManager as DummyExchangeRateManager
from tests.mocks import BTCLBCFeed, USDBTCFeed
from tests.util import is_android


import logging
logging.getLogger("lbryum").setLevel(logging.WARNING)


def get_test_daemon(data_rate=None, generous=True, with_fee=False):
    if data_rate is None:
        data_rate = conf.ADJUSTABLE_SETTINGS['data_rate'][1]

    rates = {
        'BTCLBC': {'spot': 3.0, 'ts': util.DEFAULT_ISO_TIME + 1},
        'USDBTC': {'spot': 2.0, 'ts': util.DEFAULT_ISO_TIME + 2}
    }
    component_manager = ComponentManager(
        skip_components=[DATABASE_COMPONENT, DHT_COMPONENT, WALLET_COMPONENT, UPNP_COMPONENT,
                         PEER_PROTOCOL_SERVER_COMPONENT, REFLECTOR_COMPONENT, HASH_ANNOUNCER_COMPONENT,
                         STREAM_IDENTIFIER_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT, BLOB_COMPONENT,
                         HEADERS_COMPONENT, RATE_LIMITER_COMPONENT],
        file_manager=FakeFileManager
    )
    daemon = LBRYDaemon(component_manager=component_manager)
    daemon.payment_rate_manager = OnlyFreePaymentsManager()
    daemon.wallet_manager = mock.Mock(spec=LbryWalletManager)
    daemon.wallet_manager.wallet = mock.Mock(spec=Wallet)
    daemon.wallet_manager.wallet.use_encryption = False
    daemon.wallet_manager.network = FakeNetwork()
    daemon.storage = mock.Mock(spec=SQLiteStorage)
    market_feeds = [BTCLBCFeed(), USDBTCFeed()]
    daemon.exchange_rate_manager = DummyExchangeRateManager(market_feeds, rates)
    daemon.file_manager = component_manager.get_component(FILE_MANAGER_COMPONENT)

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
    migrated = smart_decode(json.dumps(metadata))
    daemon._resolve = daemon.wallet_manager.resolve = lambda *_: defer.succeed(
        {"test": {'claim': {'value': migrated.claim_dict}}})
    return daemon


class TestCostEst(unittest.TestCase):

    def setUp(self):
        mock_conf_settings(self)
        util.resetTime(self)

    @defer.inlineCallbacks
    def test_fee_and_generous_data(self):
        size = 10000000
        correct_result = 4.5
        daemon = get_test_daemon(generous=True, with_fee=True)
        result = yield daemon.get_est_cost("test", size)
        self.assertEqual(result, correct_result)

    @defer.inlineCallbacks
    def test_fee_and_ungenerous_data(self):
        size = 10000000
        fake_fee_amount = 4.5
        data_rate = conf.ADJUSTABLE_SETTINGS['data_rate'][1]
        correct_result = size / 10 ** 6 * data_rate + fake_fee_amount
        daemon = get_test_daemon(generous=False, with_fee=True)
        result = yield daemon.get_est_cost("test", size)
        self.assertEqual(result, round(correct_result, 1))

    @defer.inlineCallbacks
    def test_generous_data_and_no_fee(self):
        size = 10000000
        correct_result = 0.0
        daemon = get_test_daemon(generous=True)
        result = yield daemon.get_est_cost("test", size)
        self.assertEqual(result, correct_result)

    @defer.inlineCallbacks
    def test_ungenerous_data_and_no_fee(self):
        size = 10000000
        data_rate = conf.ADJUSTABLE_SETTINGS['data_rate'][1]
        correct_result = size / 10 ** 6 * data_rate
        daemon = get_test_daemon(generous=False)
        result = yield daemon.get_est_cost("test", size)
        self.assertEqual(result, round(correct_result, 1))


class TestJsonRpc(unittest.TestCase):

    def setUp(self):
        def noop():
            return None

        mock_conf_settings(self)
        util.resetTime(self)
        self.test_daemon = get_test_daemon()
        self.test_daemon.wallet_manager.is_first_run = False
        self.test_daemon.wallet_manager.get_best_blockhash = noop

    def test_status(self):
        d = defer.maybeDeferred(self.test_daemon.jsonrpc_status)
        d.addCallback(lambda status: self.assertDictContainsSubset({'is_running': False}, status))

    def test_help(self):
        d = defer.maybeDeferred(self.test_daemon.jsonrpc_help, command='status')
        d.addCallback(lambda result: self.assertSubstring('daemon status', result['help']))
        # self.assertSubstring('daemon status', d.result)

    if is_android():
        test_help.skip = "Test cannot pass on Android because PYTHONOPTIMIZE removes the docstrings."


class TestFileListSorting(unittest.TestCase):

    def setUp(self):
        mock_conf_settings(self)
        util.resetTime(self)
        self.faker = Faker('en_US')
        self.faker.seed(129)  # contains 3 same points paid (5.9)
        self.test_daemon = get_test_daemon()
        self.test_daemon.file_manager.lbry_files = self._get_fake_lbry_files()

        self.test_points_paid = [
            2.5, 4.8, 5.9, 5.9, 5.9, 6.1, 7.1, 8.2, 8.4, 9.1
        ]
        self.test_file_names = [
            'add.mp3', 'any.mov', 'day.tiff', 'decade.odt', 'different.json', 'hotel.bmp',
            'might.bmp', 'physical.json', 'remember.mp3', 'than.ppt'
        ]
        self.test_authors = [
            'ashlee27', 'bfrederick', 'brittanyhicks', 'davidsonjeffrey', 'heidiherring',
            'jlewis', 'kswanson', 'michelle50', 'richard64', 'xsteele'
        ]
        return self.test_daemon.component_manager.setup()

    @defer.inlineCallbacks
    def test_sort_by_points_paid_no_direction_specified(self):
        sort_options = ['points_paid']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        self.assertEqual(self.test_points_paid, [f['points_paid'] for f in file_list])

    @defer.inlineCallbacks
    def test_sort_by_points_paid_ascending(self):
        sort_options = ['points_paid,asc']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        self.assertEqual(self.test_points_paid, [f['points_paid'] for f in file_list])

    @defer.inlineCallbacks
    def test_sort_by_points_paid_descending(self):
        sort_options = ['points_paid, desc']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        self.assertEqual(list(reversed(self.test_points_paid)), [f['points_paid'] for f in file_list])

    @defer.inlineCallbacks
    def test_sort_by_file_name_no_direction_specified(self):
        sort_options = ['file_name']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        self.assertEqual(self.test_file_names, [f['file_name'] for f in file_list])

    @defer.inlineCallbacks
    def test_sort_by_file_name_ascending(self):
        sort_options = ['file_name,\nasc']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        self.assertEqual(self.test_file_names, [f['file_name'] for f in file_list])

    @defer.inlineCallbacks
    def test_sort_by_file_name_descending(self):
        sort_options = ['\tfile_name,\n\tdesc']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        self.assertEqual(list(reversed(self.test_file_names)), [f['file_name'] for f in file_list])

    @defer.inlineCallbacks
    def test_sort_by_multiple_criteria(self):
        expected = [
            'file_name=different.json, points_paid=9.1',
            'file_name=physical.json, points_paid=8.4',
            'file_name=any.mov, points_paid=8.2',
            'file_name=hotel.bmp, points_paid=7.1',
            'file_name=add.mp3, points_paid=6.1',
            'file_name=decade.odt, points_paid=5.9',
            'file_name=might.bmp, points_paid=5.9',
            'file_name=than.ppt, points_paid=5.9',
            'file_name=remember.mp3, points_paid=4.8',
            'file_name=day.tiff, points_paid=2.5'
        ]
        format_result = lambda f: 'file_name={}, points_paid={}'.format(f['file_name'], f['points_paid'])

        sort_options = ['file_name,asc', 'points_paid,desc']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        self.assertEqual(expected, [format_result(r) for r in file_list])

        # Check that the list is not sorted as expected when sorted only by file_name.
        sort_options = ['file_name,asc']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        self.assertNotEqual(expected, [format_result(r) for r in file_list])

        # Check that the list is not sorted as expected when sorted only by points_paid.
        sort_options = ['points_paid,desc']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        self.assertNotEqual(expected, [format_result(r) for r in file_list])

        # Check that the list is not sorted as expected when not sorted at all.
        file_list = yield self.test_daemon.jsonrpc_file_list()
        self.assertNotEqual(expected, [format_result(r) for r in file_list])

    @defer.inlineCallbacks
    def test_sort_by_nested_field(self):
        extract_authors = lambda file_list: [f['metadata']['author'] for f in file_list]

        sort_options = ['metadata.author']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        self.assertEqual(self.test_authors, extract_authors(file_list))

        # Check that the list matches the expected in reverse when sorting in descending order.
        sort_options = ['metadata.author,desc']
        file_list = yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        self.assertEqual(list(reversed(self.test_authors)), extract_authors(file_list))

        # Check that the list is not sorted as expected when not sorted at all.
        file_list = yield self.test_daemon.jsonrpc_file_list()
        self.assertNotEqual(self.test_authors, extract_authors(file_list))

    @defer.inlineCallbacks
    def test_invalid_sort_produces_meaningful_errors(self):
        sort_options = ['meta.author']
        expected_message = "Failed to get 'meta.author', key 'meta' was not found."
        with self.assertRaisesRegex(Exception, expected_message):
            yield self.test_daemon.jsonrpc_file_list(sort=sort_options)
        sort_options = ['metadata.foo.bar']
        expected_message = "Failed to get 'metadata.foo.bar', key 'foo' was not found."
        with self.assertRaisesRegex(Exception, expected_message):
            yield self.test_daemon.jsonrpc_file_list(sort=sort_options)

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
            'key': self.faker.md5(raw_output=True),
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
