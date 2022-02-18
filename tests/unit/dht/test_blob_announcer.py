import contextlib
import logging
import typing
import binascii
import socket
import asyncio

from lbry.testcase import AsyncioTestCase
from tests import dht_mocks
from lbry.dht.protocol.distance import Distance
from lbry.conf import Config
from lbry.dht import constants
from lbry.dht.node import Node
from lbry.dht.peer import PeerManager, make_kademlia_peer
from lbry.dht.blob_announcer import BlobAnnouncer
from lbry.extras.daemon.storage import SQLiteStorage


class TestBlobAnnouncer(AsyncioTestCase):
    TIMEOUT = 20.0  # lower than default

    async def setup_node(self, peer_addresses, address, node_id):
        self.nodes: typing.Dict[int, Node] = {}
        self.advance = dht_mocks.get_time_accelerator(self.loop)
        self.instant_advance = dht_mocks.get_time_accelerator(self.loop)
        self.conf = Config()
        self.peer_manager = PeerManager(self.loop)
        self.node = Node(self.loop, self.peer_manager, node_id, 4444, 4444, 3333, address)
        await self.node.start_listening(address)
        await asyncio.gather(*[self.add_peer(node_id, address) for node_id, address in peer_addresses])
        for first_peer in self.nodes.values():
            for second_peer in self.nodes.values():
                if first_peer == second_peer:
                    continue
                self.add_peer_to_routing_table(first_peer, second_peer)
                self.add_peer_to_routing_table(second_peer, first_peer)
        await self.advance(0.1)  # just to make pings go through
        self.node.joined.set()
        self.node._refresh_task = self.loop.create_task(self.node.refresh_node())
        self.storage = SQLiteStorage(self.conf, ":memory:", self.loop, self.loop.time)
        await self.storage.open()
        self.blob_announcer = BlobAnnouncer(self.loop, self.node, self.storage)

    async def add_peer(self, node_id, address, add_to_routing_table=True):
        #print('add', node_id.hex()[:8], address)
        n = Node(self.loop, PeerManager(self.loop), node_id, 4444, 4444, 3333, address)
        await n.start_listening(address)
        self.nodes.update({len(self.nodes): n})
        if add_to_routing_table:
            self.add_peer_to_routing_table(self.node, n)

    def add_peer_to_routing_table(self, adder, being_added):
        adder.protocol.add_peer(
            make_kademlia_peer(
                being_added.protocol.node_id, being_added.protocol.external_ip, being_added.protocol.udp_port
            )
        )

    @contextlib.asynccontextmanager
    async def _test_network_context(self, peer_count=200):
        self.peer_addresses = [
            (constants.generate_id(i), socket.inet_ntoa(int(i + 0x01000001).to_bytes(length=4, byteorder='big')))
            for i in range(1, peer_count + 1)
        ]
        try:
            with dht_mocks.mock_network_loop(self.loop):
                await self.setup_node(self.peer_addresses, '1.2.3.1', constants.generate_id(1000))
                yield
        finally:
            self.blob_announcer.stop()
            self.node.stop()
            for n in self.nodes.values():
                n.stop()

    async def chain_peer(self, node_id, address):
        previous_last_node = self.nodes[len(self.nodes) - 1]
        await self.add_peer(node_id, address, False)
        last_node = self.nodes[len(self.nodes) - 1]
        peer = last_node.protocol.get_rpc_peer(
            make_kademlia_peer(
                previous_last_node.protocol.node_id, previous_last_node.protocol.external_ip,
                previous_last_node.protocol.udp_port
            )
        )
        await peer.ping()
        return last_node

    async def test_announce_blobs(self):
        blob1 = binascii.hexlify(b'1' * 48).decode()
        blob2 = binascii.hexlify(b'2' * 48).decode()

        async with self._test_network_context(peer_count=100):
            await self.storage.add_blobs((blob1, 1024, 0, True), (blob2, 1024, 0, True), finished=True)
            await self.storage.add_blobs(
                *((constants.generate_id(value).hex(), 1024, 0, True) for value in range(1000, 1090)),
                finished=True)
            await self.storage.db.execute("update blob set next_announce_time=0, should_announce=1")
            to_announce = await self.storage.get_blobs_to_announce()
            self.assertEqual(92, len(to_announce))
            self.blob_announcer.start(batch_size=10)  # so it covers batching logic
            # takes 60 seconds to start, but we advance 120 to ensure it processed all batches
            ongoing_announcements = asyncio.ensure_future(self.blob_announcer.wait())
            await self.instant_advance(60.0)
            await ongoing_announcements
            to_announce = await self.storage.get_blobs_to_announce()
            self.assertEqual(0, len(to_announce))
            self.blob_announcer.stop()

            # as routing table pollution will cause some peers to be hard to reach, we add a tolerance for CI
            tolerance = 0.8  # at least 80% of the announcements are within the top K
            for blob in await self.storage.get_all_blob_hashes():
                distance = Distance(bytes.fromhex(blob))
                candidates = list(self.nodes.values())
                candidates.sort(key=lambda sorting_node: distance(sorting_node.protocol.node_id))
                has_it = 0
                for index, node in enumerate(candidates[:constants.K], start=1):
                    if node.protocol.data_store.get_peers_for_blob(bytes.fromhex(blob)):
                        has_it += 1
                    else:
                        logging.warning("blob %s wasnt found between the best K (%s)", blob[:8], node.protocol.node_id.hex()[:8])
                self.assertGreaterEqual(has_it, int(tolerance * constants.K))


            # test that we can route from a poorly connected peer all the way to the announced blob

            current = len(self.nodes)
            await self.chain_peer(constants.generate_id(current + 1), '1.2.3.10')
            await self.chain_peer(constants.generate_id(current + 2), '1.2.3.11')
            await self.chain_peer(constants.generate_id(current + 3), '1.2.3.12')
            await self.chain_peer(constants.generate_id(current + 4), '1.2.3.13')
            last = await self.chain_peer(constants.generate_id(current + 5), '1.2.3.14')

            search_q, peer_q = asyncio.Queue(loop=self.loop), asyncio.Queue(loop=self.loop)
            search_q.put_nowait(blob1)

            _, task = last.accumulate_peers(search_q, peer_q)
            found_peers = await asyncio.wait_for(peer_q.get(), 1.0)
            task.cancel()

            self.assertEqual(1, len(found_peers))
            self.assertEqual(self.node.protocol.node_id, found_peers[0].node_id)
            self.assertEqual(self.node.protocol.external_ip, found_peers[0].address)
            self.assertEqual(self.node.protocol.peer_port, found_peers[0].tcp_port)

    async def test_popular_blob(self):
        peer_count = 150
        blob_hash = constants.generate_id(99999)

        async with self._test_network_context(peer_count=peer_count):
            total_seen = set()
            announced_to = self.nodes.pop(0)
            for i, node in enumerate(self.nodes.values()):
                self.add_peer_to_routing_table(announced_to, node)
                peer = node.protocol.get_rpc_peer(
                    make_kademlia_peer(
                        announced_to.protocol.node_id,
                        announced_to.protocol.external_ip,
                        announced_to.protocol.udp_port
                    )
                )
                response = await peer.store(blob_hash)
                self.assertEqual(response, b'OK')
                peers_for_blob = await peer.find_value(blob_hash, 0)
                if i == 0:
                    self.assertNotIn(blob_hash, peers_for_blob)
                    self.assertEqual(peers_for_blob[b'p'], 0)
                else:
                    self.assertEqual(len(peers_for_blob[blob_hash]), min(i, constants.K))
                    self.assertEqual(len(announced_to.protocol.data_store.get_peers_for_blob(blob_hash)), i + 1)
                if i - 1 > constants.K:
                    self.assertEqual(len(peers_for_blob[b'contacts']), constants.K)
                    self.assertEqual(peers_for_blob[b'p'], (i // (constants.K + 1)) + 1)
                    seen = set(peers_for_blob[blob_hash])
                    self.assertEqual(len(seen), constants.K)
                    self.assertEqual(len(peers_for_blob[blob_hash]), len(seen))

                    for pg in range(1, peers_for_blob[b'p']):
                        page_x = await peer.find_value(blob_hash, pg)
                        self.assertNotIn(b'contacts', page_x)
                        page_x_set = set(page_x[blob_hash])
                        self.assertEqual(len(page_x[blob_hash]), len(page_x_set))
                        self.assertGreater(len(page_x_set), 0)
                        self.assertSetEqual(seen.intersection(page_x_set), set())
                        seen.intersection_update(page_x_set)
                        total_seen.update(page_x_set)
                else:
                    self.assertEqual(len(peers_for_blob[b'contacts']), 8)  # we always add 8 on first page
            self.assertEqual(len(total_seen), peer_count - 2)
