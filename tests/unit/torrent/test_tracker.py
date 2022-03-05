import random
from lbry.testcase import AsyncioTestCase
from lbry.torrent.tracker import UDPTrackerClientProtocol, UDPTrackerServerProtocol, CompactIPv4Peer


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

    async def test_error(self):
        info_hash = random.getrandbits(160).to_bytes(20, "big", signed=False)
        peer_id = random.getrandbits(160).to_bytes(20, "big", signed=False)
        with self.assertRaises(Exception) as err:
            announcement, _ = await self.client.announce(info_hash, peer_id, 4444, "127.0.0.1", 59900, connection_id=10)
        self.assertEqual(err.exception.args[0], b'Connection ID missmatch.\x00')
