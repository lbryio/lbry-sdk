import logging
import asyncio
import typing
import socket
import binascii

from lbrynet.dht.protocol.protocol import KademliaProtocol
from lbrynet.dht.iterative_find import IterativeNodeFinder, IterativeValueFinder
from lbrynet.dht.async_generator_junction import AsyncGeneratorJunction
from lbrynet.dht import constants
from lbrynet.dht.error import RemoteException
from lbrynet.dht.routing.distance import Distance

if typing.TYPE_CHECKING:
    from lbrynet.peer import PeerManager, Peer

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

            total_peers: typing.List['Peer'] = []
            total_peers.extend(self.protocol.routing_table.get_peers())
            total_peers.extend(self.protocol.data_store.get_storing_contacts())

            node_ids = self.protocol.routing_table.get_refresh_list(0, True)
            buckets_with_contacts = self.protocol.routing_table.buckets_with_contacts()
            if buckets_with_contacts <= 3:
                for i in range(buckets_with_contacts):
                    node_ids.append(self.protocol.routing_table.random_id_in_bucket_range(i))
                    node_ids.append(self.protocol.routing_table.random_id_in_bucket_range(i))
            while node_ids:
                peers = await self.peer_search(node_ids.pop())
                total_peers.extend(peers)

            to_ping = [peer for peer in set(total_peers) if peer.contact_is_good is not True]
            if to_ping:
                log.info("ping %i peers during refresh", len(to_ping))
                await self.protocol.ping_queue.enqueue_maybe_ping(*to_ping, delay=0)

            fut = asyncio.Future(loop=self.loop)
            self.loop.call_later(constants.refresh_interval, fut.set_result, None)
            await fut

    async def announce_blob(self, blob_hash: str) -> typing.List[bytes]:
        announced_to_node_ids = []
        while not announced_to_node_ids:
            hash_value = binascii.unhexlify(blob_hash.encode())
            assert len(hash_value) == constants.hash_length
            peers = await self.peer_search(hash_value)

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
        await asyncio.wait(futs, loop=self.loop)

        async with self.peer_search_junction(self.protocol.node_id, max_results=16) as junction:
            async for peers in junction:
                for peer in peers:
                    try:
                        await peer.ping()
                    except (asyncio.TimeoutError, RemoteException):
                        pass
        self.joined.set()
        log.info("Joined DHT, %i peers known in %i buckets", len(self.protocol.routing_table.get_peers()),
                 self.protocol.routing_table.buckets_with_contacts())

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

    def stream_peer_search_junction(self, hash_queue: asyncio.Queue, bottom_out_limit=20,
                                    max_results=-1) -> AsyncGeneratorJunction:
        peer_generator = AsyncGeneratorJunction(self.loop)

        async def _add_hashes_from_queue():
            while True:
                try:
                    blob_hash = await hash_queue.get()
                except asyncio.CancelledError:
                    break
                peer_generator.add_generator(
                    self.get_iterative_value_finder(
                        binascii.unhexlify(blob_hash.encode()), bottom_out_limit=bottom_out_limit,
                        max_results=max_results
                    )
                )

        add_blobs_task = self.loop.create_task(_add_hashes_from_queue())
        peer_generator.add_cleanup(
            lambda: None if not add_blobs_task or not (add_blobs_task.done() or add_blobs_task.cancelled()) else
            add_blobs_task.cancel()
        )
        return peer_generator

    def peer_search_junction(self, node_id: bytes, max_results=constants.k*2, bottom_out_limit=20) -> AsyncGeneratorJunction:
        peer_generator = AsyncGeneratorJunction(self.loop)
        peer_generator.add_generator(
            self.get_iterative_node_finder(
                node_id, bottom_out_limit=bottom_out_limit, max_results=max_results
            )
        )
        return peer_generator

    async def peer_search(self, node_id: bytes, count=constants.k, max_results=constants.k*2,
                    bottom_out_limit=20) -> typing.List['Peer']:
        accumulated: typing.List['Peer'] = []
        async with self.peer_search_junction(self.protocol.node_id, max_results=max_results,
                                             bottom_out_limit=bottom_out_limit) as junction:
            async for peers in junction:
                log.info("peer search: %s", peers)
                accumulated.extend(peers)
            log.info("junction done")
        log.info("context done")
        distance = Distance(node_id)
        accumulated.sort(key=distance.to_contact)
        return accumulated[:count]
