import asyncio
import typing
import logging
from lbrynet.utils import drain_tasks
from lbrynet.dht import constants
from lbrynet.dht.error import RemoteException
from lbrynet.dht.protocol.distance import Distance

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from lbrynet.dht.protocol.routing_table import TreeRoutingTable
    from lbrynet.dht.protocol.protocol import KademliaProtocol
    from lbrynet.dht.peer import PeerManager, KademliaPeer

log = logging.getLogger(__name__)


class FindResponse:
    @property
    def found(self) -> bool:
        raise NotImplementedError()

    def get_close_triples(self) -> typing.List[typing.Tuple[bytes, str, int]]:
        raise NotImplementedError()


class FindNodeResponse(FindResponse):
    def __init__(self, key: bytes, close_triples: typing.List[typing.Tuple[bytes, str, int]]):
        self.key = key
        self.close_triples = close_triples

    @property
    def found(self) -> bool:
        return self.key in [triple[0] for triple in self.close_triples]

    def get_close_triples(self) -> typing.List[typing.Tuple[bytes, str, int]]:
        return self.close_triples


class FindValueResponse(FindResponse):
    def __init__(self, key: bytes, result_dict: typing.Dict):
        self.key = key
        self.token = result_dict[b'token']
        self.close_triples: typing.List[typing.Tuple[bytes, bytes, int]] = result_dict.get(b'contacts', [])
        self.found_compact_addresses = result_dict.get(key, [])

    @property
    def found(self) -> bool:
        return len(self.found_compact_addresses) > 0

    def get_close_triples(self) -> typing.List[typing.Tuple[bytes, str, int]]:
        return [(node_id, address.decode(), port) for node_id, address, port in self.close_triples]


def get_shortlist(routing_table: 'TreeRoutingTable', key: bytes,
                  shortlist: typing.Optional[typing.List['KademliaPeer']]) -> typing.List['KademliaPeer']:
    """
    If not provided, initialize the shortlist of peers to probe to the (up to) k closest peers in the routing table

    :param routing_table: a TreeRoutingTable
    :param key: a 48 byte hash
    :param shortlist: optional manually provided shortlist, this is done during bootstrapping when there are no
                      peers in the routing table. During bootstrap the shortlist is set to be the seed nodes.
    """
    if len(key) != constants.hash_length:
        raise ValueError("invalid key length: %i" % len(key))
    if not shortlist:
        shortlist = routing_table.find_close_peers(key)
    distance = Distance(key)
    shortlist.sort(key=lambda peer: distance(peer.node_id), reverse=True)
    return shortlist


