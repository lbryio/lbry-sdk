import binascii
import asyncio
import logging
from twisted.internet import defer
from lbrynet.dht.distance import Distance
from lbrynet.dht.error import TimeoutError
from lbrynet.dht import constants

log = logging.getLogger(__name__)


def get_contact(contact_list, node_id, address, port):
    for contact in contact_list:
        if contact.id == node_id and contact.address == address and contact.port == port:
            return contact
    raise IndexError(node_id)


def expand_peer(compact_peer_info):
    host = "{}.{}.{}.{}".format(*compact_peer_info[:4])
    port = int.from_bytes(compact_peer_info[4:6], 'big')
    peer_node_id = compact_peer_info[6:]
    return (peer_node_id, host, port)


class IterativeFinder:
    def __init__(self, node, shortlist, key, rpc, exclude=None):
        self.exclude = set(exclude or [])
        self.key = key
        assert rpc in ['findValue', 'findNode']
        self.rpc = rpc
        self.shortlist = list(shortlist or [])
        self.node = node

        # all distance operations in this class only care about the distance
        # to self.key, so this makes it easier to calculate those
        self.distance = Distance(key)

        # The closest known and active node yet found
        self.closest_node = None if not shortlist else shortlist[0]
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

        self.find_value_result = {}
        self.pending_iteration_calls = []
        self.loop = asyncio.get_event_loop()

        self.is_find_value_request = rpc == "findValue"
        self.finished = asyncio.Future()

        def cancel_pending_iterations(_):
            log.info("cancel pending iterations")
            while self.pending_iteration_calls:
                timer = self.pending_iteration_calls.pop()
                if timer and not timer.cancelled():
                    timer.cancel()

        self.finished.add_done_callback(cancel_pending_iterations)

    def is_closer(self, contact):
        if not self.closest_node:
            return True
        return self.distance.is_closer(contact.id, self.closest_node.id)

    def get_contact_triples(self, result):
        if self.is_find_value_request:
            log.info(result)
            contact_triples = result[b'contacts']
        else:
            contact_triples = result
        for contact_tup in contact_triples:
            if not isinstance(contact_tup, (list, tuple)) or len(contact_tup) != 3:
                raise ValueError("invalid contact triple")
            contact_tup[1] = contact_tup[1].decode()  # ips are strings
        return contact_triples

    def sort_by_distance(self, contact_list):
        """Sort the list of contacts in order by distance from key"""
        contact_list.sort(key=lambda c: self.distance(c.id))

    async def probe_contact(self, contact):
        log.info("probe %s(%s) %s:%i (%s)", self.rpc, binascii.hexlify(self.key).decode(), contact.address, contact.port, binascii.hexlify(contact.id)[:8].decode())
        fn = getattr(contact, self.rpc)
        try:
            response = await fn(self.key).asFuture(self.loop)
            return self.extend_shortlist(contact, response)
        except (TimeoutError, defer.CancelledError, ValueError, IndexError):
            return contact.id

    def extend_shortlist(self, contact, result):
        # The "raw response" tuple contains the response message and the originating address info
        origin_address = (contact.address, contact.port)
        if self.finished.done():
            return contact.id
        if self.node.contact_manager.is_ignored(origin_address):
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
            # We have found the value
            for peer in result[self.key]:
                node_id, host, port = expand_peer(peer)
                if (host, port) not in self.exclude:
                    self.find_value_result.setdefault(self.key, []).append((node_id, host, port))
            if self.find_value_result:
                self.finished.set_result(self.find_value_result)
        else:
            if self.is_find_value_request:
                # We are looking for a value, and the remote node didn't have it
                # - mark it as the closest "empty" node, if it is
                # TODO: store to this peer after finding the value as per the kademlia spec
                if b'closestNodeNoValue' in self.find_value_result:
                    if self.is_closer(contact):
                        self.find_value_result[b'closestNodeNoValue'] = contact
                else:
                    self.find_value_result[b'closestNodeNoValue'] = contact
            contact_triples = self.get_contact_triples(result)
            for contact_triple in contact_triples:
                if (contact_triple[1], contact_triple[2]) in ((c.address, c.port) for c in self.already_contacted):
                    continue
                elif self.node.contact_manager.is_ignored((contact_triple[1], contact_triple[2])):
                    continue
                else:
                    found_contact = self.node.contact_manager.make_contact(contact_triple[0], contact_triple[1],
                                                                           contact_triple[2], self.node._protocol)
                    if found_contact not in self.shortlist:
                        self.shortlist.append(found_contact)

            if not self.finished.done() and self.should_stop():
                self.sort_by_distance(self.active_contacts)
                self.finished.set_result(self.active_contacts[:min(constants.k, len(self.active_contacts))])

        return contact.id

    def should_stop(self):
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
        self.iteration_count += 1
        log.info("search iteration %s %i", self.rpc, self.iteration_count)
        # Sort the discovered active nodes from closest to furthest
        if len(self.active_contacts):
            self.sort_by_distance(self.active_contacts)
            self.prev_closest_node = self.closest_node
            self.closest_node = self.active_contacts[0]

        # Sort the current shortList before contacting other nodes
        self.sort_by_distance(self.shortlist)
        probes = []
        already_contacted_addresses = {(c.address, c.port) for c in self.already_contacted}
        to_remove = []
        async with self.lock:
            for contact in self.shortlist:
                if self.node.contact_manager.is_ignored((contact.address, contact.port)):
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
            async with self.lock:
                for probe in probes:
                    self.active_probes.remove(probe)
        elif not self.active_probes:
            # If no probes were sent, there will not be any improvement, so we're done
            if self.is_find_value_request:
                self.finished.set_result(self.find_value_result)
            else:
                self.sort_by_distance(self.active_contacts)
                self.finished.set_result(self.active_contacts[:min(constants.k, len(self.active_contacts))])
        elif not self.finished.done():
            # Force the next iteration
            self.search_iteration()

    def search_iteration(self, delay=constants.iterativeLookupDelay):
        self.pending_iteration_calls.append(
            self.loop.call_later(delay, lambda : self.loop.create_task(self._search_iteration()))
        )

    def search(self, delay=constants.iterativeLookupDelay):
        self.search_iteration(delay)
        return self.finished


