from twisted.trial import unittest
from twisted.internet import defer, task
from lbrynet import conf
from lbrynet.core import utils
from lbrynet.dht.hashannouncer import DHTHashAnnouncer
from lbrynet.tests.util import random_lbry_hash


class MocDHTNode(object):
    def __init__(self):
        self.blobs_announced = 0
        self.clock = task.Clock()
        self.peerPort = 3333

    def announceHaveBlob(self, blob):
        self.blobs_announced += 1
        d = defer.Deferred()
        self.clock.callLater(1, d.callback, ['fake'])
        return d


class MocStorage(object):
    def __init__(self, blobs_to_announce):
        self.blobs_to_announce = blobs_to_announce
        self.announced = False

    def get_blobs_to_announce(self):
        if not self.announced:
            self.announced = True
            return defer.succeed(self.blobs_to_announce)
        else:
            return defer.succeed([])

    def update_last_announced_blob(self, blob_hash, now):
        return defer.succeed(None)


class DHTHashAnnouncerTest(unittest.TestCase):

    def setUp(self):
        conf.initialize_settings(False)
        self.num_blobs = 10
        self.blobs_to_announce = []
        for i in range(0, self.num_blobs):
            self.blobs_to_announce.append(random_lbry_hash())
        self.dht_node = MocDHTNode()
        self.clock = self.dht_node.clock
        utils.call_later = self.clock.callLater
        self.storage = MocStorage(self.blobs_to_announce)
        self.announcer = DHTHashAnnouncer(self.dht_node, self.storage)

    @defer.inlineCallbacks
    def test_immediate_announce(self):
        announce_d = self.announcer.immediate_announce(self.blobs_to_announce)
        self.assertEqual(self.announcer.hash_queue_size(), self.num_blobs)
        self.clock.advance(1)
        yield announce_d
        self.assertEqual(self.dht_node.blobs_announced, self.num_blobs)
        self.assertEqual(self.announcer.hash_queue_size(), 0)
