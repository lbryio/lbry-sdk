import unittest
from unittest import mock
import json

from lbry.extras.daemon.storage import SQLiteStorage
from lbry.extras.daemon.componentmanager import ComponentManager
from lbry.extras.daemon.components import DATABASE_COMPONENT, DHT_COMPONENT, WALLET_COMPONENT
from lbry.extras.daemon.components import HASH_ANNOUNCER_COMPONENT
from lbry.extras.daemon.components import UPNP_COMPONENT, BLOB_COMPONENT
from lbry.extras.daemon.components import PEER_PROTOCOL_SERVER_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT
from lbry.extras.daemon.daemon import Daemon as LBRYDaemon
from lbry.wallet import WalletManager, Wallet
from lbry.conf import Config

from tests import test_utils
# from tests.mocks import mock_conf_settings, FakeNetwork, FakeFileManager
# from tests.mocks import ExchangeRateManager as DummyExchangeRateManager
# from tests.mocks import BTCLBCFeed, USDBTCFeed
from tests.test_utils import is_android


def get_test_daemon(conf: Config, with_fee=False):
    conf.data_dir = '/tmp'
    rates = {
        'BTCLBC': {'spot': 3.0, 'ts': test_utils.DEFAULT_ISO_TIME + 1},
        'USDBTC': {'spot': 2.0, 'ts': test_utils.DEFAULT_ISO_TIME + 2}
    }
    component_manager = ComponentManager(
        conf, skip_components=[
            DATABASE_COMPONENT, DHT_COMPONENT, WALLET_COMPONENT, UPNP_COMPONENT,
            PEER_PROTOCOL_SERVER_COMPONENT, HASH_ANNOUNCER_COMPONENT,
            EXCHANGE_RATE_MANAGER_COMPONENT, BLOB_COMPONENT,
            RATE_LIMITER_COMPONENT],
        file_manager=FakeFileManager
    )
    daemon = LBRYDaemon(conf, component_manager=component_manager)
    daemon.payment_rate_manager = OnlyFreePaymentsManager()
    daemon.wallet_manager = mock.Mock(spec=WalletManager)
    daemon.wallet_manager.wallet = mock.Mock(spec=Wallet)
    daemon.wallet_manager.use_encryption = False
    daemon.wallet_manager.network = FakeNetwork()
    daemon.storage = mock.Mock(spec=SQLiteStorage)
    market_feeds = [BTCLBCFeed(), USDBTCFeed()]
    daemon.exchange_rate_manager = DummyExchangeRateManager(market_feeds, rates)
    daemon.stream_manager = component_manager.get_component(FILE_MANAGER_COMPONENT)

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
    daemon._resolve = daemon.resolve = lambda *_: defer.succeed(
        {"test": {'claim': {'value': migrated.claim_dict}}})
    return daemon


@unittest.SkipTest
class TestCostEst(unittest.TestCase):
    def setUp(self):
        test_utils.reset_time(self)

    def test_fee_and_generous_data(self):
        size = 10000000
        correct_result = 4.5
        daemon = get_test_daemon(Config(is_generous_host=True), with_fee=True)
        result = yield f2d(daemon.get_est_cost("test", size))
        self.assertEqual(result, correct_result)

    def test_generous_data_and_no_fee(self):
        size = 10000000
        correct_result = 0.0
        daemon = get_test_daemon(Config(is_generous_host=True))
        result = yield f2d(daemon.get_est_cost("test", size))
        self.assertEqual(result, correct_result)


@unittest.SkipTest
class TestJsonRpc(unittest.TestCase):
    def setUp(self):
        async def noop():
            return None

        test_utils.reset_time(self)
        self.test_daemon = get_test_daemon(Config())
        self.test_daemon.wallet_manager.get_best_blockhash = noop

    def test_status(self):
        status = yield f2d(self.test_daemon.jsonrpc_status())
        self.assertDictContainsSubset({'is_running': False}, status)

    def test_help(self):
        result = self.test_daemon.jsonrpc_help(command='status')
        self.assertSubstring('daemon status', result['help'])

    if is_android():
        test_help.skip = "Test cannot pass on Android because PYTHONOPTIMIZE removes the docstrings."


