import tempfile
import shutil
from twisted.trial import unittest
from twisted.internet import defer, reactor, threads

from lbrynet.tests.util import random_lbry_hash
from lbrynet.dht.hashannouncer import DHTHashAnnouncer
from lbrynet.core.call_later_manager import CallLaterManager
from lbrynet.database.storage import SQLiteStorage


class MocDHTNode(object):
    def __init__(self, announce_will_fail=False):
        # if announce_will_fail is True,
        # announceHaveBlob will return empty dict
        self.call_later_manager = CallLaterManager
        self.call_later_manager.setup(reactor.callLater)
        self.blobs_announced = 0
        self.announce_will_fail = announce_will_fail

    def announceHaveBlob(self, blob):
        if self.announce_will_fail:
            return_val = {}
        else:
            return_val = {blob: ["ab"*48]}

        self.blobs_announced += 1
        d = defer.Deferred()
        self.call_later_manager.call_later(1, d.callback, return_val)
        return d


class DHTHashAnnouncerTest(unittest.TestCase):
    @defer.inlineCallbacks
    def setUp(self):
        from lbrynet.conf import initialize_settings
        initialize_settings(False)
        self.num_blobs = 10
        self.blobs_to_announce = []
        for i in range(0, self.num_blobs):
            self.blobs_to_announce.append(random_lbry_hash())
        self.dht_node = MocDHTNode()
        self.dht_node.peerPort = 3333
        self.dht_node.clock = reactor
        self.db_dir = tempfile.mkdtemp()
        self.storage = SQLiteStorage(self.db_dir)
        yield self.storage.setup()
        self.announcer = DHTHashAnnouncer(self.dht_node, self.storage, 10)
        for blob_hash in self.blobs_to_announce:
            yield self.storage.add_completed_blob(blob_hash, 100, 0, 1)

    @defer.inlineCallbacks
    def tearDown(self):
        self.dht_node.call_later_manager.stop()
        yield self.storage.stop()
        yield threads.deferToThread(shutil.rmtree, self.db_dir)

    @defer.inlineCallbacks
    def test_announce_fail(self):
        # test what happens when node.announceHaveBlob() returns empty dict
        self.dht_node.announce_will_fail = True
        d = yield self.announcer.manage()
        yield d

    @defer.inlineCallbacks
    def test_basic(self):
        d = self.announcer.immediate_announce(self.blobs_to_announce)
        self.assertEqual(len(self.announcer.hash_queue), self.num_blobs)
        yield d
        self.assertEqual(self.dht_node.blobs_announced, self.num_blobs)
        self.assertEqual(len(self.announcer.hash_queue), 0)

    @defer.inlineCallbacks
    def test_immediate_announce(self):
        # Test that immediate announce puts a hash at the front of the queue
        d = self.announcer.immediate_announce(self.blobs_to_announce)
        self.assertEqual(len(self.announcer.hash_queue), self.num_blobs)
        blob_hash = random_lbry_hash()
        self.announcer.immediate_announce([blob_hash])
        self.assertEqual(len(self.announcer.hash_queue), self.num_blobs+1)
        self.assertEqual(blob_hash, self.announcer.hash_queue[-1])
        yield d
