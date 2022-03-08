import random
import struct
import asyncio
import logging
from collections import namedtuple

from lbry.utils import resolve_host, async_timed_cache
from lbry.wallet.stream import StreamController

log = logging.getLogger(__name__)
CONNECTION_EXPIRES_AFTER_SECONDS = 360
# see: http://bittorrent.org/beps/bep_0015.html and http://xbtt.sourceforge.net/udp_tracker_protocol.html
ConnectRequest = namedtuple("ConnectRequest", ["connection_id", "action", "transaction_id"])
ConnectResponse = namedtuple("ConnectResponse", ["action", "transaction_id", "connection_id"])
AnnounceRequest = namedtuple("AnnounceRequest",
                             ["connection_id", "action", "transaction_id", "info_hash", "peer_id", "downloaded", "left",
                              "uploaded", "event", "ip_addr", "key", "num_want", "port"])
AnnounceResponse = namedtuple("AnnounceResponse",
                              ["action", "transaction_id", "interval", "leechers", "seeders", "peers"])
CompactIPv4Peer = namedtuple("CompactPeer", ["address", "port"])
ScrapeRequest = namedtuple("ScrapeRequest", ["connection_id", "action", "transaction_id", "infohashes"])
ScrapeResponse = namedtuple("ScrapeResponse", ["action", "transaction_id", "items"])
ScrapeResponseItem = namedtuple("ScrapeResponseItem", ["seeders", "completed", "leechers"])
ErrorResponse = namedtuple("ErrorResponse", ["action", "transaction_id", "message"])
STRUCTS = {
    ConnectRequest: struct.Struct(">QII"),
    ConnectResponse: struct.Struct(">IIQ"),
    AnnounceRequest: struct.Struct(">QII20s20sQQQIIIiH"),
    AnnounceResponse: struct.Struct(">IIIII"),
    CompactIPv4Peer: struct.Struct(">IH"),
    ScrapeRequest: struct.Struct(">QII"),
    ScrapeResponse: struct.Struct(">II"),
    ScrapeResponseItem: struct.Struct(">III"),
    ErrorResponse: struct.Struct(">II")
}


def decode(cls, data, offset=0):
    decoder = STRUCTS[cls]
    if cls == AnnounceResponse:
        return AnnounceResponse(*decoder.unpack_from(data, offset),
                                peers=[decode(CompactIPv4Peer, data, index) for index in range(20, len(data), 6)])
    elif cls == ScrapeResponse:
        return ScrapeResponse(*decoder.unpack_from(data, offset),
                              items=[decode(ScrapeResponseItem, data, index) for index in range(8, len(data), 12)])
    elif cls == ErrorResponse:
        return ErrorResponse(*decoder.unpack_from(data, offset), data[decoder.size:])
    return cls(*decoder.unpack_from(data, offset))


def encode(obj):
    if isinstance(obj, ScrapeRequest):
        return STRUCTS[ScrapeRequest].pack(*obj[:-1]) + b''.join(obj.infohashes)
    elif isinstance(obj, ErrorResponse):
        return STRUCTS[ErrorResponse].pack(*obj[:-1]) + obj.message
    elif isinstance(obj, AnnounceResponse):
        return STRUCTS[AnnounceResponse].pack(*obj[:-1]) + b''.join([encode(peer) for peer in obj.peers])
    return STRUCTS[type(obj)].pack(*obj)


