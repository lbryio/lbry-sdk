from lbrynet.core.client.DHTPeerFinder import DHTPeerFinder
from lbrynet.core.PeerManager import PeerManager
from lbrynet import conf
from twisted.trial import unittest
from twisted.internet import defer,reactor

conf.initialize_settings()

class MocDHTNode(object):
    def __init__(self):
        pass
    # return two peers, and a known blob peer
    def getPeersForBlob(self,bin_hash):
        return defer.succeed([('0.0.0.0',33),('0.0.0.1',33),conf.settings['known_blob_peers'][0]])

# Some simple tests, for functionality not dependent on other classes
class TestDHTPeerFinder(unittest.TestCase):
    def setUp(self):
        pass

    @defer.inlineCallbacks
    def test_default_blob_peers(self):
        default_blob_peers = conf.settings['known_blob_peers']

        peer_manager = PeerManager()
        dht_node = MocDHTNode()
        peer_finder = DHTPeerFinder(dht_node,peer_manager)

        peers = yield peer_finder.find_peers_for_blob(blob_hash='0000')
        # should return the two peers in MocDHTNode and the default blob peers 
        self.assertEqual(len(peers), 2+len(default_blob_peers))

