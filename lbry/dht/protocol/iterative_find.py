import asyncio
from itertools import chain
from collections import defaultdict, OrderedDict
from collections.abc import AsyncGenerator
import typing
import logging
from typing import TYPE_CHECKING
from lbry.dht import constants
from lbry.dht.error import RemoteException, TransportNotConnected
from lbry.dht.protocol.distance import Distance
from lbry.dht.peer import make_kademlia_peer
from lbry.dht.serialization.datagram import PAGE_KEY

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
        self.pages = int(result_dict.get(PAGE_KEY, 0))

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
    if len(key) != constants.HASH_LENGTH:
        raise ValueError("invalid key length: %i" % len(key))
    return shortlist or routing_table.find_close_peers(key)


class IterativeFinder(AsyncGenerator):
    def __init__(self, loop: asyncio.AbstractEventLoop, peer_manager: 'PeerManager',
                 routing_table: 'TreeRoutingTable', protocol: 'KademliaProtocol', key: bytes,
                 max_results: typing.Optional[int] = constants.K,
                 exclude: typing.Optional[typing.List[typing.Tuple[str, int]]] = None,
                 shortlist: typing.Optional[typing.List['KademliaPeer']] = None):
        if len(key) != constants.HASH_LENGTH:
            raise ValueError("invalid key length: %i" % len(key))
        self.loop = loop
        self.peer_manager = peer_manager
        self.routing_table = routing_table
        self.protocol = protocol

        self.key = key
        self.max_results = max(constants.K, max_results)
        self.exclude = exclude or []

        self.active: typing.Dict['KademliaPeer', int] = OrderedDict()  # peer: distance, sorted
        self.contacted: typing.Set['KademliaPeer'] = set()
        self.distance = Distance(key)

        self.iteration_queue = asyncio.Queue(loop=self.loop)

        self.running_probes: typing.Dict['KademliaPeer', asyncio.Task] = {}
        self.iteration_count = 0
        self.running = False
        self.tasks: typing.List[asyncio.Task] = []
        self.generator = None

        for peer in get_shortlist(routing_table, key, shortlist):
            if peer.node_id:
                self._add_active(peer, force=True)
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

    def get_initial_result(self) -> typing.List['KademliaPeer']:  #pylint: disable=no-self-use
        """
        Get an initial or cached result to be put into the Queue. Used for findValue requests where the blob
        has peers in the local data store of blobs announced to us
        """
        return []

    def _add_active(self, peer, force=False):
        if not force and self.peer_manager.peer_is_good(peer) is False:
            return
        if peer in self.contacted:
            return
        if peer not in self.active and peer.node_id and peer.node_id != self.protocol.node_id:
            self.active[peer] = self.distance(peer.node_id)
            self.active = OrderedDict(sorted(self.active.items(), key=lambda item: item[1]))

    async def _handle_probe_result(self, peer: 'KademliaPeer', response: FindResponse):
        self._add_active(peer)
        for contact_triple in response.get_close_triples():
            node_id, address, udp_port = contact_triple
            try:
                self._add_active(make_kademlia_peer(node_id, address, udp_port))
            except ValueError:
                log.warning("misbehaving peer %s:%i returned peer with reserved ip %s:%i", peer.address,
                            peer.udp_port, address, udp_port)
        self.check_result_ready(response)
        self._log_state()

    def _reset_closest(self, peer):
        if peer in self.active:
            del self.active[peer]

    async def _send_probe(self, peer: 'KademliaPeer'):
        try:
            response = await self.send_probe(peer)
        except asyncio.TimeoutError:
            self._reset_closest(peer)
            return
        except asyncio.CancelledError:
            log.debug("%s[%x] cancelled probe",
                      type(self).__name__, id(self))
            return
        except ValueError as err:
            log.warning(str(err))
            self._reset_closest(peer)
            return
        except TransportNotConnected:
            return self._aclose()
        except RemoteException:
            self._reset_closest(peer)
            return
        return await self._handle_probe_result(peer, response)

    def _search_round(self):
        """
        Send up to constants.alpha (5) probes to closest active peers
        """

        added = 0
        for index, peer in enumerate(self.active.keys()):
            if index == 0:
                log.debug("%s[%x] closest to probe: %s",
                          type(self).__name__, id(self),
                          peer.node_id.hex()[:8])
            if peer in self.contacted:
                continue
            if len(self.running_probes) >= constants.ALPHA:
                break
            if index > (constants.K + len(self.running_probes)):
                break
            if self.iteration_count + self.iteration_queue.qsize() >= self.max_results:
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
        log.debug("%s[%x] running %d probes for key %s",
                  type(self).__name__, id(self),
                  len(self.running_probes), self.key.hex()[:8])
        if not added and not self.running_probes:
            log.debug("%s[%x] search for %s exhausted",
                      type(self).__name__, id(self),
                      self.key.hex()[:8])
            self.search_exhausted()

    def _schedule_probe(self, peer: 'KademliaPeer'):
        self.contacted.add(peer)

        t = self.loop.create_task(self._send_probe(peer))

        def callback(_):
            self.running_probes.pop(peer, None)
            if self.running:
                self._search_round()

        t.add_done_callback(callback)
        self.running_probes[peer] = t

    def _log_state(self):
        log.debug("%s[%x] [%s] check result: %i active nodes %i contacted %i produced %i queued",
                  type(self).__name__, id(self), self.key.hex()[:8],
                  len(self.active), len(self.contacted),
                  self.iteration_count, self.iteration_queue.qsize())

    async def _generator_func(self):
        try:
            while self.iteration_count < self.max_results:
                if self.iteration_count == 0:
                    result = self.get_initial_result() or await self.iteration_queue.get()
                else:
                    result = await self.iteration_queue.get()
                if not result:
                    # no more results
                    await self._aclose(reason="no more results")
                    self.generator = None
                    return
                self.iteration_count += 1
                yield result
            # reached max_results limit
            await self._aclose(reason="max_results reached")
            self.generator = None
            return
        except asyncio.CancelledError:
            await self._aclose(reason="cancelled")
            self.generator = None
            raise
        except GeneratorExit:
            await self._aclose(reason="generator exit")
            self.generator = None
            raise

    def __aiter__(self):
        if self.running:
            raise Exception("already running")
        self.running = True
        self.generator = self._generator_func()
        self.loop.call_soon(self._search_round)
        return super().__aiter__()

    async def __anext__(self) -> typing.List['KademliaPeer']:
        return await super().__anext__()

    async def asend(self, val):
        return await self.generator.asend(val)

    async def athrow(self, typ, val=None, tb=None):
        return await self.generator.athrow(typ, val, tb)

    async def _aclose(self, reason="?"):
        self.running = False
        running_tasks = list(chain(self.tasks, self.running_probes.values()))
        for task in running_tasks:
            task.cancel()
        if len(running_tasks):
            await asyncio.wait(running_tasks, loop=self.loop)
        log.debug("%s[%x] [%s] async close because %s: %i active nodes %i contacted %i produced %i queued",
                  type(self).__name__, id(self), self.key.hex()[:8],
                  reason, len(self.active), len(self.contacted),
                  self.iteration_count, self.iteration_queue.qsize())
        self.tasks.clear()
        self.running_probes.clear()

    async def aclose(self):
        if self.generator:
            await super().aclose()
            self.generator = None
        log.debug("%s[%x] [%s] async close completed",
                  type(self).__name__, id(self), self.key.hex()[:8])


