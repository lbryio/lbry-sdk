import asyncio
from binascii import hexlify

from lbry.extras.daemon.storage import SQLiteStorage
from lbry.conf import Config
from lbry.dht import constants
from lbry.dht.node import Node
from lbry.dht import peer as dht_peer
from lbry.dht.peer import PeerManager, make_kademlia_peer
from lbry.testcase import AsyncioTestCase


class DHTIntegrationTest(AsyncioTestCase):

    async def asyncSetUp(self):
        dht_peer.ALLOW_LOCALHOST = True
        self.addCleanup(setattr, dht_peer, 'ALLOW_LOCALHOST', False)
        import logging
        logging.getLogger('asyncio').setLevel(logging.ERROR)
        logging.getLogger('lbry.dht').setLevel(logging.WARN)
        self.nodes = []
        self.known_node_addresses = []

    async def create_node(self, node_id, port, external_ip='127.0.0.1'):
        storage = SQLiteStorage(Config(), ":memory:", self.loop, self.loop.time)
        await storage.open()
        node = Node(self.loop, PeerManager(self.loop), node_id=node_id,
                    udp_port=port, internal_udp_port=port,
                    peer_port=3333, external_ip=external_ip,
                    storage=storage)
        self.addCleanup(node.stop)
        node.protocol.rpc_timeout = .5
        node.protocol.ping_queue._default_delay = .5
        return node

    async def setup_network(self, size: int, start_port=40000, seed_nodes=1, external_ip='127.0.0.1'):
        for i in range(size):
            node_port = start_port + i
            node_id = constants.generate_id(i)
            node = await self.create_node(node_id, node_port)
            self.nodes.append(node)
            self.known_node_addresses.append((external_ip, node_port))

        for node in self.nodes:
            node.start(external_ip, self.known_node_addresses[:seed_nodes])

    async def test_replace_bad_nodes(self):
        await self.setup_network(20)
        await asyncio.gather(*[node.joined.wait() for node in self.nodes])
        self.assertEqual(len(self.nodes), 20)
        node = self.nodes[0]
        bad_peers = []
        for candidate in self.nodes[1:10]:
            address, port, node_id = candidate.protocol.external_ip, candidate.protocol.udp_port, candidate.protocol.node_id
            peer = make_kademlia_peer(node_id, address, udp_port=port)
            bad_peers.append(peer)
            node.protocol.add_peer(peer)
            candidate.stop()
        await asyncio.sleep(.3)  # let pending events settle
        for bad_peer in bad_peers:
            self.assertIn(bad_peer, node.protocol.routing_table.get_peers())
        await node.refresh_node(True)
        await asyncio.sleep(.3)  # let pending events settle
        good_nodes = {good_node.protocol.node_id for good_node in self.nodes[10:]}
        for peer in node.protocol.routing_table.get_peers():
            self.assertIn(peer.node_id, good_nodes)

    async def test_re_join(self):
        await self.setup_network(20, seed_nodes=10)
        await asyncio.gather(*[node.joined.wait() for node in self.nodes])
        node = self.nodes[-1]
        self.assertTrue(node.joined.is_set())
        self.assertTrue(node.protocol.routing_table.get_peers())
        for network_node in self.nodes[:-1]:
            network_node.stop()
        await node.refresh_node(True)
        await asyncio.sleep(.3)  # let pending events settle
        self.assertFalse(node.protocol.routing_table.get_peers())
        for network_node in self.nodes[:-1]:
            network_node.start('127.0.0.1', self.known_node_addresses)
        self.assertFalse(node.protocol.routing_table.get_peers())
        timeout = 20
        while not node.protocol.routing_table.get_peers():
            await asyncio.sleep(.1)
            timeout -= 1
            if not timeout:
                self.fail("node didn't join back after 2 seconds")

    async def test_announce_no_peers(self):
        await self.setup_network(1)
        node = self.nodes[0]
        blob_hash = hexlify(constants.generate_id(1337)).decode()
        peers = await node.announce_blob(blob_hash)
        self.assertEqual(len(peers), 0)

    async def test_get_token_on_announce(self):
        await self.setup_network(2, seed_nodes=2)
        await asyncio.gather(*[node.joined.wait() for node in self.nodes])
        node1, node2 = self.nodes
        node1.protocol.peer_manager.clear_token(node2.protocol.node_id)
        blob_hash = hexlify(constants.generate_id(1337)).decode()
        node_ids = await node1.announce_blob(blob_hash)
        self.assertIn(node2.protocol.node_id, node_ids)
        node2.protocol.node_rpc.refresh_token()
        node_ids = await node1.announce_blob(blob_hash)
        self.assertIn(node2.protocol.node_id, node_ids)
        node2.protocol.node_rpc.refresh_token()
        node_ids = await node1.announce_blob(blob_hash)
        self.assertIn(node2.protocol.node_id, node_ids)

    async def test_peer_search_removes_bad_peers(self):
        # that's an edge case discovered by Tom, but an important one
        # imagine that you only got bad peers and refresh will happen in one hour
        # instead of failing for one hour we should be able to recover by scheduling pings to bad peers we find
        await self.setup_network(2, seed_nodes=2)
        await asyncio.gather(*[node.joined.wait() for node in self.nodes])
        node1, node2 = self.nodes
        node2.stop()
        # forcefully make it a bad peer but don't remove it from routing table
        address, port, node_id = node2.protocol.external_ip, node2.protocol.udp_port, node2.protocol.node_id
        peer = make_kademlia_peer(node_id, address, udp_port=port)
        self.assertTrue(node1.protocol.peer_manager.peer_is_good(peer))
        node1.protocol.peer_manager.report_failure(node2.protocol.external_ip, node2.protocol.udp_port)
        node1.protocol.peer_manager.report_failure(node2.protocol.external_ip, node2.protocol.udp_port)
        self.assertFalse(node1.protocol.peer_manager.peer_is_good(peer))

        # now a search happens, which removes bad peers while contacting them
        self.assertTrue(node1.protocol.routing_table.get_peers())
        await node1.peer_search(node2.protocol.node_id)
        await asyncio.sleep(.3)  # let pending events settle
        self.assertFalse(node1.protocol.routing_table.get_peers())

    async def test_peer_persistance(self):
        num_nodes = 6
        start_port = 40000
        num_seeds = 2
        external_ip = '127.0.0.1'

        # Start a node
        await self.setup_network(num_nodes, start_port=start_port, seed_nodes=num_seeds)
        await asyncio.gather(*[node.joined.wait() for node in self.nodes])

        node1 = self.nodes[-1]
        peer_args = [(n.protocol.node_id, n.protocol.external_ip, n.protocol.udp_port, n.protocol.peer_port) for n in
                     self.nodes[:num_seeds]]
        peers = [make_kademlia_peer(*args) for args in peer_args]

        # node1 is bootstrapped from the fixed seeds
        self.assertCountEqual(peers, node1.protocol.routing_table.get_peers())

        # Refresh and assert that the peers were persisted
        await node1.refresh_node(True)
        self.assertEqual(len(peer_args), len(await node1._storage.get_persisted_kademlia_peers()))
        node1.stop()

        # Start a fresh node with the same node_id and storage, but no known peers
        node2 = await self.create_node(constants.generate_id(num_nodes-1), start_port+num_nodes-1)
        node2._storage = node1._storage
        node2.start(external_ip, [])
        await node2.joined.wait()

        # The peers are restored
        self.assertEqual(num_seeds, len(node2.protocol.routing_table.get_peers()))
        for bucket1, bucket2 in zip(node1.protocol.routing_table.buckets, node2.protocol.routing_table.buckets):
            self.assertEqual((bucket1.range_min, bucket1.range_max), (bucket2.range_min, bucket2.range_max))
