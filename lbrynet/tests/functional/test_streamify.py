import os
import shutil
import tempfile

from Crypto.Hash import MD5
from twisted.trial.unittest import TestCase
from twisted.internet import defer

from lbrynet import conf
from lbrynet.file_manager.EncryptedFileManager import EncryptedFileManager
from lbrynet.core.Session import Session
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier
from lbrynet.file_manager.EncryptedFileCreator import create_lbry_file
from lbrynet.lbry_file.client.EncryptedFileOptions import add_lbry_file_to_sd_identifier
from lbrynet.core.StreamDescriptor import get_sd_info
from lbrynet.core.PeerManager import PeerManager
from lbrynet.core.RateLimiter import DummyRateLimiter

from lbrynet.tests import mocks


FakeNode = mocks.Node
FakeWallet = mocks.Wallet
FakePeerFinder = mocks.PeerFinder
FakeAnnouncer = mocks.Announcer
GenFile = mocks.GenFile
test_create_stream_sd_file = mocks.create_stream_sd_file
DummyBlobAvailabilityTracker = mocks.BlobAvailabilityTracker


class TestStreamify(TestCase):
    maxDiff = 5000
    def setUp(self):
        mocks.mock_conf_settings(self)
        self.session = None
        self.lbry_file_manager = None
        self.is_generous = True
        self.db_dir = tempfile.mkdtemp()
        self.blob_dir = os.path.join(self.db_dir, "blobfiles")
        os.mkdir(self.blob_dir)

    @defer.inlineCallbacks
    def tearDown(self):
        lbry_files = self.lbry_file_manager.lbry_files
        for lbry_file in lbry_files:
            yield self.lbry_file_manager.delete_lbry_file(lbry_file)
        if self.lbry_file_manager is not None:
            yield self.lbry_file_manager.stop()
        if self.session is not None:
            yield self.session.shut_down()
        shutil.rmtree(self.db_dir)
        if os.path.exists("test_file"):
            os.remove("test_file")

    def test_create_stream(self):
        wallet = FakeWallet()
        peer_manager = PeerManager()
        peer_finder = FakePeerFinder(5553, peer_manager, 2)
        hash_announcer = FakeAnnouncer()
        rate_limiter = DummyRateLimiter()
        sd_identifier = StreamDescriptorIdentifier()

        self.session = Session(
            conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=self.db_dir, node_id="abcd",
            peer_finder=peer_finder, hash_announcer=hash_announcer,
            blob_dir=self.blob_dir, peer_port=5553,
            use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
            blob_tracker_class=DummyBlobAvailabilityTracker,
            is_generous=self.is_generous, external_ip="127.0.0.1"
        )

        self.lbry_file_manager = EncryptedFileManager(self.session, sd_identifier)

        d = self.session.setup()
        d.addCallback(lambda _: add_lbry_file_to_sd_identifier(sd_identifier))
        d.addCallback(lambda _: self.lbry_file_manager.setup())

        def verify_equal(sd_info):
            self.assertEqual(sd_info, test_create_stream_sd_file)

        def verify_stream_descriptor_file(stream_hash):
            d = get_sd_info(self.session.storage, stream_hash, True)
            d.addCallback(verify_equal)
            return d

        def iv_generator():
            iv = 0
            while 1:
                iv += 1
                yield "%016d" % iv

        def create_stream():
            test_file = GenFile(5209343, b''.join([chr(i + 3) for i in xrange(0, 64, 6)]))
            d = create_lbry_file(self.session, self.lbry_file_manager, "test_file", test_file,
                                 key="0123456701234567", iv_generator=iv_generator())
            d.addCallback(lambda lbry_file: lbry_file.stream_hash)
            return d

        d.addCallback(lambda _: create_stream())
        d.addCallback(verify_stream_descriptor_file)
        return d

    def test_create_and_combine_stream(self):
        wallet = FakeWallet()
        peer_manager = PeerManager()
        peer_finder = FakePeerFinder(5553, peer_manager, 2)
        hash_announcer = FakeAnnouncer()
        rate_limiter = DummyRateLimiter()
        sd_identifier = StreamDescriptorIdentifier()

        self.session = Session(
            conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=self.db_dir, node_id="abcd",
            peer_finder=peer_finder, hash_announcer=hash_announcer,
            blob_dir=self.blob_dir, peer_port=5553,
            use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
            blob_tracker_class=DummyBlobAvailabilityTracker, external_ip="127.0.0.1"
        )

        self.lbry_file_manager = EncryptedFileManager(self.session, sd_identifier)

        @defer.inlineCallbacks
        def create_stream():
            test_file = GenFile(53209343, b''.join([chr(i + 5) for i in xrange(0, 64, 6)]))
            lbry_file = yield create_lbry_file(self.session, self.lbry_file_manager, "test_file", test_file)
            sd_hash = yield self.session.storage.get_sd_blob_hash_for_stream(lbry_file.stream_hash)
            self.assertTrue(lbry_file.sd_hash, sd_hash)
            yield lbry_file.start()
            f = open('test_file')
            hashsum = MD5.new()
            hashsum.update(f.read())
            self.assertEqual(hashsum.hexdigest(), "68959747edc73df45e45db6379dd7b3b")

        d = self.session.setup()
        d.addCallback(lambda _: add_lbry_file_to_sd_identifier(sd_identifier))
        d.addCallback(lambda _: self.lbry_file_manager.setup())
        d.addCallback(lambda _: create_stream())
        return d