class IterativeNodeFinder(IterativeFinder):
    def __init__(self, loop: asyncio.AbstractEventLoop, peer_manager: 'PeerManager',
                 routing_table: 'TreeRoutingTable', protocol: 'KademliaProtocol', key: bytes,
                 max_results: typing.Optional[int] = constants.K,
                 exclude: typing.Optional[typing.List[typing.Tuple[str, int]]] = None,
                 shortlist: typing.Optional[typing.List['KademliaPeer']] = None):
        super().__init__(loop, peer_manager, routing_table, protocol, key, max_results, exclude,
                         shortlist)
        self.yielded_peers: typing.Set['KademliaPeer'] = set()

    async def send_probe(self, peer: 'KademliaPeer') -> FindNodeResponse:
        log.debug("probe %s:%d (%s) for NODE %s",
                  peer.address, peer.udp_port, peer.node_id.hex()[:8] if peer.node_id else '', self.key.hex()[:8])
        response = await self.protocol.get_rpc_peer(peer).find_node(self.key)
        return FindNodeResponse(self.key, response)

    def search_exhausted(self):
        self.put_result(self.active.keys(), finish=True)

    def put_result(self, from_iter: typing.Iterable['KademliaPeer'], finish=False):
        not_yet_yielded = [
            peer for peer in from_iter
            if peer not in self.yielded_peers
            and peer.node_id != self.protocol.node_id
            and self.peer_manager.peer_is_good(peer) is True  # return only peers who answered
        ]
        not_yet_yielded.sort(key=lambda peer: self.distance(peer.node_id))
        to_yield = not_yet_yielded[:max(constants.K, self.max_results)]
        if to_yield:
            self.yielded_peers.update(to_yield)
            self.iteration_queue.put_nowait(to_yield)
        if finish:
            self.iteration_queue.put_nowait(None)

    def check_result_ready(self, response: FindNodeResponse):
        found = response.found and self.key != self.protocol.node_id

        if found:
            log.debug("found")
            return self.put_result(self.active.keys(), finish=True)


