from twisted.trial import unittest
from twisted.internet import defer, reactor

from lbrynet.tests.util import random_lbry_hash
from lbrynet.core.server.DHTHashAnnouncer import DHTHashAnnouncer


class MocDHTNode(object):
    def __init__(self):
        self.can_store = True
        self.blobs_announced = 0

    @defer.inlineCallbacks
    def announceHaveBlob(self, blob):
        self.blobs_announced += 1
        d = defer.Deferred(None)
        reactor.callLater(1, d.callback, {blob: ["ab" * 48]})
        result = yield d
        defer.returnValue(result)


class MocSupplier(object):
    def __init__(self, blobs_to_announce):
        self.blobs_to_announce = blobs_to_announce
        self.announced = False

    def hashes_to_announce(self):
        if not self.announced:
            self.announced = True
            return defer.succeed(self.blobs_to_announce)
        else:
            return defer.succeed([])

    def set_single_hash_announce_duration(self, seconds):
        pass

class DHTHashAnnouncerTest(unittest.TestCase):
    def setUp(self):
        self.num_blobs = 10
        self.blobs_to_announce = []
        for i in range(0, self.num_blobs):
            self.blobs_to_announce.append(random_lbry_hash())
        self.dht_node = MocDHTNode()
        self.announcer = DHTHashAnnouncer(self.dht_node, peer_port=3333)
        self.supplier = MocSupplier(self.blobs_to_announce)
        self.announcer.add_supplier(self.supplier)

    @defer.inlineCallbacks
    def test_basic(self):
        d = self.announcer._announce_available_hashes()
        self.assertEqual(self.announcer.hash_queue_size(), self.announcer.CONCURRENT_ANNOUNCERS)
        yield d
        self.assertEqual(self.dht_node.blobs_announced, self.num_blobs)
        self.assertEqual(self.announcer.hash_queue_size(), 0)

    @defer.inlineCallbacks
    def test_immediate_announce(self):
        # Test that immediate announce puts a hash at the front of the queue
        d = self.announcer._announce_available_hashes()
        self.assertEqual(self.announcer.hash_queue_size(), self.announcer.CONCURRENT_ANNOUNCERS)
        blob_hash = random_lbry_hash()
        self.announcer.immediate_announce([blob_hash])
        self.assertEqual(self.announcer.hash_queue_size(), self.announcer.CONCURRENT_ANNOUNCERS+1)
        self.assertEqual(blob_hash, self.announcer.hash_queue[0][0])
        yield d
