import asyncio
from torba.testcase import AsyncioTestCase
from tests import dht_mocks
from lbrynet.dht import constants
from lbrynet.dht.protocol.protocol import KademliaProtocol
from lbrynet.peer import PeerManager


class TestRefreshPingQueue(AsyncioTestCase):
    async def test_ping_queue(self):
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
            advance = dht_mocks.get_time_accelerator(loop, loop.time())
            # start the nodes
            nodes = {
                i: KademliaProtocol(PeerManager(loop), loop, node_id, address, 4444, 3333)
                for i, (node_id, address) in enumerate(peer_addresses)
            }
            for i, p in nodes.items():
                await loop.create_datagram_endpoint(lambda: p, (peer_addresses[i][1], 4444))
            await advance(1)

            node_1 = nodes[0]

            # ping 8 nodes from node_1, this will result in a delayed return ping
            futs = []
            for i in range(1, len(peer_addresses)):
                node = nodes[i]
                assert node.node_id != node_1.node_id
                peer = node_1.peer_manager.make_peer(node.external_ip, dht_protocol=node_1, node_id=node.node_id,
                                                     udp_port=node.udp_port)
                futs.append(peer.ping())
            await advance(3)
            await asyncio.gather(*tuple(futs))

            # run long enough for the ping queue
            await advance(360)

            # verify all of the previously pinged peers have node_1 in their routing tables
            for p in nodes.values():
                if p is node_1:
                    continue
                contacts = p.routing_table.get_contacts()
                self.assertEqual(len(contacts), 1)
                self.assertEqual((contacts[0].node_id, contacts[0].address, contacts[0].udp_port),
                                 (node_1.node_id, node_1.external_ip, node_1.udp_port))

            # run long enough for the refresh loop to run twice
            await advance(7200)

            # verify all the nodes know about each other
            for p in nodes.values():
                if p is node_1:
                    continue
                contacts = p.routing_table.get_contacts()
                self.assertSetEqual(
                    {n_id[0] for n_id in peer_addresses if n_id[0] != p.node_id},
                    {c.node_id for c in contacts}
                )
                self.assertSetEqual(
                    {n_addr[1] for n_addr in peer_addresses if n_addr[1] != p.external_ip},
                    {c.address for c in contacts}
                )
                self.assertEqual(8, len(contacts))

            # teardown
            for p in nodes.values():
                p.transport.close()
                p.ping_queue.stop()

    # async def test_discover_via_refresh_loop(self):
    #     loop = asyncio.get_event_loop()
    #
    #     peer_addresses = [
    #         (constants.generate_id(i), '1.2.3.%i' % i) for i in range(1, 255)
    #     ]
    #     with dht_mocks.mock_network_loop(loop):
    #         advance = dht_mocks.get_time_accelerator(loop, loop.time())
    #         # start the nodes
    #         nodes = {
    #             i: KademliaProtocol(PeerManager(loop), loop, node_id, address, 4444, 3333)
    #             for i, (node_id, address) in enumerate(peer_addresses)
    #         }
    #         futs = []
    #         for i, p in nodes.items():
    #             futs.append(p.listen(peer_addresses[i][1]))
    #         await advance(1)
    #         await asyncio.gather(*tuple(futs))
    #
    #         node_1 = nodes[0]
    #
    #         # ping node_1 from all other nodes
    #         futs = []
    #         for i in range(1, len(peer_addresses)):
    #             node = nodes[i]
    #             assert node.node_id != node_1.node_id
    #             peer = node.peer_manager.make_peer(node_1.node_id, node_1.external_ip, node, node_1.udp_port)
    #             futs.append(peer.ping())
    #         await advance(3)
    #         await asyncio.gather(*tuple(futs))
    #
    #         await advance(3600 * 3)
    #
    #         routable_peers = set([x[0] for x in peer_addresses])
    #         in_routing = set()
    #         for n in nodes.values():
    #             for peer in n.routing_table.get_contacts():
    #                 if peer.node_id not in in_routing:
    #                     in_routing.add(peer.node_id)
    #         self.assertSetEqual(in_routing, routable_peers)
    #
    #         # teardown
    #         for p in nodes.values():
    #             p.transport.close()
    #             p.ping_queue.stop()