@unittest.SkipTest
class TestFileListSorting(unittest.TestCase):
    def setUp(self):
        test_utils.reset_time(self)
        self.test_daemon = get_test_daemon(Config())
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
        return f2d(self.test_daemon.component_manager.start())

    def test_sort_by_points_paid_no_direction_specified(self):
        sort_options = ['points_paid']
        file_list = yield f2d(self.test_daemon.jsonrpc_file_list(sort=sort_options)['items'])
        self.assertEqual(self.test_points_paid, [f['points_paid'] for f in file_list])

    def test_sort_by_points_paid_ascending(self):
        sort_options = ['points_paid,asc']
        file_list = yield f2d(self.test_daemon.jsonrpc_file_list(sort=sort_options)['items'])
        self.assertEqual(self.test_points_paid, [f['points_paid'] for f in file_list])

    def test_sort_by_points_paid_descending(self):
        sort_options = ['points_paid, desc']
        file_list = yield f2d(self.test_daemon.jsonrpc_file_list(sort=sort_options)['items'])
        self.assertEqual(list(reversed(self.test_points_paid)), [f['points_paid'] for f in file_list])

    def test_sort_by_file_name_no_direction_specified(self):
        sort_options = ['file_name']
        file_list = yield f2d(self.test_daemon.jsonrpc_file_list(sort=sort_options)['items'])
        self.assertEqual(self.test_file_names, [f['file_name'] for f in file_list])

    def test_sort_by_file_name_ascending(self):
        sort_options = ['file_name,\nasc']
        file_list = yield f2d(self.test_daemon.jsonrpc_file_list(sort=sort_options)['items'])
        self.assertEqual(self.test_file_names, [f['file_name'] for f in file_list])

    def test_sort_by_file_name_descending(self):
        sort_options = ['\tfile_name,\n\tdesc']
        file_list = yield f2d(self.test_daemon.jsonrpc_file_list(sort=sort_options)['items'])
        self.assertEqual(list(reversed(self.test_file_names)), [f['file_name'] for f in file_list])

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
        format_result = lambda f: f"file_name={f['file_name']}, points_paid={f['points_paid']}"

        sort_options = ['file_name,asc', 'points_paid,desc']
        file_list = yield f2d(self.test_daemon.jsonrpc_file_list(sort=sort_options)['items'])
        self.assertEqual(expected, [format_result(r) for r in file_list])

        # Check that the list is not sorted as expected when sorted only by file_name.
        sort_options = ['file_name,asc']
        file_list = yield f2d(self.test_daemon.jsonrpc_file_list(sort=sort_options)['items'])
        self.assertNotEqual(expected, [format_result(r) for r in file_list])

        # Check that the list is not sorted as expected when sorted only by points_paid.
        sort_options = ['points_paid,desc']
        file_list = yield f2d(self.test_daemon.jsonrpc_file_list(sort=sort_options)['items'])
        self.assertNotEqual(expected, [format_result(r) for r in file_list])

        # Check that the list is not sorted as expected when not sorted at all.
        file_list = yield f2d(self.test_daemon.jsonrpc_file_list()['items'])
        self.assertNotEqual(expected, [format_result(r) for r in file_list])

    def test_sort_by_nested_field(self):
        extract_authors = lambda file_list: [f['metadata']['author'] for f in file_list]

        sort_options = ['metadata.author']
        file_list = yield f2d(self.test_daemon.jsonrpc_file_list(sort=sort_options)['items'])
        self.assertEqual(self.test_authors, extract_authors(file_list))

        # Check that the list matches the expected in reverse when sorting in descending order.
        sort_options = ['metadata.author,desc']
        file_list = yield f2d(self.test_daemon.jsonrpc_file_list(sort=sort_options)['items'])
        self.assertEqual(list(reversed(self.test_authors)), extract_authors(file_list))

        # Check that the list is not sorted as expected when not sorted at all.
        file_list = yield f2d(self.test_daemon.jsonrpc_file_list()['items'])
        self.assertNotEqual(self.test_authors, extract_authors(file_list))

    def test_invalid_sort_produces_meaningful_errors(self):
        sort_options = ['meta.author']
        expected_message = "Failed to get 'meta.author', key 'meta' was not found."
        with self.assertRaisesRegex(Exception, expected_message):
            yield f2d(self.test_daemon.jsonrpc_file_list(sort=sort_options)['items'])
        sort_options = ['metadata.foo.bar']
        expected_message = "Failed to get 'metadata.foo.bar', key 'foo' was not found."
        with self.assertRaisesRegex(Exception, expected_message):
            yield f2d(self.test_daemon.jsonrpc_file_list(sort=sort_options)['items'])

    @staticmethod
    def _get_fake_lbry_files():
        faked_lbry_files = []
        for metadata in FAKED_LBRY_FILES:
            lbry_file = mock.Mock(spec=ManagedEncryptedFileDownloader)
            for attribute in metadata:
                setattr(lbry_file, attribute, metadata[attribute])
            async def get_total_bytes():
                return 0
            lbry_file.get_total_bytes = get_total_bytes
            async def status():
                return EncryptedFileStatusReport(
                    'file_name', 1, 1, 'completed'
                )
            lbry_file.status = status
            faked_lbry_files.append(lbry_file)
        return faked_lbry_files


