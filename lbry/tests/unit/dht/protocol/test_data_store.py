import asyncio
from unittest import mock, TestCase
from lbry.dht.protocol.data_store import DictDataStore
from lbry.dht.peer import PeerManager, get_kademlia_peer


class DataStoreTests(TestCase):
    def setUp(self):
        self.loop = mock.Mock(spec=asyncio.BaseEventLoop)
        self.loop.time = lambda: 0.0
        self.peer_manager = PeerManager(self.loop)
        self.data_store = DictDataStore(self.loop, self.peer_manager)

    def _test_add_peer_to_blob(self, blob=b'2' * 48, node_id=b'1' * 48, address='1.2.3.4', tcp_port=3333,
                               udp_port=4444):
        peer = get_kademlia_peer(node_id, address, udp_port)
        peer.update_tcp_port(tcp_port)
        before = self.data_store.get_peers_for_blob(blob)
        self.data_store.add_peer_to_blob(peer, blob)
        self.assertListEqual(before + [peer], self.data_store.get_peers_for_blob(blob))
        return peer

    def test_refresh_peer_to_blob(self):
        blob = b'f' * 48
        self.assertListEqual([], self.data_store.get_peers_for_blob(blob))
        peer = self._test_add_peer_to_blob(blob=blob, node_id=b'a' * 48, address='1.2.3.4')
        self.assertTrue(self.data_store.has_peers_for_blob(blob))
        self.assertEqual(len(self.data_store.get_peers_for_blob(blob)), 1)
        self.assertEqual(self.data_store._data_store[blob][0][1], 0)
        self.loop.time = lambda: 100.0
        self.assertEqual(self.data_store._data_store[blob][0][1], 0)
        self.data_store.add_peer_to_blob(peer, blob)
        self.assertEqual(self.data_store._data_store[blob][0][1], 100)

    def test_add_peer_to_blob(self, blob=b'f' * 48, peers=None):
        peers = peers or [
            (b'a' * 48, '1.2.3.4'),
            (b'b' * 48, '1.2.3.5'),
            (b'c' * 48, '1.2.3.6'),
        ]
        self.assertListEqual([], self.data_store.get_peers_for_blob(blob))
        peer_objects = []
        for (node_id, address) in peers:
            peer_objects.append(self._test_add_peer_to_blob(blob=blob, node_id=node_id, address=address))
            self.assertTrue(self.data_store.has_peers_for_blob(blob))
        self.assertEqual(len(self.data_store.get_peers_for_blob(blob)), len(peers))
        return peer_objects

    def test_get_storing_contacts(self, peers=None, blob1=b'd' * 48, blob2=b'e' * 48):
        peers = peers or [
            (b'a' * 48, '1.2.3.4'),
            (b'b' * 48, '1.2.3.5'),
            (b'c' * 48, '1.2.3.6'),
        ]
        peer_objs1 = self.test_add_peer_to_blob(blob=blob1, peers=peers)
        self.assertEqual(len(peers), len(peer_objs1))
        self.assertEqual(len(peers), len(self.data_store.get_storing_contacts()))

        peer_objs2 = self.test_add_peer_to_blob(blob=blob2, peers=peers)
        self.assertEqual(len(peers), len(peer_objs2))
        self.assertEqual(len(peers), len(self.data_store.get_storing_contacts()))

        for o1, o2 in zip(peer_objs1, peer_objs2):
            self.assertIs(o1, o2)

    def test_remove_expired_peers(self):
        peers = [
            (b'a' * 48, '1.2.3.4'),
            (b'b' * 48, '1.2.3.5'),
            (b'c' * 48, '1.2.3.6'),
        ]
        blob1 = b'd' * 48
        blob2 = b'e' * 48

        self.data_store.removed_expired_peers()  # nothing should happen
        self.test_get_storing_contacts(peers, blob1, blob2)
        self.assertEqual(len(self.data_store.get_peers_for_blob(blob1)), len(peers))
        self.assertEqual(len(self.data_store.get_peers_for_blob(blob2)), len(peers))
        self.assertEqual(len(self.data_store.get_storing_contacts()), len(peers))

        # expire the first peer from blob1
        first = self.data_store._data_store[blob1][0][0]
        self.data_store._data_store[blob1][0] = (first, -86401)
        self.assertEqual(len(self.data_store.get_storing_contacts()), len(peers))
        self.data_store.removed_expired_peers()
        self.assertEqual(len(self.data_store.get_peers_for_blob(blob1)), len(peers) - 1)
        self.assertEqual(len(self.data_store.get_peers_for_blob(blob2)), len(peers))
        self.assertEqual(len(self.data_store.get_storing_contacts()), len(peers))

        # expire the first peer from blob2
        first = self.data_store._data_store[blob2][0][0]
        self.data_store._data_store[blob2][0] = (first, -86401)
        self.data_store.removed_expired_peers()
        self.assertEqual(len(self.data_store.get_peers_for_blob(blob1)), len(peers) - 1)
        self.assertEqual(len(self.data_store.get_peers_for_blob(blob2)), len(peers) - 1)
        self.assertEqual(len(self.data_store.get_storing_contacts()), len(peers) - 1)

        # expire the second and third peers from blob1
        first = self.data_store._data_store[blob2][0][0]
        self.data_store._data_store[blob1][0] = (first, -86401)
        second = self.data_store._data_store[blob2][1][0]
        self.data_store._data_store[blob1][1] = (second, -86401)
        self.data_store.removed_expired_peers()
        self.assertEqual(len(self.data_store.get_peers_for_blob(blob1)), 0)
        self.assertEqual(len(self.data_store.get_peers_for_blob(blob2)), len(peers) - 1)
        self.assertEqual(len(self.data_store.get_storing_contacts()), len(peers) - 1)