class UDPTrackerClientProtocol(asyncio.DatagramProtocol):
    def __init__(self, timeout = 30.0):
        self.transport = None
        self.data_queue = {}
        self.timeout = timeout

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    async def request(self, obj, tracker_ip, tracker_port):
        self.data_queue[obj.transaction_id] = asyncio.get_running_loop().create_future()
        self.transport.sendto(encode(obj), (tracker_ip, tracker_port))
        try:
            return await asyncio.wait_for(self.data_queue[obj.transaction_id], self.timeout)
        finally:
            self.data_queue.pop(obj.transaction_id, None)

    async def connect(self, tracker_ip, tracker_port):
        transaction_id = random.getrandbits(32)
        return decode(ConnectResponse,
                      await self.request(ConnectRequest(0x41727101980, 0, transaction_id), tracker_ip, tracker_port))

    @async_timed_cache(CONNECTION_EXPIRES_AFTER_SECONDS)
    async def ensure_connection_id(self, peer_id, tracker_ip, tracker_port):
        # peer_id is just to ensure cache coherency
        return (await self.connect(tracker_ip, tracker_port)).connection_id

    async def announce(self, info_hash, peer_id, port, tracker_ip, tracker_port, stopped=False):
        connection_id = await self.ensure_connection_id(peer_id, tracker_ip, tracker_port)
        # this should make the key deterministic but unique per info hash + peer id
        key = int.from_bytes(info_hash[:4], "big") ^ int.from_bytes(peer_id[:4], "big") ^ port
        transaction_id = random.getrandbits(32)
        req = AnnounceRequest(
            connection_id, 1, transaction_id, info_hash, peer_id, 0, 0, 0, 3 if stopped else 1, 0, key, -1, port)
        return decode(AnnounceResponse, await self.request(req, tracker_ip, tracker_port))

    async def scrape(self, infohashes, tracker_ip, tracker_port, connection_id=None):
        if not connection_id:
            reply = await self.connect(tracker_ip, tracker_port)
            connection_id = reply.connection_id
        transaction_id = random.getrandbits(32)
        reply = await self.request(
            ScrapeRequest(connection_id, 2, transaction_id, infohashes), tracker_ip, tracker_port)
        return decode(ScrapeResponse, reply), connection_id

    def datagram_received(self, data: bytes, addr: (str, int)) -> None:
        if len(data) < 8:
            return
        transaction_id = int.from_bytes(data[4:8], byteorder="big", signed=False)
        if transaction_id in self.data_queue:
            if not self.data_queue[transaction_id].done():
                if data[3] == 3:
                    return self.data_queue[transaction_id].set_exception(Exception(decode(ErrorResponse, data).message))
                return self.data_queue[transaction_id].set_result(data)
        log.debug("unexpected packet (can be a response for a previously timed out request): %s", data.hex())

    def connection_lost(self, exc: Exception = None) -> None:
        self.transport = None


class TrackerClient:
    EVENT_CONTROLLER = StreamController()
    def __init__(self, node_id, announce_port, servers):
        self.client = UDPTrackerClientProtocol()
        self.transport = None
        self.node_id = node_id or random.getrandbits(160).to_bytes(20, "big", signed=False)
        self.announce_port = announce_port
        self.servers = servers

    async def start(self):
        self.transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: self.client, local_addr=("0.0.0.0", 0))
        self.EVENT_CONTROLLER.stream.listen(lambda request: self.on_hash(request[1]) if request[0] == 'search' else None)

    def stop(self):
        if self.transport is not None:
            self.transport.close()
        self.client = None
        self.transport = None
        self.EVENT_CONTROLLER.close()

    def on_hash(self, info_hash):
        asyncio.ensure_future(self.get_peer_list(info_hash))

    async def get_peer_list(self, info_hash, stopped=False):
        found = []
        for done in asyncio.as_completed([self._probe_server(info_hash, *server, stopped) for server in self.servers]):
            found.extend(await done)
        return found

    async def _probe_server(self, info_hash, tracker_host, tracker_port, stopped=False):
        try:
            tracker_ip = await resolve_host(tracker_host, tracker_port, 'udp')
            result = await self.client.announce(
                info_hash, self.node_id, self.announce_port, tracker_ip, tracker_port, stopped)
        except asyncio.TimeoutError:
            log.info("Tracker timed out: %s:%d", tracker_host, tracker_port)
            return []
        log.info("Announced to tracker. Found %d peers for %s on %s",
                 len(result.peers), info_hash.hex()[:8], tracker_host)
        self.EVENT_CONTROLLER.add((info_hash, result))
        return result


def subscribe_hash(hash, on_data):
    TrackerClient.EVENT_CONTROLLER.add(('search', bytes.fromhex(hash)))
    TrackerClient.EVENT_CONTROLLER.stream.listen(
        lambda request: on_data(request[1]) if request[0].hex() == hash else None)
