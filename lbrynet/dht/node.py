import logging
import asyncio
import typing
import binascii
from lbrynet.utils import resolve_host
from lbrynet.dht import constants
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

    async def refresh_node(self, force_once=False):
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
                if force_once:
                    break
                fut = asyncio.Future(loop=self.loop)
                self.loop.call_later(constants.refresh_interval // 4, fut.set_result, None)
                await fut
                continue

            # ping the set of peers; upon success/failure the routing able and last replied/failed time will be updated
            to_ping = [peer for peer in set(total_peers) if self.protocol.peer_manager.peer_is_good(peer) is not True]
            if to_ping:
                self.protocol.ping_queue.enqueue_maybe_ping(*to_ping, delay=0)
            if force_once:
                break

            fut = asyncio.Future(loop=self.loop)
            self.loop.call_later(constants.refresh_interval, fut.set_result, None)
            await fut

    async def announce_blob(self, blob_hash: str) -> typing.List[bytes]:
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
        stored_to = [node_id for node_id, contacted in stored_to_tup if contacted]
        if stored_to:
            log.info("Stored %s to %i of %i attempted peers", binascii.hexlify(hash_value).decode()[:8],
                     len(stored_to), len(peers))
        else:
            log.warning("Failed announcing %s, stored to 0 peers", blob_hash[:8])
        return stored_to

    def stop(self) -> None:
        if self.joined.is_set():
            self.joined.clear()
        if self._join_task:
            self._join_task.cancel()
        if self._refresh_task and not (self._refresh_task.done() or self._refresh_task.cancelled()):
            self._refresh_task.cancel()
        if self.protocol and self.protocol.ping_queue.running:
            self.protocol.ping_queue.stop()
            self.protocol.stop()
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
            self.protocol.start()
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
                if (address, port) not in known_node_addresses and\
                        (address, port) != (self.protocol.external_ip, self.protocol.udp_port):
                    known_node_addresses.append((address, port))
                    url_to_addr[address] = host

        if known_node_addresses:
            peers = [
                KademliaPeer(self.loop, address, udp_port=port)
                for (address, port) in known_node_addresses
            ]
            while True:
                if not self.protocol.routing_table.get_peers():
                    if self.joined.is_set():
                        self.joined.clear()
                    self.protocol.peer_manager.reset()
                    self.protocol.ping_queue.enqueue_maybe_ping(*peers, delay=0.0)
                    peers.extend(await self.peer_search(self.protocol.node_id, shortlist=peers, count=32))
                    if self.protocol.routing_table.get_peers():
                        self.joined.set()
                        log.info(
                            "Joined DHT, %i peers known in %i buckets", len(self.protocol.routing_table.get_peers()),
                            self.protocol.routing_table.buckets_with_contacts())
                    else:
                        continue
                await asyncio.sleep(1, loop=self.loop)

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

    async def peer_search(self, node_id: bytes, count=constants.k, max_results=constants.k*2,
                          bottom_out_limit=20, shortlist: typing.Optional[typing.List] = None
                          ) -> typing.List['KademliaPeer']:
        peers = []
        async for iteration_peers in self.get_iterative_node_finder(
                node_id, shortlist=shortlist, bottom_out_limit=bottom_out_limit, max_results=max_results):
            peers.extend(iteration_peers)
        distance = Distance(node_id)
        peers.sort(key=lambda peer: distance(peer.node_id))
        return peers[:count]

    async def _accumulate_search_junction(self, search_queue: asyncio.Queue,
                                          result_queue: asyncio.Queue):
        tasks = []
        try:
            while True:
                blob_hash = await search_queue.get()
                tasks.append(asyncio.create_task(self._value_producer(blob_hash, result_queue)))
        finally:
            for task in tasks:
                task.cancel()

    async def _value_producer(self, blob_hash: str, result_queue: asyncio.Queue):
        for interval in range(1000):
            log.info("Searching %s", blob_hash[:8])
            async for results in self.get_iterative_value_finder(binascii.unhexlify(blob_hash.encode())):
                result_queue.put_nowait(results)
            log.info("Search expired %s", blob_hash[:8])
            await asyncio.sleep(interval ** 2)

    def accumulate_peers(self, search_queue: asyncio.Queue,
                         peer_queue: typing.Optional[asyncio.Queue] = None) -> typing.Tuple[
                         asyncio.Queue, asyncio.Task]:
        q = peer_queue or asyncio.Queue()
        return q, asyncio.create_task(self._accumulate_search_junction(search_queue, q))
