import contextlib
import typing
import binascii
import asyncio
from torba.testcase import AsyncioTestCase
from tests import dht_mocks
from lbrynet.conf import Config
from lbrynet.dht import constants
from lbrynet.dht.node import Node
from lbrynet.dht.peer import PeerManager
from lbrynet.dht.blob_announcer import BlobAnnouncer
from lbrynet.extras.daemon.storage import SQLiteStorage


class TestBlobAnnouncer(AsyncioTestCase):
    async def setup_node(self, peer_addresses, address, node_id):
        self.nodes: typing.Dict[int, Node] = {}
        self.advance = dht_mocks.get_time_accelerator(self.loop, self.loop.time())
        self.conf = Config()
        self.storage = SQLiteStorage(self.conf, ":memory:", self.loop, self.loop.time)
        await self.storage.open()
        self.peer_manager = PeerManager(self.loop)
        self.node = Node(self.loop, self.peer_manager, node_id, 4444, 4444, 3333, address)
        await self.node.start_listening(address)
        self.blob_announcer = BlobAnnouncer(self.loop, self.node, self.storage)
        for node_id, address in peer_addresses:
            await self.add_peer(node_id, address)
        self.node.joined.set()

    async def add_peer(self, node_id, address, add_to_routing_table=True):
        n = Node(self.loop, PeerManager(self.loop), node_id, 4444, 4444, 3333, address)
        await n.start_listening(address)
        self.nodes.update({len(self.nodes): n})
        if add_to_routing_table:
            self.node.protocol.add_peer(
                self.peer_manager.get_kademlia_peer(
                    n.protocol.node_id, n.protocol.external_ip, n.protocol.udp_port
                )
            )

    @contextlib.asynccontextmanager
    async def _test_network_context(self, peer_addresses=None):
        self.peer_addresses = peer_addresses or [
            (constants.generate_id(2), '1.2.3.2'),
            (constants.generate_id(3), '1.2.3.3'),
            (constants.generate_id(4), '1.2.3.4'),
            (constants.generate_id(5), '1.2.3.5'),
            (constants.generate_id(6), '1.2.3.6'),
            (constants.generate_id(7), '1.2.3.7'),
            (constants.generate_id(8), '1.2.3.8'),
            (constants.generate_id(9), '1.2.3.9'),
        ]
        try:
            with dht_mocks.mock_network_loop(self.loop):
                await self.setup_node(self.peer_addresses, '1.2.3.1', constants.generate_id(1))
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
            last_node.protocol.peer_manager.get_kademlia_peer(
                previous_last_node.protocol.node_id, previous_last_node.protocol.external_ip,
                previous_last_node.protocol.udp_port
            )
        )
        await peer.ping()
        return peer

    async def test_announce_blobs(self):
        blob1 = binascii.hexlify(b'1' * 48).decode()
        blob2 = binascii.hexlify(b'2' * 48).decode()

        async with self._test_network_context():
            await self.storage.add_blobs((blob1, 1024), (blob2, 1024), finished=True)
            await self.storage.db.execute(
                "update blob set next_announce_time=0, should_announce=1 where blob_hash in (?, ?)",
                (blob1, blob2)
            )
            to_announce = await self.storage.get_blobs_to_announce()
            self.assertEqual(2, len(to_announce))
            self.blob_announcer.start(batch_size=1)  # so it covers batching logic
            await self.advance(61.0)
            to_announce = await self.storage.get_blobs_to_announce()
            self.assertEqual(0, len(to_announce))
            self.blob_announcer.stop()

            # test that we can route from a poorly connected peer all the way to the announced blob

            await self.chain_peer(constants.generate_id(10), '1.2.3.10')
            await self.chain_peer(constants.generate_id(11), '1.2.3.11')
            await self.chain_peer(constants.generate_id(12), '1.2.3.12')
            await self.chain_peer(constants.generate_id(13), '1.2.3.13')
            await self.chain_peer(constants.generate_id(14), '1.2.3.14')
            await self.advance(61.0)

            last = self.nodes[len(self.nodes) - 1]
            search_q, peer_q = asyncio.Queue(loop=self.loop), asyncio.Queue(loop=self.loop)
            search_q.put_nowait(blob1)

            _, task = last.accumulate_peers(search_q, peer_q)
            found_peers = await peer_q.get()
            task.cancel()

            self.assertEqual(1, len(found_peers))
            self.assertEqual(self.node.protocol.node_id, found_peers[0].node_id)
            self.assertEqual(self.node.protocol.external_ip, found_peers[0].address)
            self.assertEqual(self.node.protocol.peer_port, found_peers[0].tcp_port)
