import struct
from twisted.internet import defer
from lbrynet.dht import constants
from lbrynet.core.utils import generate_id
from dht_test_environment import TestKademliaBase
import logging

log = logging.getLogger()


class TestStoreExpiration(TestKademliaBase):
    network_size = 40

    @defer.inlineCallbacks
    def test_store_and_expire(self):
        blob_hash = generate_id(1)
        announcing_node = self.nodes[20]
        # announce the blob
        announce_d = announcing_node.announceHaveBlob(blob_hash)
        self.pump_clock(5)
        storing_node_ids = yield announce_d
        all_nodes = set(self.nodes).union(set(self._seeds))

        # verify the nodes we think stored it did actually store it
        storing_nodes = [node for node in all_nodes if node.node_id.encode('hex') in storing_node_ids]
        self.assertEquals(len(storing_nodes), len(storing_node_ids))
        self.assertEquals(len(storing_nodes), constants.k)
        for node in storing_nodes:
            self.assertTrue(node._dataStore.hasPeersForBlob(blob_hash))
            datastore_result = node._dataStore.getPeersForBlob(blob_hash)
            self.assertEquals(map(lambda contact: (contact.id, contact.address, contact.port),
                                  node._dataStore.getStoringContacts()), [(announcing_node.node_id,
                                                                           announcing_node.externalIP,
                                                                           announcing_node.port)])
            self.assertEquals(len(datastore_result), 1)
            expanded_peers = []
            for peer in datastore_result:
                host = ".".join([str(ord(d)) for d in peer[:4]])
                port, = struct.unpack('>H', peer[4:6])
                peer_node_id = peer[6:]
                if (host, port, peer_node_id) not in expanded_peers:
                    expanded_peers.append((peer_node_id, host, port))
            self.assertEquals(expanded_peers[0],
                              (announcing_node.node_id, announcing_node.externalIP, announcing_node.peerPort))

        # verify the announced blob expires in the storing nodes datastores

        self.clock.advance(constants.dataExpireTimeout)         # skip the clock directly ahead
        for node in storing_nodes:
            self.assertFalse(node._dataStore.hasPeersForBlob(blob_hash))
            datastore_result = node._dataStore.getPeersForBlob(blob_hash)
            self.assertEquals(len(datastore_result), 0)
            self.assertTrue(blob_hash in node._dataStore._dict)  # the looping call shouldn't have removed it yet
            self.assertEquals(len(node._dataStore.getStoringContacts()), 1)

        self.pump_clock(constants.checkRefreshInterval + 1)  # tick the clock forward (so the nodes refresh)
        for node in storing_nodes:
            self.assertFalse(node._dataStore.hasPeersForBlob(blob_hash))
            datastore_result = node._dataStore.getPeersForBlob(blob_hash)
            self.assertEquals(len(datastore_result), 0)
            self.assertEquals(len(node._dataStore.getStoringContacts()), 0)
            self.assertTrue(blob_hash not in node._dataStore._dict)  # the looping call should have fired

    @defer.inlineCallbacks
    def test_storing_node_went_stale_then_came_back(self):
        blob_hash = generate_id(1)
        announcing_node = self.nodes[20]
        # announce the blob
        announce_d = announcing_node.announceHaveBlob(blob_hash)
        self.pump_clock(5)
        storing_node_ids = yield announce_d
        all_nodes = set(self.nodes).union(set(self._seeds))

        # verify the nodes we think stored it did actually store it
        storing_nodes = [node for node in all_nodes if node.node_id.encode('hex') in storing_node_ids]
        self.assertEquals(len(storing_nodes), len(storing_node_ids))
        self.assertEquals(len(storing_nodes), constants.k)
        for node in storing_nodes:
            self.assertTrue(node._dataStore.hasPeersForBlob(blob_hash))
            datastore_result = node._dataStore.getPeersForBlob(blob_hash)
            self.assertEquals(map(lambda contact: (contact.id, contact.address, contact.port),
                                  node._dataStore.getStoringContacts()), [(announcing_node.node_id,
                                                                           announcing_node.externalIP,
                                                                           announcing_node.port)])
            self.assertEquals(len(datastore_result), 1)
            expanded_peers = []
            for peer in datastore_result:
                host = ".".join([str(ord(d)) for d in peer[:4]])
                port, = struct.unpack('>H', peer[4:6])
                peer_node_id = peer[6:]
                if (host, port, peer_node_id) not in expanded_peers:
                    expanded_peers.append((peer_node_id, host, port))
            self.assertEquals(expanded_peers[0],
                              (announcing_node.node_id, announcing_node.externalIP, announcing_node.peerPort))

        self.pump_clock(constants.checkRefreshInterval*2)

        # stop the node
        self.nodes.remove(announcing_node)
        yield self.run_reactor(31, [announcing_node.stop()])
        # run the network for an hour, which should expire the removed node and turn the announced value stale
        self.pump_clock(constants.checkRefreshInterval * 5, constants.checkRefreshInterval/2)
        self.verify_all_nodes_are_routable()

        # make sure the contact isn't returned as a peer for the blob, but that we still have the entry in the
        # datastore in case the node comes back
        for node in storing_nodes:
            self.assertFalse(node._dataStore.hasPeersForBlob(blob_hash))
            datastore_result = node._dataStore.getPeersForBlob(blob_hash)
            self.assertEquals(len(datastore_result), 0)
            self.assertEquals(len(node._dataStore.getStoringContacts()), 1)
            self.assertTrue(blob_hash in node._dataStore._dict)

        # # bring the announcing node back online
        self.nodes.append(announcing_node)
        yield self.run_reactor(
            31, [announcing_node.start([(seed_name, 4444) for seed_name in sorted(self.seed_dns.keys())])]
        )
        self.pump_clock(constants.checkRefreshInterval * 2)
        self.verify_all_nodes_are_routable()

        # now the announcing node should once again be returned as a peer for the blob
        for node in storing_nodes:
            self.assertTrue(node._dataStore.hasPeersForBlob(blob_hash))
            datastore_result = node._dataStore.getPeersForBlob(blob_hash)
            self.assertEquals(len(datastore_result), 1)
            self.assertEquals(len(node._dataStore.getStoringContacts()), 1)
            self.assertTrue(blob_hash in node._dataStore._dict)

        # verify the announced blob expires in the storing nodes datastores
        self.clock.advance(constants.dataExpireTimeout)  # skip the clock directly ahead
        for node in storing_nodes:
            self.assertFalse(node._dataStore.hasPeersForBlob(blob_hash))
            datastore_result = node._dataStore.getPeersForBlob(blob_hash)
            self.assertEquals(len(datastore_result), 0)
            self.assertTrue(blob_hash in node._dataStore._dict)  # the looping call shouldn't have removed it yet
            self.assertEquals(len(node._dataStore.getStoringContacts()), 1)

        self.pump_clock(constants.checkRefreshInterval + 1)  # tick the clock forward (so the nodes refresh)
        for node in storing_nodes:
            self.assertFalse(node._dataStore.hasPeersForBlob(blob_hash))
            datastore_result = node._dataStore.getPeersForBlob(blob_hash)
            self.assertEquals(len(datastore_result), 0)
            self.assertEquals(len(node._dataStore.getStoringContacts()), 0)
            self.assertTrue(blob_hash not in node._dataStore._dict)  # the looping call should have fired
