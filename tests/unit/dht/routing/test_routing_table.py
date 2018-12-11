import asyncio
from torba.testcase import AsyncioTestCase
from tests import dht_mocks
from lbrynet.dht import constants
from lbrynet.dht.node import Node
from lbrynet.peer import PeerManager


class TestRouting(AsyncioTestCase):
    async def test_fill_one_bucket(self):
        loop = asyncio.get_event_loop()
        peer_addresses = [
            (constants.generate_id(1), '1.2.3.1'),
            (constants.generate_id(2), '1.2.3.2'),
            (constants.generate_id(3), '1.2.3.3'),
            (constants.generate_id(4), '1.2.3.4'),
            (constants.generate_id(5), '1.2.3.5'),
            (constants.generate_id(6), '1.2.3.6'),
            (constants.generate_id(7), '1.2.3.7'),
            (constants.generate_id(8), '1.2.3.8'),
            (constants.generate_id(9), '1.2.3.9'),
        ]
        with dht_mocks.mock_network_loop(loop):
            nodes = {
                i: Node(PeerManager(loop), loop, node_id, 4444, 4444, 3333, address)
                for i, (node_id, address) in enumerate(peer_addresses)
            }
            for i, p in nodes.items():
                await p.start_listening()
            node_1 = nodes[0]
            contact_cnt = 0
            for i in range(1, len(peer_addresses)):
                self.assertEqual(len(node_1.protocol.routing_table.get_contacts()), contact_cnt)
                node = nodes[i]
                peer = node_1.protocol.peer_manager.make_peer(
                    node.protocol.external_ip, dht_protocol=node_1.protocol, node_id=node.protocol.node_id,
                    udp_port=node.protocol.udp_port
                )
                added = await node_1.protocol.routing_table.add_contact(peer)
                self.assertEqual(True, added)
                contact_cnt += 1
            self.assertEqual(len(node_1.protocol.routing_table.get_contacts()), 8)
            self.assertEqual(node_1.protocol.routing_table.buckets_with_contacts(), 1)

            for p in nodes.values():
                p.protocol.transport.close()