def iterativeFind(node, shortlist, key, rpc, exclude=None) -> defer.Deferred:
    helper = IterativeFinder(node, shortlist, key, rpc, exclude)
    return defer.Deferred.fromFuture(helper.search(0))


# class _IterativeFind:
#     # TODO: use polymorphism to search for a value or node
#     #       instead of using a find_value flag
#     def __init__(self, node, shortlist, key, rpc, exclude=None):
#         self.exclude = set(exclude or [])
#         self.node = node
#         self.finished_deferred = defer.Deferred()
#         # all distance operations in this class only care about the distance
#         # to self.key, so this makes it easier to calculate those
#         self.distance = Distance(key)
#         # The closest known and active node yet found
#         self.closest_node = None if not shortlist else shortlist[0]
#         self.prev_closest_node = None
#         # Shortlist of contact objects (the k closest known contacts to the key from the routing table)
#         self.shortlist = shortlist
#         # The search key
#         self.key = key
#         # The rpc method name (findValue or findNode)
#         self.rpc = rpc
#         # List of active queries; len() indicates number of active probes
#         self.active_probes = []
#         # List of contact (address, port) tuples that have already been queried, includes contacts that didn't reply
#         self.already_contacted = []
#         # A list of found and known-to-be-active remote nodes (Contact objects)
#         self.active_contacts = []
#         # Ensure only one searchIteration call is running at a time
#         self._search_iteration_semaphore = defer.DeferredSemaphore(1)
#         self._iteration_count = 0
#         self.find_value_result = {}
#         self.pending_iteration_calls = []
#
#     @property
#     def is_find_node_request(self):
#         return self.rpc == "findNode"
#
#     @property
#     def is_find_value_request(self):
#         return self.rpc == "findValue"
#
#     def is_closer(self, contact):
#         if not self.closest_node:
#             return True
#         return self.distance.is_closer(contact.id, self.closest_node.id)
#
#     def getContactTriples(self, result):
#         if self.is_find_value_request:
#             contact_triples = result['contacts']
#         else:
#             contact_triples = result
#         for contact_tup in contact_triples:
#             if not isinstance(contact_tup, (list, tuple)) or len(contact_tup) != 3:
#                 raise ValueError("invalid contact triple")
#             contact_tup[1] = contact_tup[1].decode()  # ips are strings
#         return contact_triples
#
#     def sortByDistance(self, contact_list):
#         """Sort the list of contacts in order by distance from key"""
#         contact_list.sort(key=lambda c: self.distance(c.id))
#
#     def extendShortlist(self, contact, result):
#         # The "raw response" tuple contains the response message and the originating address info
#         originAddress = (contact.address, contact.port)
#         if self.finished_deferred.called:
#             return contact.id
#         if self.node.contact_manager.is_ignored(originAddress):
#             raise ValueError("contact is ignored")
#         if contact.id == self.node.node_id:
#             return contact.id
#
#         if contact not in self.active_contacts:
#             self.active_contacts.append(contact)
#         if contact not in self.shortlist:
#             self.shortlist.append(contact)
#
#         # Now grow extend the (unverified) shortlist with the returned contacts
#         # TODO: some validation on the result (for guarding against attacks)
#         # If we are looking for a value, first see if this result is the value
#         # we are looking for before treating it as a list of contact triples
#         if self.is_find_value_request and self.key in result:
#             # We have found the value
#             for peer in result[self.key]:
#                 node_id, host, port = expand_peer(peer)
#                 if (host, port) not in self.exclude:
#                     self.find_value_result.setdefault(self.key, []).append((node_id, host, port))
#             if self.find_value_result:
#                 self.finished_deferred.callback(self.find_value_result)
#         else:
#             if self.is_find_value_request:
#                 # We are looking for a value, and the remote node didn't have it
#                 # - mark it as the closest "empty" node, if it is
#                 # TODO: store to this peer after finding the value as per the kademlia spec
#                 if 'closestNodeNoValue' in self.find_value_result:
#                     if self.is_closer(contact):
#                         self.find_value_result['closestNodeNoValue'] = contact
#                 else:
#                     self.find_value_result['closestNodeNoValue'] = contact
#             contactTriples = self.getContactTriples(result)
#             for contactTriple in contactTriples:
#                 if (contactTriple[1], contactTriple[2]) in ((c.address, c.port) for c in self.already_contacted):
#                     continue
#                 elif self.node.contact_manager.is_ignored((contactTriple[1], contactTriple[2])):
#                     continue
#                 else:
#                     found_contact = self.node.contact_manager.make_contact(contactTriple[0], contactTriple[1],
#                                                                            contactTriple[2], self.node._protocol)
#                     if found_contact not in self.shortlist:
#                         self.shortlist.append(found_contact)
#
#             if not self.finished_deferred.called and self.should_stop():
#                 self.sortByDistance(self.active_contacts)
#                 self.finished_deferred.callback(self.active_contacts[:min(constants.k, len(self.active_contacts))])
#
#         return contact.id
#
#     @defer.inlineCallbacks
#     def probeContact(self, contact):
#         fn = getattr(contact, self.rpc)
#         try:
#             response = yield fn(self.key)
#             result = self.extendShortlist(contact, response)
#             defer.returnValue(result)
#         except (TimeoutError, defer.CancelledError, ValueError, IndexError):
#             defer.returnValue(contact.id)
#
#     def should_stop(self):
#         if self.is_find_value_request:
#             # search stops when it finds a value, let it run
#             return False
#         if self.prev_closest_node and self.closest_node and self.distance.is_closer(self.prev_closest_node.id,
#                                                                                     self.closest_node.id):
#             # we're getting further away
#             return True
#         if len(self.active_contacts) >= constants.k:
#             # we have enough results
#             return True
#         return False
#
#     # Send parallel, asynchronous FIND_NODE RPCs to the shortlist of contacts
#     def _searchIteration(self):
#         # Sort the discovered active nodes from closest to furthest
#         if len(self.active_contacts):
#             self.sortByDistance(self.active_contacts)
#             self.prev_closest_node = self.closest_node
#             self.closest_node = self.active_contacts[0]
#
#         # Sort the current shortList before contacting other nodes
#         self.sortByDistance(self.shortlist)
#         probes = []
#         already_contacted_addresses = {(c.address, c.port) for c in self.already_contacted}
#         to_remove = []
#         for contact in self.shortlist:
#             if self.node.contact_manager.is_ignored((contact.address, contact.port)):
#                 to_remove.append(contact)  # a contact became bad during iteration
#                 continue
#             if (contact.address, contact.port) not in already_contacted_addresses:
#                 self.already_contacted.append(contact)
#                 to_remove.append(contact)
#                 probe = self.probeContact(contact)
#                 probes.append(probe)
#                 self.active_probes.append(probe)
#             if len(probes) == constants.alpha:
#                 break
#         for contact in to_remove:  # these contacts will be re-added to the shortlist when they reply successfully
#             self.shortlist.remove(contact)
#
#         # run the probes
#         if probes:
#             # Schedule the next iteration if there are any active
#             # calls (Kademlia uses loose parallelism)
#             self.searchIteration()
#
#             d = defer.DeferredList(probes, consumeErrors=True)
#
#             def _remove_probes(results):
#                 for probe in probes:
#                     self.active_probes.remove(probe)
#                 return results
#
#             d.addCallback(_remove_probes)
#
#         elif not self.finished_deferred.called and not self.active_probes or self.should_stop():
#             # If no probes were sent, there will not be any improvement, so we're done
#             if self.is_find_value_request:
#                 self.finished_deferred.callback(self.find_value_result)
#             else:
#                 self.sortByDistance(self.active_contacts)
#                 self.finished_deferred.callback(self.active_contacts[:min(constants.k, len(self.active_contacts))])
#         elif not self.finished_deferred.called:
#             # Force the next iteration
#             self.searchIteration()
#
#     def searchIteration(self, delay=constants.iterativeLookupDelay):
#         def _cancel_pending_iterations(result):
#             while self.pending_iteration_calls:
#                 canceller = self.pending_iteration_calls.pop()
#                 canceller()
#             return result
#         self.finished_deferred.addBoth(_cancel_pending_iterations)
#         self._iteration_count += 1
#         call, cancel = self.node.reactor_callLater(delay, self._search_iteration_semaphore.run, self._searchIteration)
#         self.pending_iteration_calls.append(cancel)