class IterativeFinder:
    def __init__(self, loop: asyncio.BaseEventLoop, peer_manager: 'PeerManager',
                 routing_table: 'TreeRoutingTable', protocol: 'KademliaProtocol', key: bytes,
                 bottom_out_limit: typing.Optional[int] = 2, max_results: typing.Optional[int] = constants.k,
                 exclude: typing.Optional[typing.List[typing.Tuple[str, int]]] = None,
                 shortlist: typing.Optional[typing.List['KademliaPeer']] = None):
        if len(key) != constants.hash_length:
            raise ValueError("invalid key length: %i" % len(key))
        self.loop = loop
        self.peer_manager = peer_manager
        self.routing_table = routing_table
        self.protocol = protocol

        self.key = key
        self.bottom_out_limit = bottom_out_limit
        self.max_results = max_results
        self.exclude = exclude or []

        self.shortlist: typing.List['KademliaPeer'] = get_shortlist(routing_table, key, shortlist)
        self.active: typing.List['KademliaPeer'] = []
        self.contacted: typing.List[typing.Tuple[str, int]] = []
        self.distance = Distance(key)

        self.closest_peer: typing.Optional['KademliaPeer'] = None if not self.shortlist else self.shortlist[0]
        self.prev_closest_peer: typing.Optional['KademliaPeer'] = None

        self.iteration_queue = asyncio.Queue(loop=self.loop)

        self.running_probes: typing.List[asyncio.Task] = []
        self.lock = asyncio.Lock(loop=self.loop)
        self.iteration_count = 0
        self.bottom_out_count = 0
        self.running = False
        self.tasks: typing.List[asyncio.Task] = []
        self.delayed_calls: typing.List[asyncio.Handle] = []
        self.finished = asyncio.Event(loop=self.loop)

    async def send_probe(self, peer: 'KademliaPeer') -> FindResponse:
        """
        Send the rpc request to the peer and return an object with the FindResponse interface
        """
        raise NotImplementedError()

    def check_result_ready(self, response: FindResponse):
        """
        Called with a lock after adding peers from an rpc result to the shortlist.
        This method is responsible for putting a result for the generator into the Queue
        """
        raise NotImplementedError()

    def get_initial_result(self) -> typing.List['KademliaPeer']:
        """
        Get an initial or cached result to be put into the Queue. Used for findValue requests where the blob
        has peers in the local data store of blobs announced to us
        """
        return []

    def _is_closer(self, peer: 'KademliaPeer') -> bool:
        if not self.closest_peer:
            return True
        return self.distance.is_closer(peer.node_id, self.closest_peer.node_id)

    def _update_closest(self):
        self.shortlist.sort(key=lambda peer: self.distance(peer.node_id), reverse=True)
        if self.closest_peer and self.closest_peer is not self.shortlist[-1]:
            if self._is_closer(self.shortlist[-1]):
                self.prev_closest_peer = self.closest_peer
                self.closest_peer = self.shortlist[-1]

    async def _handle_probe_result(self, peer: 'KademliaPeer', response: FindResponse):
        async with self.lock:
            if peer not in self.shortlist:
                self.shortlist.append(peer)
            if peer not in self.active:
                self.active.append(peer)
            for contact_triple in response.get_close_triples():
                addr_tuple = (contact_triple[1], contact_triple[2])
                if addr_tuple not in self.contacted:  # and not self.peer_manager.is_ignored(addr_tuple)
                    found_peer = self.peer_manager.get_kademlia_peer(
                        contact_triple[0], contact_triple[1], contact_triple[2]
                    )
                    if found_peer not in self.shortlist and self.peer_manager.peer_is_good(peer) is not False:
                        self.shortlist.append(found_peer)
            self._update_closest()
            self.check_result_ready(response)

    async def _send_probe(self, peer: 'KademliaPeer'):
        try:
            response = await self.send_probe(peer)
        except asyncio.CancelledError:
            return
        except asyncio.TimeoutError:
            if peer in self.active:
                self.active.remove(peer)
            return
        except ValueError as err:
            log.warning(str(err))
            if peer in self.active:
                self.active.remove(peer)
            return
        except RemoteException:
            return
        return await self._handle_probe_result(peer, response)

    async def _search_round(self):
        """
        Send up to constants.alpha (5) probes to the closest peers in the shortlist
        """

        added = 0
        async with self.lock:
            self.shortlist.sort(key=lambda p: self.distance(p.node_id), reverse=True)
            while self.running and len(self.shortlist) and added < constants.alpha:
                peer = self.shortlist.pop()
                origin_address = (peer.address, peer.udp_port)
                if origin_address in self.exclude or self.peer_manager.peer_is_good(peer) is False:
                    continue
                if peer.node_id == self.protocol.node_id:
                    continue
                if (peer.address, peer.udp_port) == (self.protocol.external_ip, self.protocol.udp_port):
                    continue
                if (peer.address, peer.udp_port) not in self.contacted:
                    self.contacted.append((peer.address, peer.udp_port))

                    t = self.loop.create_task(self._send_probe(peer))

                    def callback(_):
                        if t and t in self.running_probes:
                            self.running_probes.remove(t)
                        if not self.running_probes and self.shortlist:
                            self.tasks.append(self.loop.create_task(self._search_task(0.0)))

                    t.add_done_callback(callback)
                    self.running_probes.append(t)
                    added += 1

    async def _search_task(self, delay: typing.Optional[float] = constants.iterative_lookup_delay):
        try:
            if self.running:
                await self._search_round()
            if self.running:
                self.delayed_calls.append(self.loop.call_later(delay, self._search))
        except (asyncio.CancelledError, StopAsyncIteration):
            if self.running:
                drain_tasks(self.running_probes)
                self.running = False

    def _search(self):
        self.tasks.append(self.loop.create_task(self._search_task()))

    def search(self):
        if self.running:
            raise Exception("already running")
        self.running = True
        self._search()

    async def next_queue_or_finished(self) -> typing.List['KademliaPeer']:
        peers = self.loop.create_task(self.iteration_queue.get())
        finished = self.loop.create_task(self.finished.wait())
        err = None
        try:
            await asyncio.wait([peers, finished], loop=self.loop, return_when='FIRST_COMPLETED')
            if peers.done():
                return peers.result()
            raise StopAsyncIteration()
        except asyncio.CancelledError as error:
            err = error
        finally:
            if not finished.done() and not finished.cancelled():
                finished.cancel()
            if not peers.done() and not peers.cancelled():
                peers.cancel()
            if err:
                raise err

    def __aiter__(self):
        self.search()
        return self

    async def __anext__(self) -> typing.List['KademliaPeer']:
        try:
            if self.iteration_count == 0:
                initial_results = self.get_initial_result()
                if initial_results:
                    self.iteration_queue.put_nowait(initial_results)
            result = await self.next_queue_or_finished()
            self.iteration_count += 1
            return result
        except (asyncio.CancelledError, StopAsyncIteration):
            await self.aclose()
            raise

    def aclose(self):
        self.running = False

        async def _aclose():
            async with self.lock:
                self.running = False
                if not self.finished.is_set():
                    self.finished.set()
                drain_tasks(self.tasks)
                drain_tasks(self.running_probes)
                while self.delayed_calls:
                    timer = self.delayed_calls.pop()
                    if timer:
                        timer.cancel()

        return asyncio.ensure_future(_aclose(), loop=self.loop)


