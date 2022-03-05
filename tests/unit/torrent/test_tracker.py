import asyncio
import random
from functools import reduce

from lbry.testcase import AsyncioTestCase
from lbry.torrent.tracker import UDPTrackerClientProtocol, encode, decode, CompactIPv4Peer, ConnectRequest, \
    ConnectResponse, AnnounceRequest, ErrorResponse, AnnounceResponse, get_peer_list


class UDPTrackerServerProtocol(asyncio.DatagramProtocol):  # for testing. Not suitable for production
    def __init__(self):
        self.transport = None
        self.known_conns = set()
        self.peers = {}

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

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
                self.peers.setdefault(req.info_hash, [])
                compact_ip = reduce(lambda buff, x: buff + bytearray([int(x)]), address[0].split('.'), bytearray())
                self.peers[req.info_hash].append(compact_ip + req.port.to_bytes(2, "big", signed=False))
                peers = [decode(CompactIPv4Peer, peer) for peer in self.peers[req.info_hash]]
                resp = encode(AnnounceResponse(1, req.transaction_id, 1700, 0, len(peers), peers))
            return self.transport.sendto(resp, address)


class UDPTrackerClientTestCase(AsyncioTestCase):
    async def asyncSetUp(self):
        transport, _ = await self.loop.create_datagram_endpoint(UDPTrackerServerProtocol, local_addr=("127.0.0.1", 59900))
        self.addCleanup(transport.close)
        self.client = UDPTrackerClientProtocol()
        transport, _ = await self.loop.create_datagram_endpoint(lambda: self.client, local_addr=("127.0.0.1", 0))
        self.addCleanup(transport.close)

    async def test_announce(self):
        info_hash = random.getrandbits(160).to_bytes(20, "big", signed=False)
        peer_id = random.getrandbits(160).to_bytes(20, "big", signed=False)
        announcement, _ = await self.client.announce(info_hash, peer_id, 4444, "127.0.0.1", 59900)
        self.assertEqual(announcement.seeders, 1)
        self.assertEqual(announcement.peers,
                         [CompactIPv4Peer(int.from_bytes(bytes([127, 0, 0, 1]), "big", signed=False), 4444)])

    async def test_announce_using_helper_function(self):
        info_hash = random.getrandbits(160).to_bytes(20, "big", signed=False)
        peers = await get_peer_list(info_hash, None, 4444, "127.0.0.1", 59900)
        self.assertEqual(len(peers), 1)
        self.assertEqual(peers, [CompactIPv4Peer(int.from_bytes(bytes([127, 0, 0, 1]), "big", signed=False), 4444)])

    async def test_error(self):
        info_hash = random.getrandbits(160).to_bytes(20, "big", signed=False)
        peer_id = random.getrandbits(160).to_bytes(20, "big", signed=False)
        with self.assertRaises(Exception) as err:
            announcement, _ = await self.client.announce(info_hash, peer_id, 4444, "127.0.0.1", 59900, connection_id=10)
        self.assertEqual(err.exception.args[0], b'Connection ID missmatch.\x00')
