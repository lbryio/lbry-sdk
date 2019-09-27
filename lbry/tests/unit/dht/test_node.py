import asyncio
import typing
from torba.testcase import AsyncioTestCase
from tests import dht_mocks
from lbry.dht import constants
from lbry.dht.node import Node
from lbry.dht.peer import PeerManager, get_kademlia_peer


class TestNodePingQueueDiscover(AsyncioTestCase):
    async def test_ping_queue_discover(self):
        loop = asyncio.get_event_loop()
        loop.set_debug(False)

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
            advance = dht_mocks.get_time_accelerator(loop, loop.time())
            # start the nodes
            nodes: typing.Dict[int, Node] = {
                i: Node(loop, PeerManager(loop), node_id, 4444, 4444, 3333, address)
                for i, (node_id, address) in enumerate(peer_addresses)
            }
            for i, n in nodes.items():
                n.start(peer_addresses[i][1], [])

            await advance(1)

            node_1 = nodes[0]

            # ping 8 nodes from node_1, this will result in a delayed return ping
            futs = []
            for i in range(1, len(peer_addresses)):
                node = nodes[i]
                assert node.protocol.node_id != node_1.protocol.node_id
                peer = get_kademlia_peer(
                    node.protocol.node_id, node.protocol.external_ip, udp_port=node.protocol.udp_port
                )
                futs.append(node_1.protocol.get_rpc_peer(peer).ping())
            await advance(3)
            replies = await asyncio.gather(*tuple(futs))
            self.assertTrue(all(map(lambda reply: reply == b"pong", replies)))

            # run for long enough for the delayed pings to have been sent by node 1
            await advance(1000)

            # verify all of the previously pinged peers have node_1 in their routing tables
            for n in nodes.values():
                peers = n.protocol.routing_table.get_peers()
                if n is node_1:
                    self.assertEqual(8, len(peers))
                else:
                    self.assertEqual(1, len(peers))
                    self.assertEqual((peers[0].node_id, peers[0].address, peers[0].udp_port),
                                     (node_1.protocol.node_id, node_1.protocol.external_ip, node_1.protocol.udp_port))

            # run long enough for the refresh loop to run
            await advance(3600)

            # verify all the nodes know about each other
            for n in nodes.values():
                if n is node_1:
                    continue
                peers = n.protocol.routing_table.get_peers()
                self.assertEqual(8, len(peers))
                self.assertSetEqual(
                    {n_id[0] for n_id in peer_addresses if n_id[0] != n.protocol.node_id},
                    {c.node_id for c in peers}
                )
                self.assertSetEqual(
                    {n_addr[1] for n_addr in peer_addresses if n_addr[1] != n.protocol.external_ip},
                    {c.address for c in peers}
                )

            # teardown
            for n in nodes.values():
                n.stop()
