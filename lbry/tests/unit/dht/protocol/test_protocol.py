import asyncio
import binascii
from torba.testcase import AsyncioTestCase
from tests import dht_mocks
from lbry.dht.serialization.bencoding import bencode, bdecode
from lbry.dht import constants
from lbry.dht.protocol.protocol import KademliaProtocol
from lbry.dht.peer import PeerManager, make_kademlia_peer


class TestProtocol(AsyncioTestCase):
    async def test_ping(self):
        loop = asyncio.get_event_loop()
        with dht_mocks.mock_network_loop(loop):
            node_id1 = constants.generate_id()
            peer1 = KademliaProtocol(
                loop, PeerManager(loop), node_id1, '1.2.3.4', 4444, 3333
            )
            peer2 = KademliaProtocol(
                loop, PeerManager(loop), constants.generate_id(), '1.2.3.5', 4444, 3333
            )
            await loop.create_datagram_endpoint(lambda: peer1, ('1.2.3.4', 4444))
            await loop.create_datagram_endpoint(lambda: peer2, ('1.2.3.5', 4444))

            peer = make_kademlia_peer(node_id1, '1.2.3.4', udp_port=4444)
            result = await peer2.get_rpc_peer(peer).ping()
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
                loop, PeerManager(loop), node_id1, '1.2.3.4', 4444, 3333
            )
            peer2 = KademliaProtocol(
                loop, PeerManager(loop), constants.generate_id(), '1.2.3.5', 4444, 3333
            )
            await loop.create_datagram_endpoint(lambda: peer1, ('1.2.3.4', 4444))
            await loop.create_datagram_endpoint(lambda: peer2, ('1.2.3.5', 4444))

            peer = make_kademlia_peer(node_id1, '1.2.3.4', udp_port=4444)
            self.assertEqual(None, peer2.peer_manager.get_node_token(peer.node_id))
            await peer2.get_rpc_peer(peer).find_value(b'1' * 48)
            self.assertNotEqual(None, peer2.peer_manager.get_node_token(peer.node_id))
            peer1.stop()
            peer2.stop()
            peer1.disconnect()
            peer2.disconnect()

    async def test_store_to_peer(self):
        loop = asyncio.get_event_loop()
        with dht_mocks.mock_network_loop(loop):
            node_id1 = constants.generate_id()
            peer1 = KademliaProtocol(
                loop, PeerManager(loop), node_id1, '1.2.3.4', 4444, 3333
            )
            peer2 = KademliaProtocol(
                loop, PeerManager(loop), constants.generate_id(), '1.2.3.5', 4444, 3333
            )
            await loop.create_datagram_endpoint(lambda: peer1, ('1.2.3.4', 4444))
            await loop.create_datagram_endpoint(lambda: peer2, ('1.2.3.5', 4444))

            peer = make_kademlia_peer(node_id1, '1.2.3.4', udp_port=4444)
            peer2_from_peer1 = make_kademlia_peer(
                peer2.node_id, peer2.external_ip, udp_port=peer2.udp_port
            )
            peer2_from_peer1.update_tcp_port(3333)
            peer3 = make_kademlia_peer(
                constants.generate_id(), '1.2.3.6', udp_port=4444
            )
            store_result = await peer2.store_to_peer(b'2' * 48, peer)
            self.assertEqual(store_result[0], peer.node_id)
            self.assertEqual(True, store_result[1])
            self.assertEqual(True, peer1.data_store.has_peers_for_blob(b'2' * 48))
            self.assertEqual(False, peer1.data_store.has_peers_for_blob(b'3' * 48))
            self.assertListEqual([peer2_from_peer1], peer1.data_store.get_storing_contacts())
            peer1.data_store.completed_blobs.add(binascii.hexlify(b'2' * 48).decode())
            find_value_response = peer1.node_rpc.find_value(peer3, b'2' * 48)
            self.assertEqual(len(find_value_response[b'contacts']), 0)
            self.assertSetEqual(
                {b'2' * 48, b'token', b'protocolVersion', b'contacts', b'p'}, set(find_value_response.keys())
            )
            self.assertEqual(2, len(find_value_response[b'2' * 48]))
            self.assertEqual(find_value_response[b'2' * 48][0], peer2_from_peer1.compact_address_tcp())
            self.assertDictEqual(bdecode(bencode(find_value_response)), find_value_response)

            find_value_page_above_pages_response = peer1.node_rpc.find_value(peer3, b'2' * 48, page=10)
            self.assertNotIn(b'2' * 48, find_value_page_above_pages_response)

            peer1.stop()
            peer2.stop()
            peer1.disconnect()
            peer2.disconnect()

    async def _make_protocol(self, other_peer, node_id, address, udp_port, tcp_port):
        proto = KademliaProtocol(
            self.loop, PeerManager(self.loop), node_id, address, udp_port, tcp_port
        )
        await self.loop.create_datagram_endpoint(lambda: proto, (address, 4444))
        proto.start()
        return proto, make_kademlia_peer(node_id, address, udp_port=udp_port)

    async def test_add_peer_after_handle_request(self):
        with dht_mocks.mock_network_loop(self.loop):
            node_id1 = constants.generate_id()
            node_id2 = constants.generate_id()
            node_id3 = constants.generate_id()
            node_id4 = constants.generate_id()

            peer1 = KademliaProtocol(
                self.loop, PeerManager(self.loop), node_id1, '1.2.3.4', 4444, 3333
            )
            await self.loop.create_datagram_endpoint(lambda: peer1, ('1.2.3.4', 4444))
            peer1.start()

            peer2, peer_2_from_peer_1 = await self._make_protocol(peer1, node_id2, '1.2.3.5', 4444, 3333)
            peer3, peer_3_from_peer_1 = await self._make_protocol(peer1, node_id3, '1.2.3.6', 4444, 3333)
            peer4, peer_4_from_peer_1 = await self._make_protocol(peer1, node_id4, '1.2.3.7', 4444, 3333)

            # peers who reply should be added
            await peer1.get_rpc_peer(peer_2_from_peer_1).ping()
            await asyncio.sleep(0.5)
            self.assertListEqual([peer_2_from_peer_1], peer1.routing_table.get_peers())
            peer1.routing_table.remove_peer(peer_2_from_peer_1)

            # peers not known by be good/bad should be enqueued to maybe-ping
            peer1_from_peer3 = peer3.get_rpc_peer(make_kademlia_peer(node_id1, '1.2.3.4', 4444))
            self.assertEqual(0, len(peer1.ping_queue._pending_contacts))
            pong = await peer1_from_peer3.ping()
            self.assertEqual(b'pong', pong)
            self.assertEqual(1, len(peer1.ping_queue._pending_contacts))
            peer1.ping_queue._pending_contacts.clear()

            # peers who are already good should be added
            peer1_from_peer4 = peer4.get_rpc_peer(make_kademlia_peer(node_id1, '1.2.3.4', 4444))
            peer1.peer_manager.update_contact_triple(node_id4,'1.2.3.7', 4444)
            peer1.peer_manager.report_last_replied('1.2.3.7', 4444)
            self.assertEqual(0, len(peer1.ping_queue._pending_contacts))
            pong = await peer1_from_peer4.ping()
            self.assertEqual(b'pong', pong)
            await asyncio.sleep(0.5)
            self.assertEqual(1, len(peer1.routing_table.get_peers()))
            self.assertEqual(0, len(peer1.ping_queue._pending_contacts))
            peer1.routing_table.buckets[0].peers.clear()

            # peers who are known to be bad recently should not be added or maybe-pinged
            peer1_from_peer4 = peer4.get_rpc_peer(make_kademlia_peer(node_id1, '1.2.3.4', 4444))
            peer1.peer_manager.update_contact_triple(node_id4,'1.2.3.7', 4444)
            peer1.peer_manager.report_failure('1.2.3.7', 4444)
            peer1.peer_manager.report_failure('1.2.3.7', 4444)
            self.assertEqual(0, len(peer1.ping_queue._pending_contacts))
            pong = await peer1_from_peer4.ping()
            self.assertEqual(b'pong', pong)
            self.assertEqual(0, len(peer1.routing_table.get_peers()))
            self.assertEqual(0, len(peer1.ping_queue._pending_contacts))

            for p in [peer1, peer2, peer3, peer4]:
                p.stop()
                p.disconnect()