FAKED_LBRY_FILES = (
    {
        'channel_claim_id': '3aace03b007d108c668d201533b7b07ab2981d47',
        'channel_name': '@ashlee27',
        'claim_id': 'cb63e644b6629467c031d0097d52ab6e0f1a5bf8',
        'claim_name': 'very-skill-place-growth',
        'completed': True,
        'download_directory': '/usually',
        'download_path': '/usually/any.mov',
        'file_name': 'any.mov',
        'key': b'>a\x11}\xec\xc2j\x1c\xe9\xc5l]\xfc\x16s|',
        'metadata': {'author': 'ashlee27', 'nsfw': True},
        'mime_type': 'multipart/signed',
        'nout': 7197,
        'outpoint': 'c5633a5932f9c8e3e5b9799c07251b236e3aec078b0546614f24a932b6b133f6',
        'points_paid': 8.2,
        'sd_hash': '3354ecf502870f6f6d59d21188755c1361c2cffaeb458764c179c136b26c4795083acfd93b3920218870b1a9c22535ef',
        'stopped': True,
        'stream_hash': 'c8f58a686726116c15a8de7f33b4f0d72504777c7dd0c48ba94d7bbea23d9c82b2f977081cd7c49d25d6a2841b232e1d',
        'stream_name': 'down.txt',
        'suggested_file_name': 'down.txt',
        'txid': '1c02986bfdb77b1c338e60b60c4c9febc59130af2e225f51665067c3d3419a35',
        'written_bytes': 6838,
    },
    {
        'channel_claim_id': 'dade35ea84001858d7cf10f50be3b5fea3e57fb7',
        'channel_name': '@richard64',
        'claim_id': '1c01096727da90140d333197fa8aaf88893f6ea8',
        'claim_name': 'room-tonight-produce-good',
        'completed': False,
        'download_directory': '/ability',
        'download_path': '/ability/day.tiff',
        'file_name': 'day.tiff',
        'key': b'`\x86j\xba\x97\x0c\xe4L\xad\x06nC\x8b]\xd6&',
        'metadata': {'author': 'richard64', 'nsfw': False},
        'mime_type': 'multipart/related',
        'nout': 9678,
        'outpoint': '0138083012ce4ff5a6e4c0ec2fc08e11a52ebd2306d70a20f36424011f7c1330',
        'points_paid': 2.5,
        'sd_hash': '9e98f5e4bd4393b45a41839fe72a4df1f94b029e2339f8b14b9eaa9fec2be5245b160a59cfcc80fa86c1f91da67d5581',
        'stopped': False,
        'stream_hash': '7403ff9319292bdb022d66d0b88401775c6bb355fc0a75fe01452950fb19642ba58d492d34e24d8bf58375e6c2fca16f',
        'stream_name': 'including.mp3',
        'suggested_file_name': 'including.mp3',
        'txid': '345bfc7b4a0c042b14474ac2cecf099236aec5a6730943630ffb176e7b421121',
        'written_bytes': 8438,
    },
    {
        'channel_claim_id': '59766071ea2df38b4a751834a77246bf8ff8071d',
        'channel_name': '@bfrederick',
        'claim_id': '1c08967d515ac2a5fd3cb4e477fde18bddde22e2',
        'claim_name': 'at-first-skill-agency',
        'completed': True,
        'download_directory': '/agree',
        'download_path': '/agree/different.json',
        'file_name': 'different.json',
        'key': b'\xc06\xb9\x8e\x00S\xdbX\x1cC\xbd+\xfc\xea\xc96',
        'metadata': {'author': 'bfrederick', 'nsfw': True},
        'mime_type': 'image/svg+xml',
        'nout': 2975,
        'outpoint': '62bb992e11c562e8064aec094e2b4eefb422e50b13ae49dc10f440a60f8e99bc',
        'points_paid': 9.1,
        'sd_hash': '3d809caf1266ec1ab78cc046a62f388434b6c59f85844500f59a1c75b4303b9ea27c532a231556e8b9776c544677bdf7',
        'stopped': True,
        'stream_hash': '9ecb8cf7dca7260f90666f05c88882017c786d31b572f3cba9447099ca9b49cdcb93f801db2249b7d32ff44ca6ffd69c',
        'stream_name': 'north.doc',
        'suggested_file_name': 'north.doc',
        'txid': '98e12bce3a5db96e3513f1ff45afca8b69d61324117d6e839075ac512dd86251',
        'written_bytes': 1929,
    },
    {
        'channel_claim_id': '046c8a762cd158a6e5b112d7d9c9e4b778f27388',
        'channel_name': '@heidiherring',
        'claim_id': '3d7573264601af7b5402cd54a66c13f2f93f296f',
        'claim_name': 'drop-hot-military-drive',
        'completed': False,
        'download_directory': '/letter',
        'download_path': '/letter/than.ppt',
        'file_name': 'than.ppt',
        'key': b'\n\xa7\xb3\x05\xab\x8e\xcc\n\xdcn\xd9\x81\xf3m\xf1t',
        'metadata': {'author': 'heidiherring', 'nsfw': True},
        'mime_type': 'text/javascript',
        'nout': 3452,
        'outpoint': '5e8b55ffe59774366804c384f632f728f769bad566c784c6a23f1081724d00ea',
        'points_paid': 5.9,
        'sd_hash': 'c945b0acaf1c97dd7f262cf73cc3813ab6552f695ab00a445ca07a2a4da43bf3bb020cc7e338b484405d0865ef836480',
        'stopped': False,
        'stream_hash': '692ea08506d13422c875ce9d49fb9fe90b828d259d46c53adffa68a045e3852d4763b90ef94ef3864a1164bcab7eefa0',
        'stream_name': 'few.css',
        'suggested_file_name': 'few.css',
        'txid': '9ef901facbf8bc133cfe67793fe4423c048753dab8370d987f6f552ed6483bbb',
        'written_bytes': 9498,
    },
    {
        'channel_claim_id': 'adc87fa84d601aa1760d0f4585f02e60bc82c703',
        'channel_name': '@xsteele',
        'claim_id': '9022e1fd14646f6a4f6708566fbb6f6ac10ba3d5',
        'claim_name': 'mean-television-miss-yourself',
        'completed': True,
        'download_directory': '/its',
        'download_path': '/its/add.mp3',
        'file_name': 'add.mp3',
        'key': b'\xdc\xd1\xf1i!\x85\xc6\xc8\\\xe0\xd7\xc0\xceN<l',
        'metadata': {'author': 'xsteele', 'nsfw': False},
        'mime_type': 'message/imdn+xml',
        'nout': 7924,
        'outpoint': '4fd8a071fd00050006a666de076595d7a61e04dac0ce8bf9ef90024d2415ba30',
        'points_paid': 6.1,
        'sd_hash': 'ac28c50337bd16b4a753a2ae6bdad25cbb93270b83f593ec238b8237ce4ddf30aff676eb7025211d970ab5a5cca204c7',
        'stopped': True,
        'stream_hash': 'a0a9aa762fb6599f94e7098d70cc14ced34d08c210863d62b6d1e9c7eb523d98d0d8e3c80ddc03ce68b51f99e88024b5',
        'stream_name': 'picture.csv',
        'suggested_file_name': 'picture.csv',
        'txid': 'b4df85f9be396f2d9a3b9172f826be9899608d827cabc5196863ec27d3a32f82',
        'written_bytes': 9220,
    },
    {
        'channel_claim_id': '79d17bbcb93b31c20fe395190dc199d871268ef1',
        'channel_name': '@michelle50',
        'claim_id': 'daf4c15cd3da305e7b29b0028cf801c61bd67e30',
        'claim_name': 'card-oil-since-take',
        'completed': True,
        'download_directory': '/lawyer',
        'download_path': '/lawyer/hotel.bmp',
        'file_name': 'hotel.bmp',
        'key': b'\xda<-\x11-\xbb\xe3u\x80\xffX\x01N\xfc\x01)',
        'metadata': {'author': 'michelle50', 'nsfw': True},
        'mime_type': 'image/png',
        'nout': 5576,
        'outpoint': '27a62194fbf658327899431ecf251866bd0eec4da24d0b3feb8c440c4ea3ac1a',
        'points_paid': 7.1,
        'sd_hash': '20e4fc4513d7ea6f270e2021f7057c78e175754561e7db94e10c41d6d74ca639bb3c4d6e38dc2817ce303629c901d1a2',
        'stopped': False,
        'stream_hash': '781785e554fadb275ba75ee58cc5db0063f4d9cf2a1f1c4053a586ddce20089197d42e6640398cec75c8623a7c38ae0b',
        'stream_name': 'paper.jpeg',
        'suggested_file_name': 'paper.jpeg',
        'txid': '8647c42f762694237804eeed4cbde776490a4f3b8b293ca41f550488098f883e',
        'written_bytes': 7382,
    },
    {
        'channel_claim_id': '7e4cee485713909665c21246ba22159e0a20a820',
        'channel_name': '@jlewis',
        'claim_id': '7bc402e4bc6a8b1c1aa2184e8e082eb1d0353db3',
        'claim_name': 'heavy-street-meeting-and',
        'completed': True,
        'download_directory': '/personal',
        'download_path': '/personal/remember.mp3',
        'file_name': 'remember.mp3',
        'key': b'\x1c\x9d%\x1e\xe4\xab\xb9\x0c\xac<\x86\xc7P;\xfdO',
        'metadata': {'author': 'jlewis', 'nsfw': True},
        'mime_type': 'video/x-matroska',
        'nout': 8116,
        'outpoint': 'e2da970db0edb37680519a58de53dc088e6d26d5c4a37ae37d5c0f1901f30197',
        'points_paid': 4.8,
        'sd_hash': 'f42913f4bfba90f157b4744b55e4043d79d2d658dc08aa306b34a3ae4a1c1c37759fd9f0b4b8181f539bd60373746954',
        'stopped': True,
        'stream_hash': '4051a577422fe2b444c9c572a0a1b3f731e0ed2e5eb3b9a3aaa4ce1b0ec694cd7786e224c94a126fc9a868f1b93cb2e1',
        'stream_name': 'feel.html',
        'suggested_file_name': 'feel.html',
        'txid': 'c88e0c86ebbca20d0dafed682711a0b2e02e80637515c25eb26f2a589385bfe2',
        'written_bytes': 9337,
    },
    {
        'channel_claim_id': '13aa3c28c0c8bb08a679a010f63bd3f4b5234e73',
        'channel_name': '@brittanyhicks',
        'claim_id': '3c9c02bf1bfcedb2654f9003c464df9059a8e6b0',
        'claim_name': 'cold-music-admit-technology',
        'completed': True,
        'download_directory': '/nor',
        'download_path': '/nor/might.bmp',
        'file_name': 'might.bmp',
        'key': b'\rh\xb3jqR\\\xdb\xb9\xa0a\xa4J\xa4\xacs',
        'metadata': {'author': 'brittanyhicks', 'nsfw': True},
        'mime_type': 'application/xop+xml',
        'nout': 8338,
        'outpoint': 'a68a9dfa301292e1d0fe60a9bb0bcefa3e4e26630269064c8d2dd0f578427a10',
        'points_paid': 5.9,
        'sd_hash': '48fef5178b93b542495d19d76407692802ab529d989539b203a1cb38ce35ec2d4e9ea7d31eac660f715c39b69cd574ec',
        'stopped': True,
        'stream_hash': '2052889a9447ea73d743ec2c8c71678bf60616c01cd05d0a4d34a1aa92ee334585771a28f42cfe1b4124645352325946',
        'stream_name': 'shoulder.js',
        'suggested_file_name': 'shoulder.js',
        'txid': 'b3f5f9db4c40157f348b9cf7dcb4ae3c53fe5e43481a4b66b2cc2334ae5ad2cb',
        'written_bytes': 9736,
    },
    {
        'channel_claim_id': 'a18b45f2131fd79fea6bb493d94349c9734ef211',
        'channel_name': '@kswanson',
        'claim_id': '1223727010f0b4b9f6f45ca95cad0bfb3ce759a0',
        'claim_name': 'often-speech-provide-run',
        'completed': True,
        'download_directory': '/member',
        'download_path': '/member/physical.json',
        'file_name': 'physical.json',
        'key': b"'\xa7\x9b!\t\x86\xe2q\x15S\x9c\x92S@7;",
        'metadata': {'author': 'kswanson', 'nsfw': True},
        'mime_type': 'multipart/form-data',
        'nout': 7028,
        'outpoint': '818a4265723d7682cff4cc89d9b3433af48636ba42d2ca1e65eef8b7f9bef0ad',
        'points_paid': 8.4,
        'sd_hash': 'c808d997ff914c4986e420c4b2547ab030082da28ffebe2a0844ad6325c9f276fad5a003b18dcd015397e41b71d172e2',
        'stopped': False,
        'stream_hash': '2d457dda5ed01009b3812ff60bd24cbc2a0cb1361f566433d71dbce7d757977deac7f5aca62a60ec63eaa1b401194da5',
        'stream_name': 'country.avi',
        'suggested_file_name': 'country.avi',
        'txid': '42db2b952c578afcb8f640c2a12e563ba1a31b18fc8357d2f04f5de6c8515fba',
        'written_bytes': 9688,
    },
    {
        'channel_claim_id': '84a06ce77cde8ed1511e268fcfdebd8feb1333e2',
        'channel_name': '@davidsonjeffrey',
        'claim_id': '8fb403f0bb0695530935a0991a7eb7218c46eed9',
        'claim_name': 'option-company-glass-this',
        'completed': True,
        'download_directory': '/environment',
        'download_path': '/environment/decade.odt',
        'file_name': 'decade.odt',
        'key': b')\xa3h\x12\xf2\xd5RPkWojN\x08%\x0e',
        'metadata': {'author': 'davidsonjeffrey', 'nsfw': True},
        'mime_type': 'video/webm',
        'nout': 8810,
        'outpoint': '04da67fe9c6d129812e16045c02f1f670d3e329e7a9c0872712aaa74876becdd',
        'points_paid': 5.9,
        'sd_hash': '394eb1e0caf0d7dbeb80d435631534dc716229fac035aebe2af1729af5cbbad1c4fa503ce7fa7cc01e5366d1ce9d9d07',
        'stopped': False,
        'stream_hash': '1904d27ab8c784b7ae770980f004522e36089e86e3ce95d3005c3829cf4ad1571c5fe248a3f67a54521e07290a9e7466',
        'stream_name': 'score.wav',
        'suggested_file_name': 'score.wav',
        'txid': 'd2f8ecfac4491e1de186b43a5e561413304769a1683612a16633dd3e725ff1e0',
        'written_bytes': 7929,
    },
)
