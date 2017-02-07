import os
import binascii
from twisted.trial import unittest
from twisted.internet import defer,task
from lbrynet.core.server.DHTHashAnnouncer import DHTHashAnnouncer,DHTHashSupplier
from lbrynet.core.utils import random_string
from lbrynet.core import log_support


class MocDHTNode(object):
    def __init__(self):
        self.blobs_announced = 0

    def announceHaveBlob(self,blob,port):
        self.blobs_announced += 1
        return defer.succeed(True)

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

class DHTHashAnnouncerTest(unittest.TestCase):

    def setUp(self):
        self.num_blobs = 10
        self.blobs_to_announce = []
        for i in range(0, self.num_blobs):
            self.blobs_to_announce.append(binascii.b2a_hex(os.urandom(32)))
        self.clock = task.Clock()
        self.dht_node = MocDHTNode()
        self.announcer = DHTHashAnnouncer(self.dht_node, peer_port=3333)
        self.announcer.callLater = self.clock.callLater
        self.supplier = MocSupplier(self.blobs_to_announce)
        self.announcer.add_supplier(self.supplier)

    def test_basic(self):
        self.announcer._announce_available_hashes()
        self.clock.advance(1)
        self.assertEqual(self.dht_node.blobs_announced, self.num_blobs)
        self.assertEqual(self.announcer.hash_queue_size(), 0)



