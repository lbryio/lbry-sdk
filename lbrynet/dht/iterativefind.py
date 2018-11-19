import binascii
import asyncio
import typing
import logging
from twisted.internet import defer
from lbrynet.dht.distance import Distance
from lbrynet.dht.error import TimeoutError, UnknownRemoteException
from lbrynet.dht import constants
from lbrynet.peer import BlobPeer, PeerManager, DHTPeer
log = logging.getLogger(__name__)


def get_contact(contact_list, node_id, address, port):
    for contact in contact_list:
        if contact.id == node_id and contact.address == address and contact.port == port:
            return contact
    raise IndexError(node_id)


def expand_peer(compact_peer_info) -> typing.Tuple[bytes, str, int]:
    host = "{}.{}.{}.{}".format(*compact_peer_info[:4])
    port = int.from_bytes(compact_peer_info[4:6], 'big')
    peer_node_id = compact_peer_info[6:]
    return (peer_node_id, host, port)


def sort_result(cumulative_find_result: typing.Set, key: bytes) -> typing.Union[typing.List[BlobPeer],
                                                                                typing.List[DHTPeer]]:
    list_result = list(cumulative_find_result)
    if all((isinstance(r, BlobPeer) for r in list_result)):
        return list_result
    distance = Distance(key)
    list_result.sort(key=lambda c: distance(c.id))
    return list_result


def get_shortlist(node, key: bytes, shortlist: typing.Optional[typing.List[DHTPeer]]) -> typing.List[DHTPeer]:
    if len(key) != constants.key_bits // 8:
        raise ValueError("invalid key length: %i" % len(key))
    if not shortlist:
        return node._routingTable.findCloseNodes(key)
    return shortlist