class IterativeNodeFinder(IterativeFinder):
    def __init__(self, loop: asyncio.BaseEventLoop, peer_manager: 'PeerManager',
                 routing_table: 'TreeRoutingTable', protocol: 'KademliaProtocol', key: bytes,
                 bottom_out_limit: typing.Optional[int] = 2, max_results: typing.Optional[int] = constants.k,
                 exclude: typing.Optional[typing.List[typing.Tuple[str, int]]] = None,
                 shortlist: typing.Optional[typing.List['KademliaPeer']] = None):
        super().__init__(loop, peer_manager, routing_table, protocol, key, bottom_out_limit, max_results, exclude,
                         shortlist)
        self.yielded_peers: typing.Set['KademliaPeer'] = set()

    async def send_probe(self, peer: 'KademliaPeer') -> FindNodeResponse:
        response = await self.protocol.get_rpc_peer(peer).find_node(self.key)
        return FindNodeResponse(self.key, response)

    def put_result(self, from_list: typing.List['KademliaPeer']):
        not_yet_yielded = [peer for peer in from_list if peer not in self.yielded_peers]
        not_yet_yielded.sort(key=lambda peer: self.distance(peer.node_id))
        to_yield = not_yet_yielded[:min(constants.k, len(not_yet_yielded))]
        if to_yield:
            for peer in to_yield:
                self.yielded_peers.add(peer)
            self.iteration_queue.put_nowait(to_yield)

    def check_result_ready(self, response: FindNodeResponse):
        found = response.found and self.key != self.protocol.node_id

        if found:
            log.info("found")
            self.put_result(self.shortlist)
            if not self.finished.is_set():
                self.finished.set()
            return
        if self.prev_closest_peer and self.closest_peer and not self._is_closer(self.prev_closest_peer):
            # log.info("improving, %i %i %i %i %i", len(self.shortlist), len(self.active), len(self.contacted),
            #          self.bottom_out_count, self.iteration_count)
            self.bottom_out_count = 0
        elif self.prev_closest_peer and self.closest_peer:
            self.bottom_out_count += 1
            log.info("bottom out %i %i %i %i", len(self.active), len(self.contacted), len(self.shortlist),
                     self.bottom_out_count)
        if self.bottom_out_count >= self.bottom_out_limit or self.iteration_count >= self.bottom_out_limit:
            log.info("limit hit")
            self.put_result(self.active)
            if not self.finished.is_set():
                self.finished.set()
            return
        if self.max_results and len(self.active) - len(self.yielded_peers) >= self.max_results:
            log.info("max results")
            self.put_result(self.active)
            if not self.finished.is_set():
                self.finished.set()
            return


class IterativeValueFinder(IterativeFinder):
    def __init__(self, loop: asyncio.BaseEventLoop, peer_manager: 'PeerManager',
                 routing_table: 'TreeRoutingTable', protocol: 'KademliaProtocol', key: bytes,
                 bottom_out_limit: typing.Optional[int] = 2, max_results: typing.Optional[int] = constants.k,
                 exclude: typing.Optional[typing.List[typing.Tuple[str, int]]] = None,
                 shortlist: typing.Optional[typing.List['KademliaPeer']] = None):
        super().__init__(loop, peer_manager, routing_table, protocol, key, bottom_out_limit, max_results, exclude,
                         shortlist)
        self.blob_peers: typing.Set['KademliaPeer'] = set()

    async def send_probe(self, peer: 'KademliaPeer') -> FindValueResponse:
        response = await self.protocol.get_rpc_peer(peer).find_value(self.key)
        return FindValueResponse(self.key, response)

    def check_result_ready(self, response: FindValueResponse):
        if response.found:
            blob_peers = [self.peer_manager.decode_tcp_peer_from_compact_address(compact_addr)
                          for compact_addr in response.found_compact_addresses]
            to_yield = []
            self.bottom_out_count = 0
            for blob_peer in blob_peers:
                if blob_peer not in self.blob_peers:
                    self.blob_peers.add(blob_peer)
                    to_yield.append(blob_peer)
            if to_yield:
                # log.info("found %i new peers for blob", len(to_yield))
                self.iteration_queue.put_nowait(to_yield)
                # if self.max_results and len(self.blob_peers) >= self.max_results:
                #     log.info("enough blob peers found")
                #     if not self.finished.is_set():
                #         self.finished.set()
            return
        if self.prev_closest_peer and self.closest_peer:
            self.bottom_out_count += 1
            if self.bottom_out_count >= self.bottom_out_limit:
                log.info("blob peer search bottomed out")
                if not self.finished.is_set():
                    self.finished.set()
                return

    def get_initial_result(self) -> typing.List['KademliaPeer']:
        if self.protocol.data_store.has_peers_for_blob(self.key):
            return self.protocol.data_store.get_peers_for_blob(self.key)
        return []
