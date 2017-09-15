import os
import shutil
import tempfile

from twisted.internet import defer, threads, error
from twisted.trial import unittest

from lbrynet import conf
from lbrynet import lbry_file
from lbrynet import reflector
from lbrynet.core import BlobManager
from lbrynet.core import PeerManager
from lbrynet.core import RateLimiter
from lbrynet.core import Session
from lbrynet.core import StreamDescriptor
from lbrynet.dht.node import Node
from lbrynet.lbry_file import EncryptedFileMetadataManager
from lbrynet.lbry_file.client import EncryptedFileOptions
from lbrynet.file_manager import EncryptedFileCreator
from lbrynet.file_manager import EncryptedFileManager

from tests import mocks
from tests.util import mk_db_and_blob_dir, rm_db_and_blob_dir

class TestReflector(unittest.TestCase):
    def setUp(self):
        mocks.mock_conf_settings(self)
        self.session = None
        self.stream_info_manager = None
        self.lbry_file_manager = None
        self.server_blob_manager = None
        self.reflector_port = None
        self.port = None
        self.addCleanup(self.take_down_env)
        wallet = mocks.Wallet()
        peer_manager = PeerManager.PeerManager()
        peer_finder = mocks.PeerFinder(5553, peer_manager, 2)
        hash_announcer = mocks.Announcer()
        rate_limiter = RateLimiter.DummyRateLimiter()
        sd_identifier = StreamDescriptor.StreamDescriptorIdentifier()

        self.expected_blobs = [
            (
                'dc4708f76a5e7af0f1cae0ee96b824e2ed9250c9346c093b'
                '441f0a20d3607c17948b6fcfb4bc62020fe5286693d08586',
                2097152
            ),
            (
                'f4067522c1b49432a2a679512e3917144317caa1abba0c04'
                '1e0cd2cf9f635d4cf127ce1824fa04189b63916174951f70',
                2097152
            ),
            (
                '305486c434260484fcb2968ce0e963b72f81ba56c11b08b1'
                'af0789b55b44d78422600f9a38e3cf4f2e9569897e5646a9',
                1015056
            ),
        ]

        self.db_dir, self.blob_dir = mk_db_and_blob_dir()
        self.session = Session.Session(
            conf.settings['data_rate'],
            db_dir=self.db_dir,
            lbryid="abcd",
            peer_finder=peer_finder,
            hash_announcer=hash_announcer,
            blob_dir=self.blob_dir,
            peer_port=5553,
            use_upnp=False,
            rate_limiter=rate_limiter,
            wallet=wallet,
            blob_tracker_class=mocks.BlobAvailabilityTracker,
            dht_node_class=Node
        )

        self.stream_info_manager = EncryptedFileMetadataManager.DBEncryptedFileMetadataManager(self.db_dir)

        self.lbry_file_manager = EncryptedFileManager.EncryptedFileManager(
            self.session, self.stream_info_manager, sd_identifier)

        self.server_db_dir, self.server_blob_dir = mk_db_and_blob_dir()
        self.server_blob_manager = BlobManager.DiskBlobManager(
                                    hash_announcer, self.server_blob_dir, self.server_db_dir)
        self.server_stream_info_manager = EncryptedFileMetadataManager.DBEncryptedFileMetadataManager(self.server_db_dir)


        d = self.session.setup()
        d.addCallback(lambda _: self.stream_info_manager.setup())
        d.addCallback(lambda _: EncryptedFileOptions.add_lbry_file_to_sd_identifier(sd_identifier))
        d.addCallback(lambda _: self.lbry_file_manager.setup())
        d.addCallback(lambda _: self.server_blob_manager.setup())
        d.addCallback(lambda _: self.server_stream_info_manager.setup())

        def verify_equal(sd_info):
            self.assertEqual(mocks.create_stream_sd_file, sd_info)

        def save_sd_blob_hash(sd_hash):
            self.sd_hash = sd_hash
            self.expected_blobs.append((sd_hash, 923))

        def verify_stream_descriptor_file(stream_hash):
            self.stream_hash = stream_hash
            d = lbry_file.get_sd_info(self.lbry_file_manager.stream_info_manager, stream_hash, True)
            d.addCallback(verify_equal)
            d.addCallback(
                lambda _: lbry_file.publish_sd_blob(
                    self.lbry_file_manager.stream_info_manager,
                    self.session.blob_manager, stream_hash
                )
            )
            d.addCallback(save_sd_blob_hash)
            return d

        def create_stream():
            test_file = mocks.GenFile(5209343, b''.join([chr(i + 3) for i in xrange(0, 64, 6)]))
            d = EncryptedFileCreator.create_lbry_file(
                self.session,
                self.lbry_file_manager,
                "test_file",
                test_file,
                key="0123456701234567",
                iv_generator=iv_generator()
            )
            return d

        def start_server():
            server_factory = reflector.ServerFactory(peer_manager, self.server_blob_manager, self.server_stream_info_manager)
            from twisted.internet import reactor
            port = 8943
            while self.reflector_port is None:
                try:
                    self.reflector_port = reactor.listenTCP(port, server_factory)
                    self.port = port
                except error.CannotListenError:
                    port += 1

        d.addCallback(lambda _: create_stream())
        d.addCallback(verify_stream_descriptor_file)
        d.addCallback(lambda _: start_server())
        return d

    def take_down_env(self):
        d = defer.succeed(True)
        if self.lbry_file_manager is not None:
            d.addCallback(lambda _: self.lbry_file_manager.stop())
        if self.session is not None:
            d.addCallback(lambda _: self.session.shut_down())
        if self.stream_info_manager is not None:
            d.addCallback(lambda _: self.stream_info_manager.stop())
        if self.server_blob_manager is not None:
            d.addCallback(lambda _: self.server_blob_manager.stop())
        if self.reflector_port is not None:
            d.addCallback(lambda _: self.reflector_port.stopListening())

        def delete_test_env():
            try:
                rm_db_and_blob_dir(self.db_dir, self.blob_dir)
                rm_db_and_blob_dir(self.server_db_dir, self.server_blob_dir)
            except:
                raise unittest.SkipTest("TODO: fix this for windows")

        d.addCallback(lambda _: threads.deferToThread(delete_test_env))
        d.addErrback(lambda err: str(err))
        return d

    def test_stream_reflector(self):
        def verify_blob_on_reflector():
            check_blob_ds = []
            for blob_hash, blob_size in self.expected_blobs:
                check_blob_ds.append(verify_have_blob(blob_hash, blob_size))
            return defer.DeferredList(check_blob_ds)

        @defer.inlineCallbacks
        def verify_stream_on_reflector():
            # check stream_info_manager has all the right information
            streams = yield self.server_stream_info_manager.get_all_streams()
            self.assertEqual(1, len(streams))
            self.assertEqual(self.stream_hash, streams[0])

            blobs = yield self.server_stream_info_manager.get_blobs_for_stream(self.stream_hash)
            blob_hashes = [b[0] for b in blobs if b[0] is not None]
            expected_blob_hashes = [b[0] for b in self.expected_blobs[:-1] if b[0] is not None]
            self.assertEqual(expected_blob_hashes, blob_hashes)
            sd_hashes = yield self.server_stream_info_manager.get_sd_blob_hashes_for_stream(self.stream_hash)
            self.assertEqual(1, len(sd_hashes))
            expected_sd_hash = self.expected_blobs[-1][0]
            self.assertEqual(self.sd_hash, sd_hashes[0])

            # check should_announce blobs on blob_manager
            blob_hashes = yield self.server_blob_manager._get_all_should_announce_blob_hashes()
            self.assertEqual(2, len(blob_hashes))
            self.assertTrue(self.sd_hash in blob_hashes)
            self.assertTrue(expected_blob_hashes[0] in blob_hashes)

        def verify_have_blob(blob_hash, blob_size):
            d = self.server_blob_manager.get_blob(blob_hash)
            d.addCallback(lambda blob: verify_blob_completed(blob, blob_size))
            return d

        def send_to_server():
            fake_lbry_file = mocks.FakeLBRYFile(self.session.blob_manager,
                                                self.stream_info_manager,
                                                self.stream_hash)
            factory = reflector.ClientFactory(fake_lbry_file)

            from twisted.internet import reactor
            reactor.connectTCP('localhost', self.port, factory)
            return factory.finished_deferred

        def verify_blob_completed(blob, blob_size):
            self.assertTrue(blob.is_validated())
            self.assertEqual(blob_size, blob.length)
            return

        d = send_to_server()
        d.addCallback(lambda _: verify_blob_on_reflector())
        d.addCallback(lambda _: verify_stream_on_reflector())
        return d

    def test_blob_reflector(self):
        def verify_data_on_reflector():
            check_blob_ds = []
            for blob_hash, blob_size in self.expected_blobs:
                check_blob_ds.append(verify_have_blob(blob_hash, blob_size))
            return defer.DeferredList(check_blob_ds)

        def verify_have_blob(blob_hash, blob_size):
            d = self.server_blob_manager.get_blob(blob_hash)
            d.addCallback(lambda blob: verify_blob_completed(blob, blob_size))
            return d

        def send_to_server(blob_hashes_to_send):
            factory = reflector.BlobClientFactory(
                self.session.blob_manager,
                blob_hashes_to_send
            )

            from twisted.internet import reactor
            reactor.connectTCP('localhost', self.port, factory)
            return factory.finished_deferred

        def verify_blob_completed(blob, blob_size):
            self.assertTrue(blob.is_validated())
            self.assertEqual(blob_size, blob.length)

        d = send_to_server([x[0] for x in self.expected_blobs])
        d.addCallback(lambda _: verify_data_on_reflector())
        return d

    def test_blob_reflector_v1(self):
        def verify_data_on_reflector():
            check_blob_ds = []
            for blob_hash, blob_size in self.expected_blobs:
                check_blob_ds.append(verify_have_blob(blob_hash, blob_size))
            return defer.DeferredList(check_blob_ds)

        def verify_have_blob(blob_hash, blob_size):
            d = self.server_blob_manager.get_blob(blob_hash)
            d.addCallback(lambda blob: verify_blob_completed(blob, blob_size))
            return d

        def send_to_server(blob_hashes_to_send):
            factory = reflector.BlobClientFactory(
                self.session.blob_manager,
                blob_hashes_to_send
            )
            factory.protocol_version = 0

            from twisted.internet import reactor
            reactor.connectTCP('localhost', self.port, factory)
            return factory.finished_deferred

        def verify_blob_completed(blob, blob_size):
            self.assertTrue(blob.is_validated())
            self.assertEqual(blob_size, blob.length)

        d = send_to_server([x[0] for x in self.expected_blobs])
        d.addCallback(lambda _: verify_data_on_reflector())
        return d


def iv_generator():
    iv = 0
    while True:
        iv += 1
        yield "%016d" % iv
