import asyncio
from binascii import hexlify
from itertools import chain

import typing
import logging
from lbry.dht import constants
from lbry.dht.error import RemoteException, TransportNotConnected
from lbry.dht.protocol.distance import Distance

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from lbry.dht.protocol.routing_table import TreeRoutingTable
    from lbry.dht.protocol.protocol import KademliaProtocol
    from lbry.dht.peer import PeerManager, KademliaPeer

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
    return shortlist or routing_table.find_close_peers(key)


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

        self.active: typing.Set['KademliaPeer'] = set()
        self.contacted: typing.Set['KademliaPeer'] = set()
        self.distance = Distance(key)

        self.closest_peer: typing.Optional['KademliaPeer'] = None
        self.prev_closest_peer: typing.Optional['KademliaPeer'] = None

        self.iteration_queue = asyncio.Queue(loop=self.loop)

        self.running_probes: typing.Set[asyncio.Task] = set()
        self.iteration_count = 0
        self.bottom_out_count = 0
        self.running = False
        self.tasks: typing.List[asyncio.Task] = []
        self.delayed_calls: typing.List[asyncio.Handle] = []
        for peer in get_shortlist(routing_table, key, shortlist):
            if peer.node_id:
                self._add_active(peer)
            else:
                # seed nodes
                self._schedule_probe(peer)

    async def send_probe(self, peer: 'KademliaPeer') -> FindResponse:
        """
        Send the rpc request to the peer and return an object with the FindResponse interface
        """
        raise NotImplementedError()

    def search_exhausted(self):
        """
        This method ends the iterator due no more peers to contact.
        Override to provide last time results.
        """
        self.iteration_queue.put_nowait(None)

    def check_result_ready(self, response: FindResponse):
        """
        Called after adding peers from an rpc result to the shortlist.
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
        return not self.closest_peer or self.distance.is_closer(peer.node_id, self.closest_peer.node_id)

    def _add_active(self, peer):
        if peer not in self.active and peer.node_id and peer.node_id != self.protocol.node_id:
            self.active.add(peer)
            if self._is_closer(peer):
                self.prev_closest_peer = self.closest_peer
                self.closest_peer = peer

    async def _handle_probe_result(self, peer: 'KademliaPeer', response: FindResponse):
        self._add_active(peer)
        for contact_triple in response.get_close_triples():
            node_id, address, udp_port = contact_triple
            self._add_active(self.peer_manager.get_kademlia_peer(node_id, address, udp_port))
        self.check_result_ready(response)

    async def _send_probe(self, peer: 'KademliaPeer'):
        try:
            response = await self.send_probe(peer)
        except asyncio.TimeoutError:
            self.active.discard(peer)
            return
        except ValueError as err:
            log.warning(str(err))
            self.active.discard(peer)
            return
        except TransportNotConnected:
            return self.aclose()
        except RemoteException:
            return
        return await self._handle_probe_result(peer, response)

    async def _search_round(self):
        """
        Send up to constants.alpha (5) probes to closest active peers
        """

        added = 0
        to_probe = list(self.active - self.contacted)
        to_probe.sort(key=lambda peer: self.distance(self.key))
        for peer in to_probe:
            if added >= constants.alpha:
                break
            origin_address = (peer.address, peer.udp_port)
            if origin_address in self.exclude:
                continue
            if peer.node_id == self.protocol.node_id:
                continue
            if origin_address == (self.protocol.external_ip, self.protocol.udp_port):
                continue
            self._schedule_probe(peer)
            added += 1
        log.debug("running %d probes", len(self.running_probes))
        if not added and not self.running_probes:
            log.debug("search for %s exhausted", hexlify(self.key)[:8])
            self.search_exhausted()

    def _schedule_probe(self, peer: 'KademliaPeer'):
        self.contacted.add(peer)

        t = self.loop.create_task(self._send_probe(peer))

        def callback(_):
            self.running_probes.difference_update({
                probe for probe in self.running_probes if probe.done() or probe == t
            })
            if not self.running_probes:
                self.tasks.append(self.loop.create_task(self._search_task(0.0)))

        t.add_done_callback(callback)
        self.running_probes.add(t)

    async def _search_task(self, delay: typing.Optional[float] = constants.iterative_lookup_delay):
        try:
            if self.running:
                await self._search_round()
            if self.running:
                self.delayed_calls.append(self.loop.call_later(delay, self._search))
        except (asyncio.CancelledError, StopAsyncIteration, TransportNotConnected):
            if self.running:
                self.loop.call_soon(self.aclose)

    def _search(self):
        self.tasks.append(self.loop.create_task(self._search_task()))

    def __aiter__(self):
        if self.running:
            raise Exception("already running")
        self.running = True
        self._search()
        return self

    async def __anext__(self) -> typing.List['KademliaPeer']:
        try:
            if self.iteration_count == 0:
                result = self.get_initial_result() or await self.iteration_queue.get()
            else:
                result = await self.iteration_queue.get()
            if not result:
                raise StopAsyncIteration
            self.iteration_count += 1
            return result
        except (asyncio.CancelledError, StopAsyncIteration):
            self.loop.call_soon(self.aclose)
            raise

    def aclose(self):
        self.running = False
        self.iteration_queue.put_nowait(None)
        for task in chain(self.tasks, self.running_probes, self.delayed_calls):
            task.cancel()
        self.tasks.clear()
        self.running_probes.clear()
        self.delayed_calls.clear()


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
        log.debug("probing %s:%d %s", peer.address, peer.udp_port, hexlify(peer.node_id)[:8] if peer.node_id else '')
        response = await self.protocol.get_rpc_peer(peer).find_node(self.key)
        return FindNodeResponse(self.key, response)

    def search_exhausted(self):
        self.put_result(self.active, finish=True)

    def put_result(self, from_iter: typing.Iterable['KademliaPeer'], finish=False):
        not_yet_yielded = [
            peer for peer in from_iter
            if peer not in self.yielded_peers
               and peer.node_id != self.protocol.node_id
               and self.peer_manager.peer_is_good(peer) is not False
        ]
        not_yet_yielded.sort(key=lambda peer: self.distance(peer.node_id))
        to_yield = not_yet_yielded[:min(constants.k, len(not_yet_yielded))]
        if to_yield:
            self.yielded_peers.update(to_yield)
            self.iteration_queue.put_nowait(to_yield)
        if finish:
            self.iteration_queue.put_nowait(None)

    def check_result_ready(self, response: FindNodeResponse):
        found = response.found and self.key != self.protocol.node_id

        if found:
            log.debug("found")
            return self.put_result(self.active, finish=True)
        if self.prev_closest_peer and self.closest_peer and not self._is_closer(self.prev_closest_peer):
            # log.info("improving, %i %i %i %i %i", len(self.shortlist), len(self.active), len(self.contacted),
            #          self.bottom_out_count, self.iteration_count)
            self.bottom_out_count = 0
        elif self.prev_closest_peer and self.closest_peer:
            self.bottom_out_count += 1
            log.info("bottom out %i %i %i", len(self.active), len(self.contacted), self.bottom_out_count)
        if self.bottom_out_count >= self.bottom_out_limit or self.iteration_count >= self.bottom_out_limit:
            log.info("limit hit")
            self.put_result(self.active, True)


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
        elif self.prev_closest_peer and self.closest_peer:
            self.bottom_out_count += 1
            if self.bottom_out_count >= self.bottom_out_limit:
                log.info("blob peer search bottomed out")
                self.iteration_queue.put_nowait(None)

    def get_initial_result(self) -> typing.List['KademliaPeer']:
        if self.protocol.data_store.has_peers_for_blob(self.key):
            return self.protocol.data_store.get_peers_for_blob(self.key)
        return []
