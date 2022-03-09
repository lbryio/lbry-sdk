import asyncio
import random
from functools import reduce

from lbry.testcase import AsyncioTestCase
from lbry.torrent.tracker import encode, decode, CompactIPv4Peer, ConnectRequest, \
    ConnectResponse, AnnounceRequest, ErrorResponse, AnnounceResponse, TrackerClient, subscribe_hash


class UDPTrackerServerProtocol(asyncio.DatagramProtocol):  # for testing. Not suitable for production
    def __init__(self):
        self.transport = None
        self.known_conns = set()
        self.peers = {}

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    def add_peer(self, info_hash, ip_address: str, port: int):
        self.peers.setdefault(info_hash, [])
        self.peers[info_hash].append(encode_peer(ip_address, port))

    def datagram_received(self, data: bytes, address: (str, int)) -> None:
        if len(data) < 16:
            return
        action = int.from_bytes(data[8:12], "big", signed=False)
        if action == 0:
            req = decode(ConnectRequest, data)
            connection_id = random.getrandbits(32)
            self.known_conns.add(connection_id)
            return self.transport.sendto(encode(ConnectResponse(0, req.transaction_id, connection_id)), address)
        elif action == 1:
            req = decode(AnnounceRequest, data)
            if req.connection_id not in self.known_conns:
                resp = encode(ErrorResponse(3, req.transaction_id, b'Connection ID missmatch.\x00'))
            else:
                compact_address = encode_peer(address[0], req.port)
                if req.event != 3:
                    self.add_peer(req.info_hash, address[0], req.port)
                elif compact_address in self.peers.get(req.info_hash, []):
                    self.peers[req.info_hash].remove(compact_address)
                peers = [decode(CompactIPv4Peer, peer) for peer in self.peers[req.info_hash]]
                resp = encode(AnnounceResponse(1, req.transaction_id, 1700, 0, len(peers), peers))
            return self.transport.sendto(resp, address)


def encode_peer(ip_address: str, port: int):
    compact_ip = reduce(lambda buff, x: buff + bytearray([int(x)]), ip_address.split('.'), bytearray())
    return compact_ip + port.to_bytes(2, "big", signed=False)


class UDPTrackerClientTestCase(AsyncioTestCase):
    async def asyncSetUp(self):
        self.servers = {}
        self.client = TrackerClient(b"\x00" * 48, 4444, [], timeout=0.1)
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
            self.client.servers.append(("127.0.0.1", port))

    async def test_announce(self):
        info_hash = random.getrandbits(160).to_bytes(20, "big", signed=False)
        announcement = (await self.client.get_peer_list(info_hash))[0]
        self.assertEqual(announcement.seeders, 1)
        self.assertEqual(announcement.peers,
                         [CompactIPv4Peer(int.from_bytes(bytes([127, 0, 0, 1]), "big", signed=False), 4444)])

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

    async def test_multiple(self):
        await asyncio.gather(*[self.add_server() for _ in range(10)])
        info_hash = random.getrandbits(160).to_bytes(20, "big", signed=False)
        await self.client.get_peer_list(info_hash)
        for server in self.servers.values():
            self.assertEqual(server.peers, {info_hash: [encode_peer("127.0.0.1", self.client.announce_port)]})

    async def test_multiple_with_bad_one(self):
        await asyncio.gather(*[self.add_server() for _ in range(10)])
        self.client.servers.append(("127.0.0.2", 7070))
        info_hash = random.getrandbits(160).to_bytes(20, "big", signed=False)
        await self.client.get_peer_list(info_hash)
        for server in self.servers.values():
            self.assertEqual(server.peers, {info_hash: [encode_peer("127.0.0.1", self.client.announce_port)]})

    async def test_multiple_with_different_peers_across_helper_function(self):
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
