import logging
import asyncio
import typing
import binascii
import contextlib
from lbrynet.utils import resolve_host
from lbrynet.dht import constants
from lbrynet.dht.error import RemoteException
from lbrynet.dht.protocol.async_generator_junction import AsyncGeneratorJunction
from lbrynet.dht.protocol.distance import Distance
from lbrynet.dht.protocol.iterative_find import IterativeNodeFinder, IterativeValueFinder
from lbrynet.dht.protocol.protocol import KademliaProtocol
from lbrynet.dht.peer import KademliaPeer

if typing.TYPE_CHECKING:
    from lbrynet.dht.peer import PeerManager

log = logging.getLogger(__name__)


class Node:
    def __init__(self, loop: asyncio.BaseEventLoop, peer_manager: 'PeerManager', node_id: bytes, udp_port: int,
                 internal_udp_port: int, peer_port: int, external_ip: str, rpc_timeout: float = constants.rpc_timeout,
                 split_buckets_under_index: int = constants.split_buckets_under_index):
        self.loop = loop
        self.internal_udp_port = internal_udp_port
        self.protocol = KademliaProtocol(loop, peer_manager, node_id, external_ip, udp_port, peer_port, rpc_timeout,
                                         split_buckets_under_index)
        self.listening_port: asyncio.DatagramTransport = None
        self.joined = asyncio.Event(loop=self.loop)
        self._join_task: asyncio.Task = None
        self._refresh_task: asyncio.Task = None

    async def refresh_node(self):
        while True:
            # remove peers with expired blob announcements from the datastore
            self.protocol.data_store.removed_expired_peers()

            total_peers: typing.List['KademliaPeer'] = []
            # add all peers in the routing table
            total_peers.extend(self.protocol.routing_table.get_peers())
            # add all the peers who have announed blobs to us
            total_peers.extend(self.protocol.data_store.get_storing_contacts())

            # get ids falling in the midpoint of each bucket that hasn't been recently updated
            node_ids = self.protocol.routing_table.get_refresh_list(0, True)
            # if we have 3 or fewer populated buckets get two random ids in the range of each to try and
            # populate/split the buckets further
            buckets_with_contacts = self.protocol.routing_table.buckets_with_contacts()
            if buckets_with_contacts <= 3:
                for i in range(buckets_with_contacts):
                    node_ids.append(self.protocol.routing_table.random_id_in_bucket_range(i))
                    node_ids.append(self.protocol.routing_table.random_id_in_bucket_range(i))

            if self.protocol.routing_table.get_peers():
                # if we have node ids to look up, perform the iterative search until we have k results
                while node_ids:
                    peers = await self.peer_search(node_ids.pop())
                    total_peers.extend(peers)
            else:
                fut = asyncio.Future(loop=self.loop)
                self.loop.call_later(constants.refresh_interval // 4, fut.set_result, None)
                await fut
                continue

            # ping the set of peers; upon success/failure the routing able and last replied/failed time will be updated
            to_ping = [peer for peer in set(total_peers) if self.protocol.peer_manager.peer_is_good(peer) is not True]
            if to_ping:
                self.protocol.ping_queue.enqueue_maybe_ping(*to_ping, delay=0)

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
            log.debug("Store to %i peers", len(peers))
            for peer in peers:
                log.debug("store to %s %s %s", peer.address, peer.udp_port, peer.tcp_port)
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
                           known_node_urls: typing.Optional[typing.List[typing.Tuple[str, int]]] = None):
        if not self.listening_port:
            await self.start_listening(interface)
        self.protocol.ping_queue.start()
        self._refresh_task = self.loop.create_task(self.refresh_node())

        # resolve the known node urls
        known_node_addresses = []
        url_to_addr = {}

        if known_node_urls:
            for host, port in known_node_urls:
                address = await resolve_host(host, port, proto='udp')
                if (address, port) not in known_node_addresses and address != self.protocol.external_ip:
                    known_node_addresses.append((address, port))
                    url_to_addr[address] = host

        if known_node_addresses:
            while not self.protocol.routing_table.get_peers():
                success = False
                # ping the seed nodes, this will set their node ids (since we don't know them ahead of time)
                for address, port in known_node_addresses:
                    peer = self.protocol.get_rpc_peer(KademliaPeer(self.loop, address, udp_port=port))
                    try:
                        await peer.ping()
                        success = True
                    except asyncio.TimeoutError:
                        log.warning("seed node (%s:%i) timed out in %s", url_to_addr.get(address, address), port,
                                    round(self.protocol.rpc_timeout, 2))
                if success:
                    break
            # now that we have the seed nodes in routing, to an iterative lookup of our own id to populate the buckets
            # in the routing table with good peers who are near us
            async with self.peer_search_junction(self.protocol.node_id, max_results=16) as junction:
                async for peers in junction:
                    for peer in peers:
                        try:
                            await self.protocol.get_rpc_peer(peer).ping()
                        except (asyncio.TimeoutError, RemoteException):
                            pass

        log.info("Joined DHT, %i peers known in %i buckets", len(self.protocol.routing_table.get_peers()),
                 self.protocol.routing_table.buckets_with_contacts())
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

    @contextlib.asynccontextmanager
    async def stream_peer_search_junction(self, hash_queue: asyncio.Queue, bottom_out_limit=20,
                                          max_results=-1) -> AsyncGeneratorJunction:
        peer_generator = AsyncGeneratorJunction(self.loop)

        async def _add_hashes_from_queue():
            while True:
                blob_hash = await hash_queue.get()
                peer_generator.add_generator(
                    self.get_iterative_value_finder(
                        binascii.unhexlify(blob_hash.encode()), bottom_out_limit=bottom_out_limit,
                        max_results=max_results
                    )
                )
        add_hashes_task = self.loop.create_task(_add_hashes_from_queue())
        try:
            async with peer_generator as junction:
                yield junction
        finally:
            if add_hashes_task and not (add_hashes_task.done() or add_hashes_task.cancelled()):
                add_hashes_task.cancel()

    def peer_search_junction(self, node_id: bytes, max_results=constants.k*2,
                             bottom_out_limit=20) -> AsyncGeneratorJunction:
        peer_generator = AsyncGeneratorJunction(self.loop)
        peer_generator.add_generator(
            self.get_iterative_node_finder(
                node_id, bottom_out_limit=bottom_out_limit, max_results=max_results
            )
        )
        return peer_generator

    async def peer_search(self, node_id: bytes, count=constants.k, max_results=constants.k*2,
                          bottom_out_limit=20) -> typing.List['KademliaPeer']:
        accumulated: typing.List['KademliaPeer'] = []
        async with self.peer_search_junction(node_id, max_results=max_results,
                                             bottom_out_limit=bottom_out_limit) as junction:
            async for peers in junction:
                accumulated.extend(peers)
        distance = Distance(node_id)
        accumulated.sort(key=lambda peer: distance(peer.node_id))
        return accumulated[:count]

    async def _accumulate_search_junction(self, search_queue: asyncio.Queue,
                                          result_queue: asyncio.Queue):
        async with self.stream_peer_search_junction(search_queue) as search_junction:  # pylint: disable=E1701
            async for peers in search_junction:
                if peers:
                    result_queue.put_nowait([
                        peer for peer in peers
                        if not (
                                peer.address == self.protocol.external_ip
                                and peer.tcp_port == self.protocol.peer_port
                        )
                    ])

    def accumulate_peers(self, search_queue: asyncio.Queue,
                         peer_queue: typing.Optional[asyncio.Queue] = None) -> typing.Tuple[
                         asyncio.Queue, asyncio.Task]:
        q = peer_queue or asyncio.Queue()
        return q, asyncio.create_task(self._accumulate_search_junction(search_queue, q))