class IterativeValueFinder(IterativeFinder):
    def __init__(self, loop: asyncio.AbstractEventLoop, peer_manager: 'PeerManager',
                 routing_table: 'TreeRoutingTable', protocol: 'KademliaProtocol', key: bytes,
                 max_results: typing.Optional[int] = constants.K,
                 exclude: typing.Optional[typing.List[typing.Tuple[str, int]]] = None,
                 shortlist: typing.Optional[typing.List['KademliaPeer']] = None):
        super().__init__(loop, peer_manager, routing_table, protocol, key, max_results, exclude,
                         shortlist)
        self.blob_peers: typing.Set['KademliaPeer'] = set()
        # this tracks the index of the most recent page we requested from each peer
        self.peer_pages: typing.DefaultDict['KademliaPeer', int] = defaultdict(int)
        # this tracks the set of blob peers returned by each peer
        self.discovered_peers: typing.Dict['KademliaPeer', typing.Set['KademliaPeer']] = defaultdict(set)

    async def send_probe(self, peer: 'KademliaPeer') -> FindValueResponse:
        log.debug("probe %s:%d (%s) for VALUE %s",
                  peer.address, peer.udp_port, peer.node_id.hex()[:8], self.key.hex()[:8])
        page = self.peer_pages[peer]
        response = await self.protocol.get_rpc_peer(peer).find_value(self.key, page=page)
        parsed = FindValueResponse(self.key, response)
        if not parsed.found:
            return parsed
        already_known = len(self.discovered_peers[peer])
        decoded_peers = set()
        for compact_addr in parsed.found_compact_addresses:
            try:
                decoded_peers.add(self.peer_manager.decode_tcp_peer_from_compact_address(compact_addr))
            except ValueError:
                log.warning("misbehaving peer %s:%i returned invalid peer for blob",
                            peer.address, peer.udp_port)
                self.peer_manager.report_failure(peer.address, peer.udp_port)
                parsed.found_compact_addresses.clear()
                return parsed
        self.discovered_peers[peer].update(decoded_peers)
        log.debug("probed %s:%i page %i, %i known", peer.address, peer.udp_port, page,
                  already_known + len(parsed.found_compact_addresses))
        if len(self.discovered_peers[peer]) != already_known + len(parsed.found_compact_addresses):
            log.warning("misbehaving peer %s:%i returned duplicate peers for blob", peer.address, peer.udp_port)
        elif len(parsed.found_compact_addresses) >= constants.K and self.peer_pages[peer] < parsed.pages:
            # the peer returned a full page and indicates it has more
            self.peer_pages[peer] += 1
            if peer in self.contacted:
                # the peer must be removed from self.contacted so that it will be probed for the next page
                self.contacted.remove(peer)
        return parsed

    def check_result_ready(self, response: FindValueResponse):
        if response.found:
            blob_peers = [self.peer_manager.decode_tcp_peer_from_compact_address(compact_addr)
                          for compact_addr in response.found_compact_addresses]
            to_yield = []
            for blob_peer in blob_peers:
                if blob_peer not in self.blob_peers:
                    self.blob_peers.add(blob_peer)
                    to_yield.append(blob_peer)
            if to_yield:
                self.iteration_queue.put_nowait(to_yield)

    def get_initial_result(self) -> typing.List['KademliaPeer']:
        if self.protocol.data_store.has_peers_for_blob(self.key):
            return self.protocol.data_store.get_peers_for_blob(self.key)
        return []
