import os
import shutil

from twisted.internet import defer, threads, error
from twisted.trial import unittest

from lbrynet import conf
from lbrynet import lbryfile
from lbrynet import reflector
from lbrynet.core import BlobManager
from lbrynet.core import PeerManager
from lbrynet.core import RateLimiter
from lbrynet.core import Storage
from lbrynet.core import Session
from lbrynet.core import StreamDescriptor
from lbrynet.dht.node import Node
from lbrynet.lbryfile.EncryptedFileMetadataManager import DBEncryptedFileMetadataManager
from lbrynet.lbryfile.client import EncryptedFileOptions
from lbrynet.lbryfilemanager import EncryptedFileCreator
from lbrynet.lbryfilemanager import EncryptedFileManager

from tests import mocks


class TestReflector(unittest.TestCase):
    def setUp(self):
        mocks.mock_conf_settings(self)
        self.server_session = None
        self.client_session = None
        self.stream_info_manager = None
        self.lbry_file_manager = None
        self.server_blob_storage = None
        self.server_blob_manager = None
        self.reflector_port = None
        self.port = None
        self.addCleanup(self.take_down_env)
        client_wallet = mocks.Wallet()
        client_peer_manager = PeerManager.PeerManager()
        client_peer_finder = mocks.PeerFinder(5553, client_peer_manager, 2)
        client_hash_announcer = mocks.Announcer()
        client_rate_limiter = RateLimiter.DummyRateLimiter()
        client_sd_identifier = StreamDescriptor.StreamDescriptorIdentifier()

        server_wallet = mocks.Wallet()
        server_peer_manager = PeerManager.PeerManager()
        server_peer_finder = mocks.PeerFinder(5553, server_peer_manager, 2)
        server_hash_announcer = mocks.Announcer()
        server_rate_limiter = RateLimiter.DummyRateLimiter()
        server_sd_identifier = StreamDescriptor.StreamDescriptorIdentifier()

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

        client_db_dir = "client"
        os.mkdir(client_db_dir)

        server_db_dir = "server"
        os.mkdir(server_db_dir)

        client_storage = Storage.FileStorage(client_db_dir)
        server_storage = Storage.FileStorage(server_db_dir)

        client_blob_manager = BlobManager.DiskBlobManager(client_hash_announcer,
                                                          client_db_dir,
                                                          client_storage)
        server_blob_manager = BlobManager.DiskBlobManager(server_hash_announcer,
                                                          server_db_dir,
                                                          server_storage)

        self.client_session = Session.Session(
            conf.settings['data_rate'],
            db_dir=client_db_dir,
            lbryid="abcd",
            peer_finder=client_peer_finder,
            hash_announcer=client_hash_announcer,
            blob_dir=None,
            peer_port=5553,
            use_upnp=False,
            rate_limiter=client_rate_limiter,
            wallet=client_wallet,
            blob_tracker_class=mocks.BlobAvailabilityTracker,
            dht_node_class=Node,
            blob_manager=client_blob_manager
        )

        self.server_session = Session.Session(
            conf.settings['data_rate'],
            db_dir=server_db_dir,
            lbryid="efgh",
            peer_finder=server_peer_finder,
            hash_announcer=server_hash_announcer,
            blob_dir=None,
            peer_port=5553,
            use_upnp=False,
            rate_limiter=server_rate_limiter,
            wallet=server_wallet,
            blob_tracker_class=mocks.BlobAvailabilityTracker,
            dht_node_class=Node,
            blob_manager=server_blob_manager
        )

        self.client_stream_info_manager = DBEncryptedFileMetadataManager(self.client_session.storage)
        self.client_lbry_file_manager = EncryptedFileManager.EncryptedFileManager(
            self.client_session, self.client_stream_info_manager, client_sd_identifier)

        self.server_stream_info_manager = DBEncryptedFileMetadataManager(self.server_session.storage)
        self.server_lbry_file_manager = EncryptedFileManager.EncryptedFileManager(
            self.server_session, self.server_stream_info_manager, server_sd_identifier)

        d = self.client_session.setup()
        d.addCallback(lambda _: self.client_stream_info_manager.setup())
        d.addCallback(lambda _: EncryptedFileOptions.add_lbry_file_to_sd_identifier(client_sd_identifier))
        d.addCallback(lambda _: self.client_lbry_file_manager.setup())
        d.addCallback(lambda _: self.server_session.setup())
        d.addCallback(lambda _: self.server_stream_info_manager.setup())
        d.addCallback(lambda _: EncryptedFileOptions.add_lbry_file_to_sd_identifier(server_sd_identifier))
        d.addCallback(lambda _: self.server_lbry_file_manager.setup())

        def verify_equal(sd_info):
            self.assertEqual(mocks.create_stream_sd_file, sd_info)

        def save_sd_blob_hash(sd_hash):
            self.expected_blobs.append((sd_hash, 923))

        @defer.inlineCallbacks
        def create_stream():
            test_file = mocks.GenFile(5209343, b''.join([chr(i + 3) for i in xrange(0, 64, 6)]))
            self.stream_hash = yield EncryptedFileCreator.create_lbry_file(
                self.client_session,
                self.client_lbry_file_manager,
                "test_file",
                test_file,
                key="0123456701234567",
                iv_generator=iv_generator()
            )

            sd_hash = yield lbryfile.publish_sd_blob(
                self.client_lbry_file_manager.stream_info_manager,
                self.client_session.blob_manager, self.stream_hash
            )
            prm = self.client_session.payment_rate_manager
            yield self.client_lbry_file_manager.add_lbry_file(self.stream_hash, prm)
            sd_info = yield lbryfile.get_sd_info(self.client_stream_info_manager, self.stream_hash, True)
            yield verify_equal(sd_info)
            save_sd_blob_hash(sd_hash)
            defer.returnValue(self.stream_hash)

        def start_server():
            server_factory = reflector.ServerFactory(server_peer_manager, self.server_session.blob_manager)
            from twisted.internet import reactor
            port = 8943
            while self.reflector_port is None:
                try:
                    self.reflector_port = reactor.listenTCP(port, server_factory)
                    self.port = port
                except error.CannotListenError:
                    port += 1

        d.addCallback(lambda _: create_stream())
        d.addCallback(lambda _: start_server())
        return d

    def take_down_env(self):
        d = defer.succeed(True)

        if self.client_lbry_file_manager is not None:
            d.addCallback(lambda _: self.client_lbry_file_manager.stop())
        if self.client_session is not None:
            d.addCallback(lambda _: self.client_session.shut_down())
        if self.client_stream_info_manager is not None:
            d.addCallback(lambda _: self.client_stream_info_manager.stop())

        if self.server_lbry_file_manager is not None:
            d.addCallback(lambda _: self.server_lbry_file_manager.stop())
        if self.server_session is not None:
            d.addCallback(lambda _: self.server_session.shut_down())
        if self.server_stream_info_manager is not None:
            d.addCallback(lambda _: self.server_stream_info_manager.stop())

        if self.reflector_port is not None:
            d.addCallback(lambda _: self.reflector_port.stopListening())

        def delete_test_env():
            try:
                shutil.rmtree('client')
                shutil.rmtree('server')
            except:
                raise unittest.SkipTest("TODO: fix this for windows")

        d.addCallback(lambda _: threads.deferToThread(delete_test_env))
        d.addErrback(lambda err: str(err))
        return d

    def test_stream_reflector(self):
        def verify_data_on_reflector():
            check_blob_ds = []
            for blob_hash, blob_size in self.expected_blobs:
                check_blob_ds.append(verify_have_blob(blob_hash, blob_size))
            return defer.DeferredList(check_blob_ds)

        def verify_have_blob(blob_hash, blob_size):
            d = self.server_session.blob_manager.get_blob(blob_hash)
            d.addCallback(lambda blob: verify_blob_completed(blob, blob_size))
            return d

        def send_to_server():
            fake_lbry_file = mocks.FakeLBRYFile(self.client_session.blob_manager,
                                                self.client_stream_info_manager,
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
        d.addCallback(lambda _: verify_data_on_reflector())
        return d

    def test_blob_reflector(self):
        def verify_data_on_reflector():
            check_blob_ds = []
            for blob_hash, blob_size in self.expected_blobs:
                check_blob_ds.append(verify_have_blob(blob_hash, blob_size))
            return defer.DeferredList(check_blob_ds)

        def verify_have_blob(blob_hash, blob_size):
            d = self.server_session.blob_manager.get_blob(blob_hash)
            d.addCallback(lambda blob: verify_blob_completed(blob, blob_size))
            return d

        def send_to_server(blob_hashes_to_send):
            factory = reflector.BlobClientFactory(
                self.client_session.blob_manager,
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
            d = self.server_session.blob_manager.get_blob(blob_hash)
            d.addCallback(lambda blob: verify_blob_completed(blob, blob_size))
            return d

        def send_to_server(blob_hashes_to_send):
            factory = reflector.BlobClientFactory(
                self.client_session.blob_manager,
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
