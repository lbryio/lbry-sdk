import os
from unittest import skip
from binascii import hexlify

from twisted.internet import defer, error
from twisted.trial import unittest
from lbrynet.stream.descriptor import get_sd_info
from lbrynet.extras.reflector.server.server import ReflectorServerFactory
from lbrynet.extras.reflector.client.client import EncryptedFileReflectorClientFactory
from lbrynet.extras.reflector.client.blob import BlobReflectorClientFactory
from lbrynet.peer import PeerManager
from lbrynet.staging import EncryptedFileCreator
from lbrynet.blob import blob_manager
from lbrynet.stream import descriptor
from lbrynet.staging.EncryptedFileManager import EncryptedFileManager
from lbrynet.staging.rate_limiter import RateLimiter
from lbrynet.storage import SQLiteStorage
from lbrynet.blob_exchange.price_negotiation import OnlyFreePaymentsManager
from tests import mocks
from tests.test_utils import mk_db_and_blob_dir, rm_db_and_blob_dir


@skip
class TestReflector(unittest.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        self.reflector_port = None
        self.port = None
        mocks.mock_conf_settings(self)
        self.server_db_dir, self.server_blob_dir = mk_db_and_blob_dir()
        self.client_db_dir, self.client_blob_dir = mk_db_and_blob_dir()
        prm = OnlyFreePaymentsManager()
        wallet = mocks.Wallet()
        peer_manager = PeerManager()
        peer_finder = mocks.PeerFinder(5553, peer_manager, 2)
        self.server_storage = SQLiteStorage(':memory:')
        self.server_blob_manager = BlobManager.DiskBlobManager(self.server_blob_dir, self.server_storage)
        self.client_storage = SQLiteStorage(':memory:')
        self.client_blob_manager = BlobManager.DiskBlobManager(self.client_blob_dir, self.client_storage)
        self.server_lbry_file_manager = EncryptedFileManager(
            peer_finder, RateLimiter(), self.server_blob_manager, wallet, prm, self.server_storage,
            descriptor.StreamDescriptorIdentifier()
        )
        self.client_lbry_file_manager = EncryptedFileManager(
            peer_finder, RateLimiter(), self.client_blob_manager, wallet, prm, self.client_storage,
            descriptor.StreamDescriptorIdentifier()
        )

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

        yield f2d(self.server_storage.open())
        yield f2d(self.server_blob_manager.setup())
        yield f2d(self.server_lbry_file_manager.setup())
        yield f2d(self.client_storage.open())
        yield f2d(self.client_blob_manager.setup())
        yield f2d(self.client_lbry_file_manager.setup())

        @defer.inlineCallbacks
        def verify_equal(sd_info, stream_hash):
            self.assertDictEqual(mocks.create_stream_sd_file, sd_info)
            sd_hash = yield f2d(self.client_storage.get_sd_blob_hash_for_stream(stream_hash))
            defer.returnValue(sd_hash)

        def save_sd_blob_hash(sd_hash):
            self.sd_hash = sd_hash
            self.expected_blobs.append((sd_hash, 923))

        def verify_stream_descriptor_file(stream_hash):
            self.stream_hash = stream_hash
            d = f2d(get_sd_info(self.client_storage, stream_hash, True))
            d.addCallback(verify_equal, stream_hash)
            d.addCallback(save_sd_blob_hash)
            return d

        def create_stream():
            test_file = mocks.GenFile(5209343, bytes((i + 3) for i in range(0, 64, 6)))
            d = EncryptedFileCreator.create_lbry_file(
                self.client_blob_manager, self.client_storage, prm, self.client_lbry_file_manager,
                "test_file",
                test_file,
                key=b"0123456701234567",
                iv_generator=iv_generator()
            )
            d.addCallback(lambda lbry_file: lbry_file.stream_hash)
            return d

        def start_server():
            server_factory = ReflectorServerFactory(peer_manager, self.server_blob_manager,
                                                     self.server_lbry_file_manager)
            from twisted.internet import reactor
            port = 8943
            while self.reflector_port is None:
                try:
                    self.reflector_port = reactor.listenTCP(port, server_factory)
                    self.port = port
                except error.CannotListenError:
                    port += 1

        stream_hash = yield create_stream()
        yield verify_stream_descriptor_file(stream_hash)
        yield start_server()

    @defer.inlineCallbacks
    def tearDown(self):
        lbry_files = self.client_lbry_file_manager.lbry_files
        for lbry_file in lbry_files:
            yield self.client_lbry_file_manager.delete_lbry_file(lbry_file)
        yield self.client_lbry_file_manager.stop()
        yield f2d(self.client_storage.close())
        self.reflector_port.stopListening()
        lbry_files = self.server_lbry_file_manager.lbry_files
        for lbry_file in lbry_files:
            yield self.server_lbry_file_manager.delete_lbry_file(lbry_file)
        yield self.server_lbry_file_manager.stop()
        yield f2d(self.server_storage.close())
        try:
            rm_db_and_blob_dir(self.client_db_dir, self.client_blob_dir)
        except Exception as err:
            raise unittest.SkipTest("TODO: fix this for windows")
        try:
            rm_db_and_blob_dir(self.server_db_dir, self.server_blob_dir)
        except Exception as err:
            raise unittest.SkipTest("TODO: fix this for windows")
        if os.path.exists("test_file"):
            os.remove("test_file")

    def test_stream_reflector(self):
        def verify_blob_on_reflector():
            check_blob_ds = []
            for blob_hash, blob_size in self.expected_blobs:
                check_blob_ds.append(verify_have_blob(blob_hash, blob_size))
            return defer.DeferredList(check_blob_ds)

        @defer.inlineCallbacks
        def verify_stream_on_reflector():
            # check stream_info_manager has all the right information
            streams = yield f2d(self.server_storage.get_all_streams())
            self.assertEqual(1, len(streams))
            self.assertEqual(self.stream_hash, streams[0])

            blobs = yield f2d(self.server_storage.get_blobs_for_stream(self.stream_hash))
            blob_hashes = [b.blob_hash for b in blobs if b.blob_hash is not None]
            expected_blob_hashes = [b[0] for b in self.expected_blobs[:-1] if b[0] is not None]
            self.assertEqual(expected_blob_hashes, blob_hashes)
            sd_hash = yield f2d(self.server_storage.get_sd_blob_hash_for_stream(streams[0]))
            self.assertEqual(self.sd_hash, sd_hash)

            # check lbry file manager has the file
            files = yield self.server_lbry_file_manager.lbry_files

            self.assertEqual(0, len(files))

            streams = yield f2d(self.server_storage.get_all_streams())
            self.assertEqual(1, len(streams))
            stream_info = yield f2d(self.server_storage.get_stream_info(self.stream_hash))
            self.assertEqual(self.sd_hash, stream_info[3])
            self.assertEqual(hexlify(b'test_file').decode(), stream_info[0])

            # check should_announce blobs on blob_manager
            blob_hashes = yield f2d(self.server_storage.get_all_should_announce_blobs())
            self.assertSetEqual({self.sd_hash, expected_blob_hashes[0]}, set(blob_hashes))

        def verify_have_blob(blob_hash, blob_size):
            d = self.server_blob_manager.get_blob(blob_hash)
            d.addCallback(lambda blob: verify_blob_completed(blob, blob_size))
            return d

        def send_to_server():
            factory = EncryptedFileReflectorClientFactory(self.client_blob_manager, self.stream_hash, self.sd_hash)

            from twisted.internet import reactor
            reactor.connectTCP('localhost', self.port, factory)
            return factory.finished_deferred

        def verify_blob_completed(blob, blob_size):
            self.assertTrue(blob.get_is_verified())
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
            factory = BlobReflectorClientFactory(
                self.client_blob_manager,
                blob_hashes_to_send
            )

            from twisted.internet import reactor
            reactor.connectTCP('localhost', self.port, factory)
            return factory.finished_deferred

        def verify_blob_completed(blob, blob_size):
            self.assertTrue(blob.get_is_verified())
            self.assertEqual(blob_size, blob.length)

        d = send_to_server([x[0] for x in self.expected_blobs])
        d.addCallback(lambda _: verify_data_on_reflector())
        return d

    def test_blob_reflector_v1(self):
        @defer.inlineCallbacks
        def verify_stream_on_reflector():
            # this protocol should not have any impact on stream info manager
            streams = yield f2d(self.server_storage.get_all_streams())
            self.assertEqual(0, len(streams))
            # there should be no should announce blobs here
            blob_hashes = yield f2d(self.server_storage.get_all_should_announce_blobs())
            self.assertEqual(0, len(blob_hashes))

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
            factory = BlobReflectorClientFactory(
                self.client_blob_manager,
                blob_hashes_to_send
            )
            factory.protocol_version = 0

            from twisted.internet import reactor
            reactor.connectTCP('localhost', self.port, factory)
            return factory.finished_deferred

        def verify_blob_completed(blob, blob_size):
            self.assertTrue(blob.get_is_verified())
            self.assertEqual(blob_size, blob.length)

        d = send_to_server([x[0] for x in self.expected_blobs])
        d.addCallback(lambda _: verify_data_on_reflector())
        return d

    # test case when we reflect blob, and than that same blob
    # is reflected as stream
    @defer.inlineCallbacks
    def test_blob_reflect_and_stream(self):

        def verify_blob_on_reflector():
            check_blob_ds = []
            for blob_hash, blob_size in self.expected_blobs:
                check_blob_ds.append(verify_have_blob(blob_hash, blob_size))
            return defer.DeferredList(check_blob_ds)

        @defer.inlineCallbacks
        def verify_stream_on_reflector():
            # check stream_info_manager has all the right information

            streams = yield f2d(self.server_storage.get_all_streams())
            self.assertEqual(1, len(streams))
            self.assertEqual(self.stream_hash, streams[0])

            blobs = yield f2d(self.server_storage.get_blobs_for_stream(self.stream_hash))
            blob_hashes = [b.blob_hash for b in blobs if b.blob_hash is not None]
            expected_blob_hashes = [b[0] for b in self.expected_blobs[:-1] if b[0] is not None]
            self.assertEqual(expected_blob_hashes, blob_hashes)
            sd_hash = yield f2d(self.server_storage.get_sd_blob_hash_for_stream(self.stream_hash))
            self.assertEqual(self.sd_hash, sd_hash)

            # check should_announce blobs on blob_manager
            to_announce = yield f2d(self.server_storage.get_all_should_announce_blobs())
            self.assertSetEqual(set(to_announce), {self.sd_hash, expected_blob_hashes[0]})

        def verify_have_blob(blob_hash, blob_size):
            d = self.server_blob_manager.get_blob(blob_hash)
            d.addCallback(lambda blob: verify_blob_completed(blob, blob_size))
            return d

        def send_to_server_as_blobs(blob_hashes_to_send):
            factory = BlobReflectorClientFactory(
                self.client_blob_manager,
                blob_hashes_to_send
            )
            factory.protocol_version = 0

            from twisted.internet import reactor
            reactor.connectTCP('localhost', self.port, factory)
            return factory.finished_deferred

        def send_to_server_as_stream(result):
            factory = EncryptedFileReflectorClientFactory(self.client_blob_manager, self.stream_hash, self.sd_hash)

            from twisted.internet import reactor
            reactor.connectTCP('localhost', self.port, factory)
            return factory.finished_deferred

        def verify_blob_completed(blob, blob_size):
            self.assertTrue(blob.get_is_verified())
            self.assertEqual(blob_size, blob.length)

        # Modify this to change which blobs to send
        blobs_to_send = self.expected_blobs

        finished = yield send_to_server_as_blobs([x[0] for x in self.expected_blobs])
        yield send_to_server_as_stream(finished)
        yield verify_blob_on_reflector()
        yield verify_stream_on_reflector()


def iv_generator():
    iv = 0
    while True:
        iv += 1
        yield b"%016d" % iv
