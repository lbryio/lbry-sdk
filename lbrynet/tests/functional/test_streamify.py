import os
import shutil
import tempfile

from hashlib import md5
from twisted.trial.unittest import TestCase
from twisted.internet import defer, threads

from lbrynet import conf
from lbrynet.file_manager.EncryptedFileManager import EncryptedFileManager
from lbrynet.core.Session import Session
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier
from lbrynet.file_manager.EncryptedFileCreator import create_lbry_file
from lbrynet.lbry_file.client.EncryptedFileOptions import add_lbry_file_to_sd_identifier
from lbrynet.core.StreamDescriptor import get_sd_info
from lbrynet.core.PeerManager import PeerManager
from lbrynet.core.RateLimiter import DummyRateLimiter
from lbrynet.daemon.Component import ComponentManager
from lbrynet.daemon.Components import DHTComponent

from lbrynet.tests import mocks


FakeNode = mocks.Node
FakeWallet = mocks.Wallet
FakePeerFinder = mocks.PeerFinder
FakeAnnouncer = mocks.Announcer
GenFile = mocks.GenFile
test_create_stream_sd_file = mocks.create_stream_sd_file
DummyBlobAvailabilityTracker = mocks.BlobAvailabilityTracker


class MockDHTComponent(DHTComponent):
    def __init__(self, component_manager):
        super(DHTComponent, self).__init__(component_manager)
        self.peer_manager = PeerManager()
        self.peer_finder = FakePeerFinder(3333, self.peer_manager, 1)

    def setup(self):
        self.dht_node = FakeNode()
        return super(MockDHTComponent, self).setup()


class TestStreamify(TestCase):
    maxDiff = 5000

    def setUp(self):
        mocks.mock_conf_settings(self)
        self.component_manager = ComponentManager(None, dht=MockDHTComponent)
        self.session = None
        self.lbry_file_manager = None
        self.is_generous = True
        self.db_dir = tempfile.mkdtemp()
        self.blob_dir = os.path.join(self.db_dir, "blobfiles")
        self.dht_node = self.component_manager.get_component("dht")
        self.wallet = FakeWallet()
        self.peer_manager = PeerManager()
        self.peer_finder = FakePeerFinder(5553, self.peer_manager, 2)
        self.rate_limiter = DummyRateLimiter()
        self.sd_identifier = StreamDescriptorIdentifier()
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
        yield self.session.storage.stop()
        yield threads.deferToThread(shutil.rmtree, self.db_dir)
        if os.path.exists("test_file"):
            os.remove("test_file")

    def setUpDHTComponent(self):
        self.dht_component = ComponentManager.get_component('dht')
        self.dht_component.dht_node_class = FakeNode
        self.dht_component.hash_announcer = FakeAnnouncer()
        self.dht_component.setup()
        return self.dht_component.dht_node

    def test_create_stream(self):

        self.session = Session(
            conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=self.db_dir, node_id="abcd", peer_finder=self.peer_finder,
            blob_dir=self.blob_dir, peer_port=5553, use_upnp=False, rate_limiter=self.rate_limiter, wallet=self.wallet,
            blob_tracker_class=DummyBlobAvailabilityTracker, external_ip="127.0.0.1", dht_node=self.dht_node
        )

        self.lbry_file_manager = EncryptedFileManager(self.session, self.sd_identifier)

        d = self.session.setup()
        d.addCallback(lambda _: add_lbry_file_to_sd_identifier(self.sd_identifier))
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

        self.session = Session(
            conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=self.db_dir, node_id="abcd", peer_finder=self.peer_finder,
            blob_dir=self.blob_dir, peer_port=5553, use_upnp=False, rate_limiter=self.rate_limiter, wallet=self.wallet,
            blob_tracker_class=DummyBlobAvailabilityTracker, external_ip="127.0.0.1", dht_node=self.dht_node
        )

        self.lbry_file_manager = EncryptedFileManager(self.session, self.sd_identifier)

        @defer.inlineCallbacks
        def create_stream():
            test_file = GenFile(53209343, b''.join([chr(i + 5) for i in xrange(0, 64, 6)]))
            lbry_file = yield create_lbry_file(self.session, self.lbry_file_manager, "test_file", test_file)
            sd_hash = yield self.session.storage.get_sd_blob_hash_for_stream(lbry_file.stream_hash)
            self.assertTrue(lbry_file.sd_hash, sd_hash)
            yield lbry_file.start()
            f = open('test_file')
            hashsum = md5()
            hashsum.update(f.read())
            self.assertEqual(hashsum.hexdigest(), "68959747edc73df45e45db6379dd7b3b")

        d = self.session.setup()
        d.addCallback(lambda _: add_lbry_file_to_sd_identifier(self.sd_identifier))
        d.addCallback(lambda _: self.lbry_file_manager.setup())
        d.addCallback(lambda _: create_stream())
        return d