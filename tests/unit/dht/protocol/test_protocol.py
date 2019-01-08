import asyncio
from torba.testcase import AsyncioTestCase
from tests import dht_mocks
from lbrynet.dht import constants
from lbrynet.dht.protocol.protocol import KademliaProtocol
from lbrynet.peer import PeerManager


class TestProtocol(AsyncioTestCase):
    async def test_ping(self):
        loop = asyncio.get_event_loop()
        with dht_mocks.mock_network_loop(loop):
            node_id1 = constants.generate_id()
            peer1 = KademliaProtocol(
                PeerManager(loop), loop, node_id1, '1.2.3.4', 4444, 3333
            )
            peer2 = KademliaProtocol(
                PeerManager(loop), loop, constants.generate_id(), '1.2.3.5', 4444, 3333
            )
            await loop.create_datagram_endpoint(lambda: peer1, ('1.2.3.4', 4444))
            await loop.create_datagram_endpoint(lambda: peer2, ('1.2.3.5', 4444))

            peer = peer2.peer_manager.make_peer('1.2.3.4', node_id=node_id1, udp_port=4444)
            result = await peer.ping()
            self.assertEqual(result, b'pong')
            peer1.stop()
            peer2.stop()
            peer1.disconnect()
            peer2.disconnect()

    async def test_update_token(self):
        loop = asyncio.get_event_loop()
        with dht_mocks.mock_network_loop(loop):
            node_id1 = constants.generate_id()
            peer1 = KademliaProtocol(
                PeerManager(loop), loop, node_id1, '1.2.3.4', 4444, 3333
            )
            peer2 = KademliaProtocol(
                PeerManager(loop), loop, constants.generate_id(), '1.2.3.5', 4444, 3333
            )
            await loop.create_datagram_endpoint(lambda: peer1, ('1.2.3.4', 4444))
            await loop.create_datagram_endpoint(lambda: peer2, ('1.2.3.5', 4444))

            peer = peer2.peer_manager.make_peer('1.2.3.4', node_id=node_id1, udp_port=4444)
            self.assertEqual(None, peer.token)
            await peer.find_value(b'1' * 48)
            self.assertNotEqual(None, peer.token)
            peer1.stop()
            peer2.stop()
            peer1.disconnect()
            peer2.disconnect()

    async def test_store_to_peer(self):
        loop = asyncio.get_event_loop()
        with dht_mocks.mock_network_loop(loop):
            node_id1 = constants.generate_id()
            peer1 = KademliaProtocol(
                PeerManager(loop), loop, node_id1, '1.2.3.4', 4444, 3333
            )
            peer2 = KademliaProtocol(
                PeerManager(loop), loop, constants.generate_id(), '1.2.3.5', 4444, 3333
            )
            await loop.create_datagram_endpoint(lambda: peer1, ('1.2.3.4', 4444))
            await loop.create_datagram_endpoint(lambda: peer2, ('1.2.3.5', 4444))

            peer = peer2.peer_manager.make_peer('1.2.3.4', node_id=node_id1, udp_port=4444)
            peer2_from_peer1 = peer1.peer_manager.make_peer(
                peer2.external_ip, node_id=peer2.node_id, udp_port=peer2.udp_port, tcp_port=peer2.peer_port
            )
            peer3 = peer1.peer_manager.make_peer(
                '1.2.3.6', node_id=constants.generate_id(), udp_port=4444
            )

            store_result = await peer2.store_to_peer(b'2' * 48, peer)
            self.assertEqual(store_result[0], peer.node_id)
            self.assertEqual(True, store_result[1])
            self.assertEqual(True, peer1.data_store.has_peers_for_blob(b'2' * 48))
            self.assertEqual(False, peer1.data_store.has_peers_for_blob(b'3' * 48))
            self.assertListEqual([peer2_from_peer1], peer1.data_store.get_storing_contacts())

            find_value_response = peer1.node_rpc.find_value(peer3, b'2' * 48)
            self.assertSetEqual(
                {b'2' * 48, b'token', b'protocolVersion'}, set(find_value_response.keys())
            )
            self.assertEqual(1, len(find_value_response[b'2' * 48]))
            self.assertEqual(find_value_response[b'2' * 48][0], peer2_from_peer1.compact_address_tcp())

            peer1.stop()
            peer2.stop()
            peer1.disconnect()
            peer2.disconnect()
