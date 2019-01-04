import binascii
import asyncio
import typing
import logging

from lbrynet.peer import Peer, PeerManager
from lbrynet.dht import constants
from lbrynet.dht.error import UnknownRemoteException
from lbrynet.dht.routing.distance import Distance
from lbrynet.dht.routing.routing_table import TreeRoutingTable
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from lbrynet.dht.protocol.protocol import KademliaProtocol

log = logging.getLogger(__name__)


def get_contact(contact_list, node_id, address, port):
    for contact in contact_list:
        if contact.node_id == node_id and contact.address == address and contact.udp_port == port:
            return contact
    raise IndexError(node_id)


def expand_peer(compact_peer_info) -> typing.Tuple[bytes, str, int]:
    host = "{}.{}.{}.{}".format(*compact_peer_info[:4])
    port = int.from_bytes(compact_peer_info[4:6], 'big')
    peer_node_id = compact_peer_info[6:]
    return (peer_node_id, host, port)


def sort_result(cumulative_find_result: typing.Set, key: bytes) -> typing.Union[typing.List[Peer]]:
    list_result = list(cumulative_find_result)
    if not all((r.node_id is not None for r in list_result)):
        return list_result
    distance = Distance(key)
    list_result.sort(key=lambda c: distance(c.node_id))
    return list_result


def get_shortlist(routing_table: TreeRoutingTable, key: bytes, shortlist: typing.Optional[typing.List[Peer]]) -> typing.List[Peer]:
    if len(key) != constants.hash_length:
        raise ValueError("invalid key length: %i" % len(key))
    if not shortlist:
        return routing_table.find_close_peers(key)
    return shortlist