class IterativeFinder:
    def __init__(self, node, shortlist: typing.List, key: bytes, rpc: str,
                 exclude: typing.Optional[typing.List] = None, bottom_out_limit: int = 3):
        assert rpc in ['findValue', 'findNode'], ValueError(rpc)
        self.bottom_out_limit = bottom_out_limit
        self.exclude = set(exclude or [])
        if len(key) != constants.key_bits // 8:
            raise ValueError("invalid key length: %i" % len(key))
        self.key = key
        self.rpc = rpc
        self.shortlist: typing.List[DHTPeer] = get_shortlist(node, key, list(shortlist or []))

        self.node = node
        self.peer_manager: PeerManager = node.peer_manager
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
        self.lock = asyncio.Lock()
        self.iteration_count = 0
        self.iteration_futures = []

        self.find_value_result: typing.List[BlobPeer] = []
        self.pending_iteration_calls = []
        self.loop = asyncio.get_event_loop()

        self.is_find_value_request = rpc == "findValue"
        self.iteration_fut: asyncio.Future = asyncio.Future()

    def is_closer(self, contact):
        if not self.closest_node:
            return True
        return self.distance.is_closer(contact.id, self.closest_node.id)

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

    async def probe_contact(self, contact: DHTPeer):
        log.debug("probe %s(%s) %s:%i (%s)", self.rpc, binascii.hexlify(self.key)[:8].decode(), contact.address,
                 contact.port, binascii.hexlify(contact.id)[:8].decode())
        fn = getattr(contact, self.rpc)
        try:
            response = await asyncio.wait_for(fn(self.key).asFuture(self.loop), constants.rpcTimeout)
            # assert contact in self.node.contacts
            return await self.extend_shortlist(contact, response)
        except (TimeoutError, defer.CancelledError, ValueError, IndexError, asyncio.TimeoutError) as err:
            return contact.id
        except UnknownRemoteException as err:
            log.exception("%s %s %s:%i %s - %s", self.rpc, binascii.hexlify(self.key).decode(),
                          contact.address, contact.port, binascii.hexlify(contact.id).decode(), err)
            return contact.id

    async def extend_shortlist(self, contact, result):
        # The "raw response" tuple contains the response message and the originating address info
        origin_address = (contact.address, contact.port)
        if self.iteration_fut.done():
            return contact.id
        if self.node.peer_manager.is_ignored(origin_address):
            raise ValueError("contact is ignored")
        if contact.id == self.node.node_id:
            return contact.id

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
                    self.find_value_result.append(self.peer_manager.make_blob_peer(node_id, host, port))
            if self.find_value_result:
                async with self.lock:
                    self.iteration_fut.set_result(self.find_value_result)
        else:
            contact_triples = self.get_contact_triples(result)
            for contact_triple in contact_triples:
                if (contact_triple[1], contact_triple[2]) in ((c.address, c.port) for c in self.already_contacted):
                    continue
                elif self.node.peer_manager.is_ignored((contact_triple[1], contact_triple[2])):
                    continue
                else:
                    found_contact = self.node.peer_manager.make_dht_peer(contact_triple[0], contact_triple[1],
                                                                            contact_triple[2], self.node._protocol)
                    if found_contact not in self.shortlist:
                        self.shortlist.append(found_contact)

            if not self.iteration_fut.done() and self.should_stop():
                self.active_contacts.sort(key=lambda c: self.distance(c.id))
                async with self.lock:
                    self.iteration_fut.set_result(self.active_contacts[:min(constants.k, len(self.active_contacts))])

        return contact.id

    def should_stop(self) -> bool:
        if self.is_find_value_request:
            # search stops when it finds a value, let it run
            return False
        if self.prev_closest_node and self.closest_node and self.distance.is_closer(self.prev_closest_node.id,
                                                                                    self.closest_node.id):
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
            self.active_contacts.sort(key=lambda c: self.distance(c.id))
            self.prev_closest_node = self.closest_node
            self.closest_node = self.active_contacts[0]

        # Sort the current shortList before contacting other nodes
        self.shortlist.sort(key=lambda c: self.distance(c.id))
        probes = []
        already_contacted_addresses = {(c.address, c.port) for c in self.already_contacted}
        to_remove = []
        for contact in self.shortlist:
            if self.node.peer_manager.is_ignored((contact.address, contact.port)):
                to_remove.append(contact)  # a contact became bad during iteration
                continue
            if (contact.address, contact.port) not in already_contacted_addresses:
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
        elif not self.active_probes:
            # If no probes were sent, there will not be any improvement, so we're done
            if self.is_find_value_request:
                self.iteration_fut.set_result(self.find_value_result)
            else:
                self.active_contacts.sort(key=lambda c: self.distance(c.id))
                self.iteration_fut.set_result(self.active_contacts[:min(constants.k, len(self.active_contacts))])
        elif not self.iteration_fut.done():
            # Force the next iteration
            self.search_iteration()

    def search_iteration(self, delay=constants.iterativeLookupDelay):
        self.pending_iteration_calls.append(
            self.loop.call_later(delay, lambda: self.loop.create_task(self._search_iteration()))
        )

    def __aiter__(self):
        return self

    async def __anext__(self) -> typing.Union[typing.List[DHTPeer], typing.List[BlobPeer]]:
        if self.iteration_fut not in self.iteration_futures:
            self.iteration_futures.append(self.iteration_fut)
        self.search_iteration()
        r = await self.iteration_fut
        async with self.lock:
            self.iteration_fut = asyncio.Future()
        return r

    def stop(self):
        log.debug("stop %i iteration calls", len(self.pending_iteration_calls))
        while self.pending_iteration_calls:
            timer = self.pending_iteration_calls.pop()
            if timer and not timer.cancelled():
                timer.cancel()

    async def iterative_find(self, max_results: int = constants.k
                             ) -> typing.AsyncIterator[typing.Union[typing.List[DHTPeer], typing.List[BlobPeer]]]:
        """
        async generator that yields results from an iterative find as they are found
        """
        try:
            i = 0
            accumulated = set()
            bottomed_out = 0
            async for iteration_result in self:
                r: typing.List = iteration_result
                for peer in r:
                    if peer not in accumulated:
                        accumulated.add(peer)
                        bottomed_out = -1
                bottomed_out += 1
                if r:
                    yield r
                i += 1
                if (bottomed_out >= self.bottom_out_limit) or (len(accumulated) >= max_results):
                    log.debug("%s %s bottomed out %i, %i", self.rpc, binascii.hexlify(self.key).decode(),
                              bottomed_out, len(accumulated))
                    break
        finally:
            self.stop()

    @classmethod
    async def cumulative_find(cls, node, shortlist: typing.Optional[typing.List], key: bytes, rpc: str,
                              exclude: typing.Optional[typing.List] = None, max_results=constants.k,
                              bottom_out_limit: int = 3) -> typing.Union[typing.List[BlobPeer], typing.List[DHTPeer]]:
        """
        Accumulate iterative find results until a given number has been found or until no improvement is made.

        :param node: 'lbrynet.dht.node.Node' object
        :param shortlist: optional list of contacts, if not provided use the k closest from the routing table
        :param key: the key to search for
        :param rpc: the search operation, findValue or findNode
        :param exclude: optional list of (host, port) tuples to exclude from the search and results
        :param max_results: the number of results to accumulate
        :param bottom_out_limit: iterations with no improvement before returning if the total has not been met
        """

        results = []
        finder = cls(node, shortlist, key, rpc, exclude, bottom_out_limit)
        async for iteration_result in finder.iterative_find(max_results):  # pylint: disable=E1133
            assert isinstance(iteration_result, list)
            for i in iteration_result:
                if i not in results:
                    results.append(i)
            log.debug("%s, %i, %i", rpc, len(iteration_result), len(results))
        return results
