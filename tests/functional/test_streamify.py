import logging
import os
import shutil

from Crypto.Hash import MD5
from twisted.trial.unittest import TestCase
from twisted.internet import defer, threads

from lbrynet import conf
from lbrynet.lbryfile.EncryptedFileMetadataManager import TempEncryptedFileMetadataManager
from lbrynet.lbryfile.EncryptedFileMetadataManager import DBEncryptedFileMetadataManager
from lbrynet.lbryfilemanager.EncryptedFileManager import EncryptedFileManager
from lbrynet.core.Session import Session
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier
from lbrynet.lbryfile import publish_sd_blob
from lbrynet.lbryfilemanager.EncryptedFileCreator import create_lbry_file
from lbrynet.lbryfile.client.EncryptedFileOptions import add_lbry_file_to_sd_identifier
from lbrynet.lbryfile.StreamDescriptor import get_sd_info
from lbrynet.core.PeerManager import PeerManager
from lbrynet.core.RateLimiter import DummyRateLimiter, RateLimiter

from tests import mocks


FakeNode = mocks.Node
FakeWallet = mocks.Wallet
FakePeerFinder = mocks.PeerFinder
FakeAnnouncer = mocks.Announcer
GenFile = mocks.GenFile
test_create_stream_sd_file = mocks.create_stream_sd_file
DummyBlobAvailabilityTracker = mocks.BlobAvailabilityTracker


class TestStreamify(TestCase):
    def setUp(self):
        mocks.mock_conf_settings(self)
        self.session = None
        self.stream_info_manager = None
        self.lbry_file_manager = None
        self.addCleanup(self.take_down_env)
        self.is_generous = True

    def take_down_env(self):
        d = defer.succeed(True)
        if self.lbry_file_manager is not None:
            d.addCallback(lambda _: self.lbry_file_manager.stop())
        if self.session is not None:
            d.addCallback(lambda _: self.session.shut_down())
        if self.stream_info_manager is not None:
            d.addCallback(lambda _: self.stream_info_manager.stop())

        def delete_test_env():
            shutil.rmtree('client')
            if os.path.exists("test_file"):
                os.remove("test_file")

        d.addCallback(lambda _: threads.deferToThread(delete_test_env))
        return d

    def test_create_stream(self):
        wallet = FakeWallet()
        peer_manager = PeerManager()
        peer_finder = FakePeerFinder(5553, peer_manager, 2)
        hash_announcer = FakeAnnouncer()
        rate_limiter = DummyRateLimiter()
        sd_identifier = StreamDescriptorIdentifier()


        db_dir = "client"
        blob_dir = os.path.join(db_dir, "blobfiles")
        os.mkdir(db_dir)
        os.mkdir(blob_dir)

        self.session = Session(
            conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir, lbryid="abcd",
            peer_finder=peer_finder, hash_announcer=hash_announcer,
            blob_dir=blob_dir, peer_port=5553,
            use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
            blob_tracker_class=DummyBlobAvailabilityTracker,
            is_generous=self.is_generous
        )

        self.stream_info_manager = TempEncryptedFileMetadataManager()

        self.lbry_file_manager = EncryptedFileManager(
            self.session, self.stream_info_manager, sd_identifier)

        d = self.session.setup()
        d.addCallback(lambda _: self.stream_info_manager.setup())
        d.addCallback(lambda _: add_lbry_file_to_sd_identifier(sd_identifier))
        d.addCallback(lambda _: self.lbry_file_manager.setup())

        def verify_equal(sd_info):
            self.assertEqual(sd_info, test_create_stream_sd_file)

        def verify_stream_descriptor_file(stream_hash):
            d = get_sd_info(self.lbry_file_manager.stream_info_manager, stream_hash, True)
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

        db_dir = "client"
        blob_dir = os.path.join(db_dir, "blobfiles")
        os.mkdir(db_dir)
        os.mkdir(blob_dir)

        self.session = Session(
            conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir, lbryid="abcd",
            peer_finder=peer_finder, hash_announcer=hash_announcer,
            blob_dir=blob_dir, peer_port=5553,
            use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
            blob_tracker_class=DummyBlobAvailabilityTracker
        )

        self.stream_info_manager = DBEncryptedFileMetadataManager(self.session.db_dir)

        self.lbry_file_manager = EncryptedFileManager(
            self.session, self.stream_info_manager, sd_identifier)

        def start_lbry_file(lbry_file):
            logging.debug("Calling lbry_file.start()")
            d = lbry_file.start()
            return d

        def combine_stream(stream_hash):
            prm = self.session.payment_rate_manager
            d = self.lbry_file_manager.add_lbry_file(stream_hash, prm)
            d.addCallback(start_lbry_file)

            def check_md5_sum():
                f = open('test_file')
                hashsum = MD5.new()
                hashsum.update(f.read())
                self.assertEqual(hashsum.hexdigest(), "68959747edc73df45e45db6379dd7b3b")

            d.addCallback(lambda _: check_md5_sum())
            return d

        @defer.inlineCallbacks
        def create_stream():
            test_file = GenFile(53209343, b''.join([chr(i + 5) for i in xrange(0, 64, 6)]))
            stream_hash = yield create_lbry_file(self.session, self.lbry_file_manager, "test_file",
                                             test_file, suggested_file_name="test_file")
            yield publish_sd_blob(self.stream_info_manager, self.session.blob_manager, stream_hash)
            defer.returnValue(stream_hash)

        d = self.session.setup()
        d.addCallback(lambda _: self.stream_info_manager.setup())
        d.addCallback(lambda _: add_lbry_file_to_sd_identifier(sd_identifier))
        d.addCallback(lambda _: self.lbry_file_manager.setup())
        d.addCallback(lambda _: create_stream())
        d.addCallback(combine_stream)
        return d
