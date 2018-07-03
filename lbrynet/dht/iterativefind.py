import logging
from twisted.internet import defer
from distance import Distance
from error import TimeoutError
import constants

log = logging.getLogger(__name__)


def get_contact(contact_list, node_id, address, port):
    for contact in contact_list:
        if contact.id == node_id and contact.address == address and contact.port == port:
            return contact
    raise IndexError(node_id)


class _IterativeFind(object):
    # TODO: use polymorphism to search for a value or node
    #       instead of using a find_value flag
    def __init__(self, node, shortlist, key, rpc):
        self.node = node
        self.finished_deferred = defer.Deferred()
        # all distance operations in this class only care about the distance
        # to self.key, so this makes it easier to calculate those
        self.distance = Distance(key)
        # The closest known and active node yet found
        self.closest_node = None if not shortlist else shortlist[0]
        self.prev_closest_node = None
        # Shortlist of contact objects (the k closest known contacts to the key from the routing table)
        self.shortlist = shortlist
        # The search key
        self.key = str(key)
        # The rpc method name (findValue or findNode)
        self.rpc = rpc
        # List of active queries; len() indicates number of active probes
        self.active_probes = []
        # List of contact (address, port) tuples that have already been queried, includes contacts that didn't reply
        self.already_contacted = []
        # A list of found and known-to-be-active remote nodes (Contact objects)
        self.active_contacts = []
        # Ensure only one searchIteration call is running at a time
        self._search_iteration_semaphore = defer.DeferredSemaphore(1)
        self._iteration_count = 0
        self.find_value_result = {}
        self.pending_iteration_calls = []

    @property
    def is_find_node_request(self):
        return self.rpc == "findNode"

    @property
    def is_find_value_request(self):
        return self.rpc == "findValue"

    def is_closer(self, contact):
        if not self.closest_node:
            return True
        return self.distance.is_closer(contact.id, self.closest_node.id)

    def getContactTriples(self, result):
        if self.is_find_value_request:
            contact_triples = result['contacts']
        else:
            contact_triples = result
        for contact_tup in contact_triples:
            if not isinstance(contact_tup, (list, tuple)) or len(contact_tup) != 3:
                raise ValueError("invalid contact triple")
        return contact_triples

    def sortByDistance(self, contact_list):
        """Sort the list of contacts in order by distance from key"""
        contact_list.sort(key=lambda c: self.distance(c.id))

    @defer.inlineCallbacks
    def extendShortlist(self, contact, result):
        # The "raw response" tuple contains the response message and the originating address info
        originAddress = (contact.address, contact.port)
        if self.finished_deferred.called:
            defer.returnValue(contact.id)
        if self.node.contact_manager.is_ignored(originAddress):
            raise ValueError("contact is ignored")
        if contact.id == self.node.node_id:
            defer.returnValue(contact.id)

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
            self.find_value_result[self.key] = result[self.key]
            self.finished_deferred.callback(self.find_value_result)
        else:
            if self.is_find_value_request:
                # We are looking for a value, and the remote node didn't have it
                # - mark it as the closest "empty" node, if it is
                # TODO: store to this peer after finding the value as per the kademlia spec
                if 'closestNodeNoValue' in self.find_value_result:
                    if self.is_closer(contact):
                        self.find_value_result['closestNodeNoValue'] = contact
                else:
                    self.find_value_result['closestNodeNoValue'] = contact
            contactTriples = self.getContactTriples(result)
            for contactTriple in contactTriples:
                if (contactTriple[1], contactTriple[2]) in ((c.address, c.port) for c in self.already_contacted):
                    continue
                elif self.node.contact_manager.is_ignored((contactTriple[1], contactTriple[2])):
                    raise ValueError("contact is ignored")
                else:
                    found_contact = self.node.contact_manager.make_contact(contactTriple[0], contactTriple[1],
                                                                           contactTriple[2], self.node._protocol)
                    if found_contact not in self.shortlist:
                        self.shortlist.append(found_contact)

            if not self.finished_deferred.called and self.should_stop():
                self.sortByDistance(self.active_contacts)
                self.finished_deferred.callback(self.active_contacts[:min(constants.k, len(self.active_contacts))])

        defer.returnValue(contact.id)

    @defer.inlineCallbacks
    def probeContact(self, contact):
        fn = getattr(contact, self.rpc)
        try:
            response = yield fn(self.key)
            result = yield self.extendShortlist(contact, response)
            defer.returnValue(result)
        except (TimeoutError, defer.CancelledError, ValueError, IndexError):
            defer.returnValue(contact.id)

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

    # Send parallel, asynchronous FIND_NODE RPCs to the shortlist of contacts
    def _searchIteration(self):
        # Sort the discovered active nodes from closest to furthest
        if len(self.active_contacts):
            self.sortByDistance(self.active_contacts)
            self.prev_closest_node = self.closest_node
            self.closest_node = self.active_contacts[0]

        # Sort the current shortList before contacting other nodes
        self.sortByDistance(self.shortlist)
        probes = []
        already_contacted_addresses = {(c.address, c.port) for c in self.already_contacted}
        to_remove = []
        for contact in self.shortlist:
            if (contact.address, contact.port) not in already_contacted_addresses:
                self.already_contacted.append(contact)
                to_remove.append(contact)
                probe = self.probeContact(contact)
                probes.append(probe)
                self.active_probes.append(probe)
            if len(probes) == constants.alpha:
                break
        for contact in to_remove:  # these contacts will be re-added to the shortlist when they reply successfully
            self.shortlist.remove(contact)

        # run the probes
        if probes:
            # Schedule the next iteration if there are any active
            # calls (Kademlia uses loose parallelism)
            self.searchIteration()

            d = defer.DeferredList(probes, consumeErrors=True)

            def _remove_probes(results):
                for probe in probes:
                    self.active_probes.remove(probe)
                return results

            d.addCallback(_remove_probes)

        elif not self.finished_deferred.called and not self.active_probes or self.should_stop():
            # If no probes were sent, there will not be any improvement, so we're done
            self.sortByDistance(self.active_contacts)
            self.finished_deferred.callback(self.active_contacts[:min(constants.k, len(self.active_contacts))])
        elif not self.finished_deferred.called:
            # Force the next iteration
            self.searchIteration()

    def searchIteration(self, delay=constants.iterativeLookupDelay):
        def _cancel_pending_iterations(result):
            while self.pending_iteration_calls:
                canceller = self.pending_iteration_calls.pop()
                canceller()
            return result
        self.finished_deferred.addBoth(_cancel_pending_iterations)
        self._iteration_count += 1
        call, cancel = self.node.reactor_callLater(delay, self._search_iteration_semaphore.run, self._searchIteration)
        self.pending_iteration_calls.append(cancel)


def iterativeFind(node, shortlist, key, rpc):
    helper = _IterativeFind(node, shortlist, key, rpc)
    helper.searchIteration(0)
    return helper.finished_deferred
