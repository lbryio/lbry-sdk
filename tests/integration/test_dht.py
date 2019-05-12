import asyncio

from lbrynet.dht import constants
from lbrynet.dht.node import Node
from lbrynet.dht.peer import PeerManager, KademliaPeer
from torba.testcase import AsyncioTestCase


class CLIIntegrationTest(AsyncioTestCase):

    async def asyncSetUp(self):
        import logging
        logging.getLogger('asyncio').setLevel(logging.ERROR)
        logging.getLogger('lbrynet.dht').setLevel(logging.DEBUG)
        self.nodes = []
        self.known_node_addresses = []

    async def setup_network(self, size: int, start_port=40000):
        for i in range(size):
            node_port = start_port + i
            node = Node(self.loop, PeerManager(self.loop), node_id=constants.generate_id(i),
                                   udp_port=node_port, internal_udp_port=node_port,
                                   peer_port=3333, external_ip='127.0.0.1')
            self.nodes.append(node)
            self.known_node_addresses.append(('127.0.0.1', node_port))
            await node.start_listening('127.0.0.1')
        for node in self.nodes:
            node.protocol.rpc_timeout = .2
            node.protocol.ping_queue._default_delay = .5
            node.start('127.0.0.1', self.known_node_addresses[:1])
        await asyncio.gather(*[node.joined.wait() for node in self.nodes])

    async def asyncTearDown(self):
        for node in self.nodes:
            node.stop()

    async def test_replace_bad_nodes(self):
        await self.setup_network(20)
        self.assertEquals(len(self.nodes), 20)
        node = self.nodes[0]
        bad_peers = []
        for candidate in self.nodes[1:10]:
            address, port, node_id = candidate.protocol.external_ip, candidate.protocol.udp_port, candidate.protocol.node_id
            peer = KademliaPeer(self.loop, address, node_id, port)
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


