import logging
import asyncio
import typing
import socket
import binascii

from lbrynet.dht.protocol.protocol import KademliaProtocol
from lbrynet.dht.iterative_find import IterativeNodeFinder, IterativeValueFinder
from lbrynet.dht import constants
if typing.TYPE_CHECKING:
    from lbrynet.peer import PeerManager

log = logging.getLogger(__name__)


class Node:
    def __init__(self, peer_manager: 'PeerManager', loop: asyncio.BaseEventLoop, node_id: bytes, udp_port: int,
                 internal_udp_port: int, peer_port: int, external_ip: str):
        self.loop = loop
        self.internal_udp_port = internal_udp_port
        self.protocol = KademliaProtocol(peer_manager, loop, node_id, external_ip, udp_port, peer_port)
        self.listening_port: asyncio.DatagramTransport = None
        self._join_task: asyncio.Task = None
        self.joined = asyncio.Event(loop=self.loop)
        self._refresh_task: asyncio.Task = None

    async def refresh_node(self):
        """ Periodically called to perform k-bucket refreshes and data
        replication/republishing as necessary """
        while True:
            self.protocol.data_store.removed_expired_peers()
            await self.protocol.ping_queue.enqueue_maybe_ping(*self.protocol.routing_table.get_peers(), delay=0)
            await self.protocol.ping_queue.enqueue_maybe_ping(*self.protocol.data_store.get_storing_contacts(),
                                                              delay=0)
            node_ids = self.protocol.routing_table.get_refresh_list(0, True)
            buckets_with_contacts = self.protocol.routing_table.buckets_with_contacts()
            if buckets_with_contacts <= 3:
                for i in range(buckets_with_contacts):
                    node_ids.append(self.protocol.routing_table.random_id_in_bucket_range(i))
                    node_ids.append(self.protocol.routing_table.random_id_in_bucket_range(i))
            while node_ids:
                await self.cumulative_find_node(node_ids.pop())

            fut = asyncio.Future(loop=self.loop)
            self.loop.call_later(constants.refresh_interval, fut.set_result, None)
            await fut

    async def announce_blob(self, blob_hash: str) -> typing.List[bytes]:
        announced_to_node_ids = []
        while not announced_to_node_ids:
            hash_value = binascii.unhexlify(blob_hash.encode())
            assert len(hash_value) == constants.hash_length
            peers = await self.cumulative_find_node(hash_value)

            if not self.protocol.external_ip:
                raise Exception("Cannot determine external IP")
            log.info("Store to %i peers", len(peers))
            log.info(peers)
            for peer in peers:
                log.info("store to %s %s %s", peer.address, peer.udp_port, peer.tcp_port)
            stored_to_tup = await asyncio.gather(
                *(self.protocol.store_to_peer(hash_value, peer) for peer in peers), loop=self.loop
            )
            announced_to_node_ids.extend([node_id for node_id, contacted in stored_to_tup if contacted])
            log.info("Stored %s to %i of %i attempted peers", binascii.hexlify(hash_value).decode()[:8],
                      len(announced_to_node_ids), len(peers))
        return announced_to_node_ids

    def stop(self) -> None:
        if self.joined.is_set():
            self.joined.clear()
        if self._join_task:
            self._join_task.cancel()
        if self._refresh_task and not (self._refresh_task.done() or self._refresh_task.cancelled()):
            self._refresh_task.cancel()
        if self.protocol and self.protocol.ping_queue.running:
            self.protocol.ping_queue.stop()
        if self.listening_port is not None:
            self.listening_port.close()
        self._join_task = None
        self.listening_port = None
        log.info("Stopped DHT node")

    async def start_listening(self, interface: str = '') -> None:
        if not self.listening_port:
            self.listening_port, _ = await self.loop.create_datagram_endpoint(
                lambda: self.protocol, (interface, self.internal_udp_port)
            )
            log.info("DHT node listening on UDP %s:%i", interface, self.internal_udp_port)
        else:
            log.warning("Already bound to port %s", self.listening_port)

    async def join_network(self, interface: typing.Optional[str] = '',
                           known_node_urls: typing.Optional[typing.List[typing.Tuple[str, int]]] = None,
                           known_node_addresses: typing.Optional[typing.List[typing.Tuple[str, int]]] = None):
        if not self.listening_port:
            await self.start_listening(interface)
        self.protocol.ping_queue.start()
        self._refresh_task = self.loop.create_task(self.refresh_node())

        known_node_addresses = known_node_addresses or []
        if known_node_urls:
            for host, port in known_node_urls:
                info = await self.loop.getaddrinfo(
                    host, 'https',
                    proto=socket.IPPROTO_TCP,
                )
                if (info[0][4][0], port) not in known_node_addresses:
                    known_node_addresses.append((info[0][4][0], port))
        futs = []
        for address, port in known_node_addresses:
            peer = self.protocol.peer_manager.make_peer(address, udp_port=port)
            futs.append(peer.ping())
        await asyncio.gather(*futs, loop=self.loop)
        closest = await self.cumulative_find_node(self.protocol.node_id, max_results=16)
        log.info("ping %i closest", len(closest))
        futs = []

        async def ping(p: 'Peer'):
            try:
                await p.ping()
            except:
                pass

        for peer in closest:
            futs.append(ping(peer))
        await asyncio.gather(*futs, loop=self.loop)
        self.joined.set()

    def start(self, interface: str, known_node_urls: typing.List[typing.Tuple[str, int]]):
        self._join_task = self.loop.create_task(
            self.join_network(
                interface=interface, known_node_urls=known_node_urls
            )
        )

    def get_iterative_node_finder(self, key: bytes, shortlist: typing.Optional[typing.List] = None,
                                  bottom_out_limit: int = constants.bottom_out_limit,
                                  max_results: int = constants.k) -> IterativeNodeFinder:

        return IterativeNodeFinder(self.loop, self.protocol.peer_manager, self.protocol.routing_table, self.protocol,
                                   key, bottom_out_limit, max_results, None, shortlist)

    def get_iterative_value_finder(self, key: bytes, shortlist: typing.Optional[typing.List] = None,
                                   bottom_out_limit: int = 40,
                                   max_results: int = -1) -> IterativeValueFinder:

        return IterativeValueFinder(self.loop, self.protocol.peer_manager, self.protocol.routing_table, self.protocol,
                                    key, bottom_out_limit, max_results, None, shortlist)

    async def cumulative_find_node(self, node_id: bytes, shortlist: typing.Optional[typing.List] = None,
                                   bottom_out_limit: int = constants.bottom_out_limit,
                                   max_results: int = constants.k * 2) -> typing.List['Peer']:
        finder = self.get_iterative_node_finder(node_id, shortlist, bottom_out_limit, max_results)
        try:
            accumulated = []
            async for peers in finder:
                log.info("got %i peers", len(peers))
                for peer in peers:
                    if peer not in accumulated:
                        accumulated.append(peer)
            return accumulated
        finally:
            if finder.running:
                await finder.aclose()
