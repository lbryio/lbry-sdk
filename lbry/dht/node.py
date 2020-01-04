import logging
import asyncio
import typing
import binascii
import socket
from lbry.utils import resolve_host
from lbry.dht import constants
from lbry.dht.peer import make_kademlia_peer
from lbry.dht.protocol.distance import Distance
from lbry.dht.protocol.iterative_find import IterativeNodeFinder, IterativeValueFinder
from lbry.dht.protocol.protocol import KademliaProtocol

if typing.TYPE_CHECKING:
    from lbry.dht.peer import PeerManager
    from lbry.dht.peer import KademliaPeer

log = logging.getLogger(__name__)


class Node:
    def __init__(self, loop: asyncio.AbstractEventLoop, peer_manager: 'PeerManager', node_id: bytes, udp_port: int,
                 internal_udp_port: int, peer_port: int, external_ip: str, rpc_timeout: float = constants.RPC_TIMEOUT,
                 split_buckets_under_index: int = constants.SPLIT_BUCKETS_UNDER_INDEX,
                 storage: typing.Optional['SQLiteStorage'] = None):
        self.loop = loop
        self.internal_udp_port = internal_udp_port
        self.protocol = KademliaProtocol(loop, peer_manager, node_id, external_ip, udp_port, peer_port, rpc_timeout,
                                         split_buckets_under_index)
        self.listening_port: asyncio.DatagramTransport = None
        self.joined = asyncio.Event(loop=self.loop)
        self._join_task: asyncio.Task = None
        self._refresh_task: asyncio.Task = None
        self._storage = storage

    async def refresh_node(self, force_once=False):
        while True:
            # remove peers with expired blob announcements from the datastore
            self.protocol.data_store.removed_expired_peers()

            total_peers: typing.List['KademliaPeer'] = []
            # add all peers in the routing table
            total_peers.extend(self.protocol.routing_table.get_peers())
            # add all the peers who have announced blobs to us
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
                self.loop.call_later(constants.REFRESH_INTERVAL // 4, fut.set_result, None)
                await fut
                continue

            # ping the set of peers; upon success/failure the routing able and last replied/failed time will be updated
            to_ping = [peer for peer in set(total_peers) if self.protocol.peer_manager.peer_is_good(peer) is not True]
            if to_ping:
                self.protocol.ping_queue.enqueue_maybe_ping(*to_ping, delay=0)
            if self._storage:
                await self._storage.save_kademlia_peers(self.protocol.routing_table.get_peers())
            if force_once:
                break

            fut = asyncio.Future(loop=self.loop)
            self.loop.call_later(constants.REFRESH_INTERVAL, fut.set_result, None)
            await fut

    async def announce_blob(self, blob_hash: str) -> typing.List[bytes]:
        hash_value = binascii.unhexlify(blob_hash.encode())
        assert len(hash_value) == constants.HASH_LENGTH
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
            log.debug(
                "Stored %s to %i of %i attempted peers", binascii.hexlify(hash_value).decode()[:8],
                len(stored_to), len(peers)
            )
        else:
            log.debug("Failed announcing %s, stored to 0 peers", blob_hash[:8])
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

    async def start_listening(self, interface: str = '0.0.0.0') -> None:
        if not self.listening_port:
            self.listening_port, _ = await self.loop.create_datagram_endpoint(
                lambda: self.protocol, (interface, self.internal_udp_port)
            )
            log.info("DHT node listening on UDP %s:%i", interface, self.internal_udp_port)
            self.protocol.start()
        else:
            log.warning("Already bound to port %s", self.listening_port)

    async def join_network(self, interface: str = '0.0.0.0',
                           known_node_urls: typing.Optional[typing.List[typing.Tuple[str, int]]] = None):
        def peers_from_urls(urls: typing.Optional[typing.List[typing.Tuple[bytes, str, int, int]]]):
            peer_addresses = []
            for node_id, address, udp_port, tcp_port in urls:
                if (node_id, address, udp_port, tcp_port) not in peer_addresses and \
                        (address, udp_port) != (self.protocol.external_ip, self.protocol.udp_port):
                    peer_addresses.append((node_id, address, udp_port, tcp_port))
            return [make_kademlia_peer(*peer_address) for peer_address in peer_addresses]

        if not self.listening_port:
            await self.start_listening(interface)
        self.protocol.ping_queue.start()
        self._refresh_task = self.loop.create_task(self.refresh_node())

        while True:
            if self.protocol.routing_table.get_peers():
                if not self.joined.is_set():
                    self.joined.set()
                    log.info(
                        "joined dht, %i peers known in %i buckets", len(self.protocol.routing_table.get_peers()),
                        self.protocol.routing_table.buckets_with_contacts()
                    )
            else:
                if self.joined.is_set():
                    self.joined.clear()
                seed_peers = peers_from_urls(
                    await self._storage.get_persisted_kademlia_peers()
                ) if self._storage else []
                if not seed_peers:
                    try:
                        seed_peers.extend(peers_from_urls([
                            (None, await resolve_host(address, udp_port, 'udp'), udp_port, None)
                            for address, udp_port in known_node_urls or []
                        ]))
                    except socket.gaierror:
                        await asyncio.sleep(30, loop=self.loop)
                        continue

                self.protocol.peer_manager.reset()
                self.protocol.ping_queue.enqueue_maybe_ping(*seed_peers, delay=0.0)
                await self.peer_search(self.protocol.node_id, shortlist=seed_peers, count=32)

            await asyncio.sleep(1, loop=self.loop)

    def start(self, interface: str, known_node_urls: typing.Optional[typing.List[typing.Tuple[str, int]]] = None):
        self._join_task = self.loop.create_task(self.join_network(interface, known_node_urls))

    def get_iterative_node_finder(self, key: bytes, shortlist: typing.Optional[typing.List['KademliaPeer']] = None,
                                  bottom_out_limit: int = constants.BOTTOM_OUT_LIMIT,
                                  max_results: int = constants.K) -> IterativeNodeFinder:

        return IterativeNodeFinder(self.loop, self.protocol.peer_manager, self.protocol.routing_table, self.protocol,
                                   key, bottom_out_limit, max_results, None, shortlist)

    def get_iterative_value_finder(self, key: bytes, shortlist: typing.Optional[typing.List['KademliaPeer']] = None,
                                   bottom_out_limit: int = 40,
                                   max_results: int = -1) -> IterativeValueFinder:

        return IterativeValueFinder(self.loop, self.protocol.peer_manager, self.protocol.routing_table, self.protocol,
                                    key, bottom_out_limit, max_results, None, shortlist)

    async def peer_search(self, node_id: bytes, count=constants.K, max_results=constants.K * 2,
                          bottom_out_limit=20, shortlist: typing.Optional[typing.List['KademliaPeer']] = None
                          ) -> typing.List['KademliaPeer']:
        peers = []
        async for iteration_peers in self.get_iterative_node_finder(
                node_id, shortlist=shortlist, bottom_out_limit=bottom_out_limit, max_results=max_results):
            peers.extend(iteration_peers)
        distance = Distance(node_id)
        peers.sort(key=lambda peer: distance(peer.node_id))
        return peers[:count]

    async def _accumulate_peers_for_value(self, search_queue: asyncio.Queue, result_queue: asyncio.Queue):
        tasks = []
        try:
            while True:
                blob_hash = await search_queue.get()
                tasks.append(self.loop.create_task(self._peers_for_value_producer(blob_hash, result_queue)))
        finally:
            for task in tasks:
                task.cancel()

    async def _peers_for_value_producer(self, blob_hash: str, result_queue: asyncio.Queue):
        async def put_into_result_queue_after_pong(_peer):
            try:
                await self.protocol.get_rpc_peer(_peer).ping()
                result_queue.put_nowait([_peer])
                log.debug("pong from %s:%i for %s", _peer.address, _peer.udp_port, blob_hash)
            except asyncio.TimeoutError:
                pass

        # prioritize peers who reply to a dht ping first
        # this minimizes attempting to make tcp connections that won't work later to dead or unreachable peers

        async for results in self.get_iterative_value_finder(binascii.unhexlify(blob_hash.encode())):
            to_put = []
            for peer in results:
                if peer.address == self.protocol.external_ip and self.protocol.peer_port == peer.tcp_port:
                    continue
                is_good = self.protocol.peer_manager.peer_is_good(peer)
                if is_good:
                    # the peer has replied recently over UDP, it can probably be reached on the TCP port
                    to_put.append(peer)
                elif is_good is None:
                    if not peer.udp_port:
                        # TODO: use the same port for TCP and UDP
                        # the udp port must be guessed
                        # default to the ports being the same. if the TCP port appears to be <=0.48.0 default,
                        # including on a network with several nodes, then assume the udp port is proportionately
                        # based on a starting port of 4444
                        udp_port_to_try = peer.tcp_port
                        if 3400 > peer.tcp_port > 3332:
                            udp_port_to_try = (peer.tcp_port - 3333) + 4444
                        self.loop.create_task(put_into_result_queue_after_pong(
                            make_kademlia_peer(peer.node_id, peer.address, udp_port_to_try, peer.tcp_port)
                        ))
                    else:
                        self.loop.create_task(put_into_result_queue_after_pong(peer))
                else:
                    # the peer is known to be bad/unreachable, skip trying to connect to it over TCP
                    log.debug("skip bad peer %s:%i for %s", peer.address, peer.tcp_port, blob_hash)
            if to_put:
                result_queue.put_nowait(to_put)

    def accumulate_peers(self, search_queue: asyncio.Queue,
                         peer_queue: typing.Optional[asyncio.Queue] = None
                         ) -> typing.Tuple[asyncio.Queue, asyncio.Task]:
        queue = peer_queue or asyncio.Queue(loop=self.loop)
        return queue, self.loop.create_task(self._accumulate_peers_for_value(search_queue, queue))
