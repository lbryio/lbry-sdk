import os
import shutil
import tempfile
from hashlib import md5
from twisted.trial.unittest import TestCase
from twisted.internet import defer, threads
from lbrynet.stream.descriptor import StreamDescriptorIdentifier
from lbrynet.blob.blob_manager import BlobFileManager
from lbrynet.stream.descriptor import get_sd_info
from lbrynet.staging.rate_limiter import RateLimiter
from lbrynet.peer import PeerManager
from lbrynet.storage import SQLiteStorage
from lbrynet.blob_exchange.price_negotiation import OnlyFreePaymentsManager
from lbrynet.staging.EncryptedFileCreator import create_lbry_file
from lbrynet.staging.EncryptedFileManager import EncryptedFileManager
from tests import mocks


FakeNode = mocks.Node
FakeWallet = mocks.Wallet
FakePeerFinder = mocks.PeerFinder
FakeAnnouncer = mocks.Announcer
GenFile = mocks.GenFile
test_create_stream_sd_file = mocks.create_stream_sd_file


class TestStreamify(TestCase):
    maxDiff = 5000

    @defer.inlineCallbacks
    def setUp(self):
        mocks.mock_conf_settings(self)
        self.session = None
        self.lbry_file_manager = None
        self.is_generous = True
        self.db_dir = tempfile.mkdtemp()
        self.blob_dir = os.path.join(self.db_dir, "blobfiles")
        os.mkdir(self.blob_dir)
        self.dht_node = FakeNode()
        self.wallet = FakeWallet()
        self.peer_manager = PeerManager()
        self.peer_finder = FakePeerFinder(5553, self.peer_manager, 2)
        self.rate_limiter = DummyRateLimiter()
        self.sd_identifier = StreamDescriptorIdentifier()
        self.storage = SQLiteStorage(':memory:')
        self.blob_manager = BlobFileManager(self.blob_dir, self.storage, self.dht_node._dataStore)
        self.prm = OnlyFreePaymentsManager()
        self.lbry_file_manager = EncryptedFileManager(
            self.peer_finder, self.rate_limiter, self.blob_manager, self.wallet, self.prm, self.storage,
            self.sd_identifier
        )
        yield f2d(self.storage.open())
        yield f2d(self.lbry_file_manager.setup())

    @defer.inlineCallbacks
    def tearDown(self):
        lbry_files = self.lbry_file_manager.lbry_files
        for lbry_file in lbry_files:
            yield self.lbry_file_manager.delete_lbry_file(lbry_file)
        yield self.lbry_file_manager.stop()
        yield f2d(self.storage.close())
        shutil.rmtree(self.db_dir, ignore_errors=True)
        if os.path.exists("test_file"):
            os.remove("test_file")

    def test_create_stream(self):

        def verify_equal(sd_info):
            self.assertEqual(sd_info, test_create_stream_sd_file)

        def verify_stream_descriptor_file(stream_hash):
            d = f2d(get_sd_info(self.storage, stream_hash, True))
            d.addCallback(verify_equal)
            return d

        def iv_generator():
            iv = 0
            while 1:
                iv += 1
                yield b"%016d" % iv

        def create_stream():
            test_file = GenFile(5209343, bytes((i + 3) for i in range(0, 64, 6)))
            d = create_lbry_file(
                self.blob_manager, self.storage, self.prm, self.lbry_file_manager, "test_file", test_file,
                key=b'0123456701234567', iv_generator=iv_generator()
            )
            d.addCallback(lambda lbry_file: lbry_file.stream_hash)
            return d

        d = create_stream()
        d.addCallback(verify_stream_descriptor_file)
        return d

    @defer.inlineCallbacks
    def test_create_and_combine_stream(self):
        test_file = GenFile(53209343, bytes((i + 5) for i in range(0, 64, 6)))
        lbry_file = yield create_lbry_file(self.blob_manager, self.storage, self.prm, self.lbry_file_manager,
                                           "test_file", test_file)
        sd_hash = yield f2d(self.storage.get_sd_blob_hash_for_stream(lbry_file.stream_hash))
        self.assertTrue(lbry_file.sd_hash, sd_hash)
        yield lbry_file.start()
        f = open('test_file', 'rb')
        hashsum = md5()
        hashsum.update(f.read())
        self.assertEqual(hashsum.hexdigest(), "68959747edc73df45e45db6379dd7b3b")
