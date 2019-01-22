import json
from twisted.trial import unittest
from twisted.internet import defer

from cryptography.hazmat.primitives.ciphers.algorithms import AES
from lbrynet.conf import Config
from lbrynet.extras.compat import f2d
from lbrynet.extras.daemon.PeerManager import PeerManager
from lbrynet.p2p.StreamDescriptor import get_sd_info, BlobStreamDescriptorReader
from lbrynet.p2p.StreamDescriptor import StreamDescriptorIdentifier
from lbrynet.p2p.BlobManager import DiskBlobManager
from lbrynet.p2p.RateLimiter import DummyRateLimiter
from lbrynet.p2p.PaymentRateManager import OnlyFreePaymentsManager
from lbrynet.extras.daemon.storage import SQLiteStorage
from lbrynet.blob import EncryptedFileCreator
from lbrynet.blob.EncryptedFileManager import EncryptedFileManager
from lbrynet.p2p.StreamDescriptor import JSONBytesEncoder
from tests import mocks
from tests.test_utils import mk_db_and_blob_dir, rm_db_and_blob_dir


FakeNode = mocks.Node
FakeWallet = mocks.Wallet
FakePeerFinder = mocks.PeerFinder
FakeAnnouncer = mocks.Announcer
GenFile = mocks.GenFile
test_create_stream_sd_file = mocks.create_stream_sd_file
DummyBlobAvailabilityTracker = mocks.BlobAvailabilityTracker

MB = 2**20


def iv_generator():
    while True:
        yield b'3' * (AES.block_size // 8)


class CreateEncryptedFileTest(unittest.TestCase):
    timeout = 5

    def setUp(self):
        self.tmp_db_dir, self.tmp_blob_dir = mk_db_and_blob_dir()
        conf = Config(data_dir=self.tmp_blob_dir)
        self.wallet = FakeWallet()
        self.peer_manager = PeerManager()
        self.peer_finder = FakePeerFinder(5553, self.peer_manager, 2)
        self.rate_limiter = DummyRateLimiter()
        self.sd_identifier = StreamDescriptorIdentifier()
        self.storage = SQLiteStorage(conf, ':memory:')
        self.blob_manager = DiskBlobManager(self.tmp_blob_dir, self.storage)
        self.prm = OnlyFreePaymentsManager()
        self.lbry_file_manager = EncryptedFileManager(
            conf, self.peer_finder, self.rate_limiter, self.blob_manager,
            self.wallet, self.prm, self.storage, self.sd_identifier
        )
        d = f2d(self.storage.open())
        d.addCallback(lambda _: f2d(self.lbry_file_manager.setup()))
        return d

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.lbry_file_manager.stop()
        yield f2d(self.blob_manager.stop())
        yield f2d(self.storage.close())
        rm_db_and_blob_dir(self.tmp_db_dir, self.tmp_blob_dir)

    @defer.inlineCallbacks
    def create_file(self, filename):
        handle = mocks.GenFile(3*MB, b'1')
        key = b'2' * (AES.block_size // 8)
        out = yield EncryptedFileCreator.create_lbry_file(
            self.blob_manager, self.storage, self.prm, self.lbry_file_manager, filename, handle, key, iv_generator()
        )
        defer.returnValue(out)

    @defer.inlineCallbacks
    def test_can_create_file(self):
        expected_stream_hash = "41e6b247d923d191b154fb6f1b8529d6ddd6a73d65c35" \
                               "7b1acb742dd83151fb66393a7709e9f346260a4f4db6de10c25"
        expected_sd_hash = "40c485432daec586c1a2d247e6c08d137640a5af6e81f3f652" \
                           "3e62e81a2e8945b0db7c94f1852e70e371d917b994352c"
        filename = 'test.file'
        lbry_file = yield self.create_file(filename)
        sd_hash = yield f2d(self.storage.get_sd_blob_hash_for_stream(lbry_file.stream_hash))

        # read the sd blob file
        sd_blob = self.blob_manager.blobs[sd_hash]
        sd_reader = BlobStreamDescriptorReader(sd_blob)
        sd_file_info = yield sd_reader.get_info()

        # this comes from the database, the blobs returned are sorted
        sd_info = yield f2d(get_sd_info(self.storage, lbry_file.stream_hash, include_blobs=True))
        self.maxDiff = None
        unicode_sd_info = json.loads(json.dumps(sd_info, sort_keys=True, cls=JSONBytesEncoder))
        self.assertDictEqual(unicode_sd_info, sd_file_info)
        self.assertEqual(sd_info['stream_hash'], expected_stream_hash)
        self.assertEqual(len(sd_info['blobs']), 3)
        self.assertNotEqual(sd_info['blobs'][0]['length'], 0)
        self.assertNotEqual(sd_info['blobs'][1]['length'], 0)
        self.assertEqual(sd_info['blobs'][2]['length'], 0)
        self.assertEqual(expected_stream_hash, lbry_file.stream_hash)
        self.assertEqual(sd_hash, lbry_file.sd_hash)
        self.assertEqual(sd_hash, expected_sd_hash)
        blobs = yield self.blob_manager.get_all_verified_blobs()
        self.assertEqual(3, len(blobs))
        num_should_announce_blobs = yield self.blob_manager.count_should_announce_blobs()
        self.assertEqual(2, num_should_announce_blobs)

    @defer.inlineCallbacks
    def test_can_create_file_with_unicode_filename(self):
        expected_stream_hash = ('d1da4258f3ce12edb91d7e8e160d091d3ab1432c2e55a6352dce0'
                                '2fd5adb86fe144e93e110075b5865fff8617776c6c0')
        filename = '☃.file'
        lbry_file = yield self.create_file(filename)
        self.assertEqual(expected_stream_hash, lbry_file.stream_hash)