class IterativeFinder:
    def __init__(self, loop: asyncio.BaseEventLoop, peer_manager: PeerManager,
                 routing_table: TreeRoutingTable, protocol: 'KademliaProtocol', shortlist: typing.List,
                 key: bytes, rpc: str, exclude: typing.Optional[typing.List] = None, bottom_out_limit: int = 2):
        self.iteration = 0
        self.loop = loop
        self.protocol = protocol
        self.node_id = protocol.node_id
        assert rpc in ['findValue', 'findNode'], ValueError(rpc)
        self.bottom_out_limit = bottom_out_limit
        self.exclude = set(exclude or [])
        if len(key) != constants.hash_length:
            raise ValueError("invalid key length: %i" % len(key))
        self.key = key
        self.rpc = rpc
        self.shortlist: typing.List[Peer] = get_shortlist(routing_table, key, list(shortlist or []))
        self.routing_table = routing_table
        self.peer_manager = peer_manager
        # all distance operations in this class only care about the distance
        # to self.key, so this makes it easier to calculate those
        self.distance = Distance(key)

        # The closest known and active node yet found
        self.closest_node = None if not self.shortlist else self.shortlist[0]
        self.prev_closest_node = None

        # List of active queries; len() indicates number of active probes
        self.active_probes = []
        # List of contact (address, port) tuples that have already been queried, includes contacts that didn't reply
        self.already_contacted = []
        # A list of found and known-to-be-active remote nodes (Contact objects)
        self.active_contacts = []

        # Ensure only one searchIteration call is running at a time
        self.lock = asyncio.Lock(loop=self.loop)
        self.iteration_count = 0

        self.find_value_result: typing.List[Peer] = []
        self.pending_iteration_calls: typing.List[asyncio.TimerHandle] = []
        self.pending_iteration_tasks: typing.List[asyncio.Task] = []

        self.is_find_value_request = rpc == "findValue"
        self.iteration_fut: asyncio.Future = asyncio.Future(loop=self.loop)
        self.iteration_futures: typing.List[asyncio.Future] = [self.iteration_fut]

    def is_closer(self, contact):
        if not self.closest_node:
            return True
        return self.distance.is_closer(contact.node_id, self.closest_node.node_id)

    def get_contact_triples(self, result):
        if self.is_find_value_request:
            contact_triples = result[b'contacts']
        else:
            contact_triples = result
        for contact_tup in contact_triples:
            if not isinstance(contact_tup, (list, tuple)) or len(contact_tup) != 3:
                raise ValueError("invalid contact triple")
            contact_tup[1] = contact_tup[1].decode()  # ips are strings
        return contact_triples

    async def probe_contact(self, contact: Peer):
        log.debug("probe %s(%s) %s:%i (%s)", self.rpc, binascii.hexlify(self.key)[:8].decode(), contact.address,
                  contact.udp_port, binascii.hexlify(contact.node_id)[:8].decode())
        if self.rpc == "findNode":
            fn = contact.find_node
        else:
            fn = contact.find_value
        try:
            response = await fn(self.key)
            # assert contact in self.node.contacts
            return await self.extend_shortlist(contact, response)
        except (TimeoutError, ValueError, IndexError, asyncio.TimeoutError, asyncio.CancelledError) as err:
            return contact.node_id
        except UnknownRemoteException as err:
            log.warning(err)
            # log.exception("%s %s %s:%i %s - %s", self.rpc, binascii.hexlify(self.key).decode(),
            #               contact.address, contact.udp_port, binascii.hexlify(contact.node_id).decode(), err)
            return contact.node_id

    async def extend_shortlist(self, contact, result):
        # The "raw response" tuple contains the response message and the originating address info
        origin_address = (contact.address, contact.udp_port)
        if self.iteration_fut.done():
            return contact.node_id
        if self.peer_manager.is_ignored(origin_address):
            raise ValueError("contact is ignored")
        if contact.node_id == self.node_id:
            return contact.node_id

        if contact not in self.active_contacts:
            self.active_contacts.append(contact)
        if contact not in self.shortlist:
            self.shortlist.append(contact)

        # Now grow extend the (unverified) shortlist with the returned contacts
        # TODO: some validation on the result (for guarding against attacks)
        # If we are looking for a value, first see if this result is the value
        # we are looking for before treating it as a list of contact triples
        if self.is_find_value_request and self.key in result:
            # TODO: store the found value to the closest node that did not return a result
            # We have found the value
            for peer in result[self.key]:
                node_id, host, port = expand_peer(peer)
                if (host, port) not in self.exclude:
                    self.exclude.add((host, port))
                    self.find_value_result.append(self.peer_manager.make_peer(host, node_id, tcp_port=port))
                    log.debug("found new peer: %s", self.find_value_result[-1])
            if self.find_value_result:
                async with self.lock:
                    self.iteration_fut.set_result(self.find_value_result)
        else:
            contact_triples = self.get_contact_triples(result)
            for contact_triple in contact_triples:
                if (contact_triple[1], contact_triple[2]) in ((c.address, c.udp_port) for c in self.already_contacted):
                    continue
                elif self.peer_manager.is_ignored((contact_triple[1], contact_triple[2])):
                    continue
                else:
                    found_contact = self.peer_manager.make_peer(contact_triple[1], contact_triple[0],
                                                                udp_port=contact_triple[2])
                    if found_contact not in self.shortlist:
                        self.shortlist.append(found_contact)

            if not self.iteration_fut.done() and self.should_stop():
                self.active_contacts.sort(key=lambda c: self.distance(c.node_id))
                async with self.lock:
                    self.iteration_fut.set_result(self.active_contacts[:min(constants.k, len(self.active_contacts))])

        return contact.node_id

    def should_stop(self) -> bool:
        if self.is_find_value_request:
            # search stops when it finds a value, let it run
            return False
        if self.prev_closest_node and self.closest_node and self.distance.is_closer(self.prev_closest_node.node_id,
                                                                                    self.closest_node.node_id):
            # we're getting further away
            return True
        if len(self.active_contacts) >= constants.k:
            # we have enough results
            return True
        return False

    async def _search_iteration(self):
        log.debug("%s %i contacts in shortlist, active: %i, contacted: %i", self.rpc, len(self.shortlist),
                 len(self.active_contacts), len(self.already_contacted))
        self.iteration_count += 1
        # Sort the discovered active nodes from closest to furthest
        if len(self.active_contacts):
            self.active_contacts.sort(key=lambda c: self.distance(c.node_id))
            self.prev_closest_node = self.closest_node
            self.closest_node = self.active_contacts[0]

        # Sort the current shortList before contacting other nodes
        self.shortlist.sort(key=lambda c: self.distance(c.node_id))
        probes = []
        already_contacted_addresses = {(c.address, c.udp_port) for c in self.already_contacted}
        to_remove = []
        for contact in self.shortlist:
            if self.peer_manager.is_ignored((contact.address, contact.udp_port)):
                to_remove.append(contact)  # a contact became bad during iteration
                continue
            if (contact.address == self.protocol.external_ip) and (contact.udp_port == self.protocol.udp_port):
                to_remove.append(contact)
                continue
            if (contact.address, contact.udp_port) not in already_contacted_addresses:
                self.already_contacted.append(contact)
                to_remove.append(contact)
                probe = self.probe_contact(contact)
                probes.append(probe)
                self.active_probes.append(probe)
            if len(probes) == constants.alpha:
                break

        for contact in to_remove:  # these contacts will be re-added to the shortlist when they reply successfully
            self.shortlist.remove(contact)

        if probes:
            self.search_iteration()
            await asyncio.gather(*tuple(probes), loop=self.loop)
            for probe in probes:
                self.active_probes.remove(probe)
        elif not self.active_probes and not self.iteration_fut.done() and not self.iteration_fut.cancelled():
            # If no probes were sent, there will not be any improvement, so we're done
            log.debug("no improvement")
            if self.is_find_value_request:
                self.iteration_fut.set_result(self.find_value_result)
            else:
                self.active_contacts.sort(key=lambda c: self.distance(c.node_id))
                self.iteration_fut.set_result(self.active_contacts[:min(constants.k, len(self.active_contacts))])
        elif not self.iteration_fut.done() and not self.iteration_fut.cancelled():
            # Force the next iteration
            self.search_iteration()

    def search_iteration(self, delay=constants.iterative_lookup_delay):
        l = lambda: self.pending_iteration_tasks.append(self.loop.create_task(self._search_iteration()))
        self.pending_iteration_calls.append(self.loop.call_later(delay, l))

    def __aiter__(self):
        return self

    async def __anext__(self) -> typing.List[Peer]:
        self.iteration += 1
        if self.iteration == 1 and self.rpc == 'findValue' and self.protocol.data_store.has_peers_for_blob(self.key):
            log.info("had cached peers")
            return self.protocol.data_store.get_peers_for_blob(self.key)
        self.search_iteration()
        try:
            return await self.next()
        except asyncio.CancelledError:
            self.astop()
            raise StopAsyncIteration()

    async def next(self) -> typing.List[Peer]:
        try:
            return await self.iteration_fut
        finally:
            try:
                await self.lock.acquire()
                self.iteration_fut = asyncio.Future(loop=self.loop)
                self.iteration_futures.append(self.iteration_fut)
            finally:
                self.lock.release()

    def astop(self):
        while self.pending_iteration_tasks:
            task = self.pending_iteration_tasks.pop()
            if task and not (task.done() or task.cancelled()):
                task.cancel()
        log.debug("stop %i iteration calls", len(self.pending_iteration_calls))
        while self.pending_iteration_calls:
            timer = self.pending_iteration_calls.pop()
            if timer and not timer.cancelled():
                timer.cancel()

    async def iterative_find(self, max_results: int = constants.k) -> typing.AsyncIterator[typing.List[Peer]]:
        """
        async generator that yields results from an iterative find as they are found
        """
        try:
            accumulated = set()
            bottomed_out = 0
            async for iteration_result in self:
                new_peers: typing.List[Peer] = []
                if not isinstance(iteration_result, list):
                    log.error("unexpected iteration result: \"%s\"", iteration_result)
                    iteration_result = []
                for peer in iteration_result:
                    if peer not in accumulated:
                        accumulated.add(peer)
                        new_peers.append(peer)
                        bottomed_out = 0
                if not new_peers:
                    bottomed_out += 1
                else:
                    bottomed_out = 0
                    if self.rpc == 'findValue':
                        log.debug("new peers: %i", len(new_peers))
                    yield new_peers
                if (bottomed_out >= self.bottom_out_limit) or ((max_results > 0) and (len(accumulated) >= max_results)):
                    log.info("%s(%s...) has %i results, bottom out counter: %i", self.rpc, binascii.hexlify(self.key).decode()[:8],
                             len(accumulated), bottomed_out)
                    log.info("%i contacts known", len(self.routing_table.get_peers()))
                    break
        except Exception as err:
            log.error("iterative find error: %s", err)
            raise err
        finally:
            self.astop()
            log.info("stopped iterative finder %s %s", self.rpc, binascii.hexlify(self.key).decode()[:8])
