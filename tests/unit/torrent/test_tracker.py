import asyncio
import random

from lbry.testcase import AsyncioTestCase
from lbry.torrent.tracker import CompactIPv4Peer, TrackerClient, subscribe_hash, UDPTrackerServerProtocol, encode_peer


class UDPTrackerClientTestCase(AsyncioTestCase):
    async def asyncSetUp(self):
        self.client_servers_list = []
        self.servers = {}
        self.client = TrackerClient(b"\x00" * 48, 4444, lambda: self.client_servers_list, timeout=1)
        await self.client.start()
        self.addCleanup(self.client.stop)
        await self.add_server()

    async def add_server(self, port=None, add_to_client=True):
        port = port or len(self.servers) + 59990
        assert port not in self.servers
        server = UDPTrackerServerProtocol()
        self.servers[port] = server
        transport, _ = await self.loop.create_datagram_endpoint(lambda: server, local_addr=("127.0.0.1", port))
        self.addCleanup(transport.close)
        if add_to_client:
            self.client_servers_list.append(("127.0.0.1", port))

    async def test_announce(self):
        info_hash = random.getrandbits(160).to_bytes(20, "big", signed=False)
        announcement = (await self.client.get_peer_list(info_hash))[0]
        self.assertEqual(announcement.seeders, 1)
        self.assertEqual(announcement.peers,
                         [CompactIPv4Peer(int.from_bytes(bytes([127, 0, 0, 1]), "big", signed=False), 4444)])

    async def test_announce_many_info_hashes_to_many_servers_with_bad_one_and_dns_error(self):
        await asyncio.gather(*[self.add_server() for _ in range(3)])
        self.client_servers_list.append(("no.it.does.not.exist", 7070))
        self.client_servers_list.append(("127.0.0.2", 7070))
        info_hashes = [random.getrandbits(160).to_bytes(20, "big", signed=False) for _ in range(5)]
        await self.client.announce_many(*info_hashes)
        for server in self.servers.values():
            self.assertDictEqual(
                server.peers, {
                    info_hash: [encode_peer("127.0.0.1", self.client.announce_port)] for info_hash in info_hashes
            })

    async def test_announce_using_helper_function(self):
        info_hash = random.getrandbits(160).to_bytes(20, "big", signed=False)
        queue = asyncio.Queue()
        subscribe_hash(info_hash, queue.put)
        announcement = await queue.get()
        peers = announcement.peers
        self.assertEqual(peers, [CompactIPv4Peer(int.from_bytes(bytes([127, 0, 0, 1]), "big", signed=False), 4444)])

    async def test_error(self):
        info_hash = random.getrandbits(160).to_bytes(20, "big", signed=False)
        await self.client.get_peer_list(info_hash)
        list(self.servers.values())[0].known_conns.clear()
        self.client.results.clear()
        with self.assertRaises(Exception) as err:
            await self.client.get_peer_list(info_hash)
        self.assertEqual(err.exception.args[0], b'Connection ID missmatch.\x00')

    async def test_multiple_servers(self):
        await asyncio.gather(*[self.add_server() for _ in range(10)])
        info_hash = random.getrandbits(160).to_bytes(20, "big", signed=False)
        await self.client.get_peer_list(info_hash)
        for server in self.servers.values():
            self.assertEqual(server.peers, {info_hash: [encode_peer("127.0.0.1", self.client.announce_port)]})

    async def test_multiple_servers_with_bad_one(self):
        await asyncio.gather(*[self.add_server() for _ in range(10)])
        self.client_servers_list.append(("127.0.0.2", 7070))
        info_hash = random.getrandbits(160).to_bytes(20, "big", signed=False)
        await self.client.get_peer_list(info_hash)
        for server in self.servers.values():
            self.assertEqual(server.peers, {info_hash: [encode_peer("127.0.0.1", self.client.announce_port)]})

    async def test_multiple_servers_with_different_peers_across_helper_function(self):
        # this is how the downloader uses it
        await asyncio.gather(*[self.add_server() for _ in range(10)])
        info_hash = random.getrandbits(160).to_bytes(20, "big", signed=False)
        fake_peers = []
        for server in self.servers.values():
            for _ in range(10):
                peer = (f"127.0.0.{random.randint(1, 255)}", random.randint(2000, 65500))
                fake_peers.append(peer)
                server.add_peer(info_hash, *peer)
        response = []
        subscribe_hash(info_hash, response.append)
        await asyncio.sleep(0)
        await asyncio.gather(*self.client.tasks.values())
        self.assertEqual(11, len(response))
