#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive
#
# The docstrings in this module contain epytext markup; API documentation
# may be created by processing this file with epydoc: http://epydoc.sf.net
import binascii
import hashlib
import struct
import time
import logging
from twisted.internet import defer, error, task

from lbrynet.core.utils import generate_id, DeferredDict
from lbrynet.core.call_later_manager import CallLaterManager
from lbrynet.core.PeerManager import PeerManager
from error import TimeoutError
import constants
import routingtable
import datastore
import protocol
from peerfinder import DHTPeerFinder
from contact import ContactManager
from distance import Distance
from iterativefind import iterativeFind


log = logging.getLogger(__name__)


def expand_peer(compact_peer_info):
    host = ".".join([str(ord(d)) for d in compact_peer_info[:4]])
    port, = struct.unpack('>H', compact_peer_info[4:6])
    peer_node_id = compact_peer_info[6:]
    return (peer_node_id, host, port)



def rpcmethod(func):
    """ Decorator to expose Node methods as remote procedure calls

    Apply this decorator to methods in the Node class (or a subclass) in order
    to make them remotely callable via the DHT's RPC mechanism.
    """
    func.rpcmethod = True
    return func


class MockKademliaHelper(object):
    def __init__(self, clock=None, callLater=None, resolve=None, listenUDP=None):
        if not listenUDP or not resolve or not callLater or not clock:
            from twisted.internet import reactor
            listenUDP = listenUDP or reactor.listenUDP
            resolve = resolve or reactor.resolve
            callLater = callLater or reactor.callLater
            clock = clock or reactor

        self.clock = clock
        self.contact_manager = ContactManager(self.clock.seconds)
        self.reactor_listenUDP = listenUDP
        self.reactor_resolve = resolve
        self.call_later_manager = CallLaterManager(callLater)
        self.reactor_callLater = self.call_later_manager.call_later
        self.reactor_callSoon = self.call_later_manager.call_soon

        self._listeningPort = None  # object implementing Twisted
        # IListeningPort This will contain a deferred created when
        # joining the network, to enable publishing/retrieving
        # information from the DHT as soon as the node is part of the
        # network (add callbacks to this deferred if scheduling such
        # operations before the node has finished joining the network)

    def get_looping_call(self, fn, *args, **kwargs):
        lc = task.LoopingCall(fn, *args, **kwargs)
        lc.clock = self.clock
        return lc

    def safe_stop_looping_call(self, lc):
        if lc and lc.running:
            return lc.stop()
        return defer.succeed(None)

    def safe_start_looping_call(self, lc, t):
        if lc and not lc.running:
            lc.start(t)


class Node(MockKademliaHelper):
    """ Local node in the Kademlia network

    This class represents a single local node in a Kademlia network; in other
    words, this class encapsulates an Entangled-using application's "presence"
    in a Kademlia network.

    In Entangled, all interactions with the Kademlia network by a client
    application is performed via this class (or a subclass).
    """

    def __init__(self, node_id=None, udpPort=4000, dataStore=None,
                 routingTableClass=None, networkProtocol=None,
                 externalIP=None, peerPort=3333, listenUDP=None,
                 callLater=None, resolve=None, clock=None, peer_finder=None,
                 peer_manager=None):
        """
        @param dataStore: The data store to use. This must be class inheriting
                          from the C{DataStore} interface (or providing the
                          same API). How the data store manages its data
                          internally is up to the implementation of that data
                          store.
        @type dataStore: entangled.kademlia.datastore.DataStore
        @param routingTable: The routing table class to use. Since there exists
                             some ambiguity as to how the routing table should be
                             implemented in Kademlia, a different routing table
                             may be used, as long as the appropriate API is
                             exposed. This should be a class, not an object,
                             in order to allow the Node to pass an
                             auto-generated node ID to the routingtable object
                             upon instantiation (if necessary).
        @type routingTable: entangled.kademlia.routingtable.RoutingTable
        @param networkProtocol: The network protocol to use. This can be
                                overridden from the default to (for example)
                                change the format of the physical RPC messages
                                being transmitted.
        @type networkProtocol: entangled.kademlia.protocol.KademliaProtocol
        @param externalIP: the IP at which this node can be contacted
        @param peerPort: the port at which this node announces it has a blob for
        """

        MockKademliaHelper.__init__(self, clock, callLater, resolve, listenUDP)
        self.node_id = node_id or self._generateID()
        self.port = udpPort
        self._change_token_lc = self.get_looping_call(self.change_token)
        self._refresh_node_lc = self.get_looping_call(self._refreshNode)

        # Create k-buckets (for storing contacts)
        if routingTableClass is None:
            self._routingTable = routingtable.TreeRoutingTable(self.node_id, self.clock.seconds)
        else:
            self._routingTable = routingTableClass(self.node_id, self.clock.seconds)

        # Initialize this node's network access mechanisms
        if networkProtocol is None:
            self._protocol = protocol.KademliaProtocol(self)
        else:
            self._protocol = networkProtocol
        # Initialize the data storage mechanism used by this node
        self.token_secret = self._generateID()
        self.old_token_secret = None
        self.externalIP = externalIP
        self.peerPort = peerPort
        self._dataStore = dataStore or datastore.DictDataStore(self.clock.seconds)
        self.peer_manager = peer_manager or PeerManager()
        self.peer_finder = peer_finder or DHTPeerFinder(self, self.peer_manager)
        self._join_deferred = None

    def __del__(self):
        log.warning("unclean shutdown of the dht node")
        if self._listeningPort is not None:
            self._listeningPort.stopListening()

    @defer.inlineCallbacks
    def stop(self):
        # stop LoopingCalls:
        yield self.safe_stop_looping_call(self._refresh_node_lc)
        yield self.safe_stop_looping_call(self._change_token_lc)
        if self._listeningPort is not None:
            yield self._listeningPort.stopListening()
        self._listeningPort = None

    def start_listening(self):
        if not self._listeningPort:
            try:
                self._listeningPort = self.reactor_listenUDP(self.port, self._protocol)
            except error.CannotListenError as e:
                import traceback
                log.error("Couldn't bind to port %d. %s", self.port, traceback.format_exc())
                raise ValueError("%s lbrynet may already be running." % str(e))
        else:
            log.warning("Already bound to port %s", self._listeningPort)

    @defer.inlineCallbacks
    def joinNetwork(self, known_node_addresses=(('jack.lbry.tech', 4455), )):
        """
        Attempt to join the dht, retry every 30 seconds if unsuccessful
        :param known_node_addresses: [(str, int)] list of hostnames and ports for known dht seed nodes
        """

        self._join_deferred = defer.Deferred()
        known_node_resolution = {}

        @defer.inlineCallbacks
        def _resolve_seeds():
            result = {}
            for host, port in known_node_addresses:
                node_address = yield self.reactor_resolve(host)
                result[(host, port)] = node_address
            defer.returnValue(result)

        if not known_node_resolution:
            known_node_resolution = yield _resolve_seeds()
            # we are one of the seed nodes, don't add ourselves
            if (self.externalIP, self.port) in known_node_resolution.itervalues():
                del known_node_resolution[(self.externalIP, self.port)]
                known_node_addresses.remove((self.externalIP, self.port))

        def _ping_contacts(contacts):
            d = DeferredDict({contact: contact.ping() for contact in contacts}, consumeErrors=True)
            d.addErrback(lambda err: err.trap(TimeoutError))
            return d

        @defer.inlineCallbacks
        def _initialize_routing():
            bootstrap_contacts = []
            contact_addresses = {(c.address, c.port): c for c in self.contacts}
            for (host, port), ip_address in known_node_resolution.iteritems():
                if (host, port) not in contact_addresses:
                    # Create temporary contact information for the list of addresses of known nodes
                    # The contact node id will be set with the responding node id when we initialize it to None
                    contact = self.contact_manager.make_contact(None, ip_address, port, self._protocol)
                    bootstrap_contacts.append(contact)
                else:
                    for contact in self.contacts:
                        if contact.address == ip_address and contact.port == port:
                            if not contact.id:
                                bootstrap_contacts.append(contact)
                            break
            if not bootstrap_contacts:
                log.warning("no bootstrap contacts to ping")
            ping_result = yield _ping_contacts(bootstrap_contacts)
            shortlist = ping_result.keys()
            if not shortlist:
                log.warning("failed to ping %i bootstrap contacts", len(bootstrap_contacts))
                defer.returnValue(None)
            else:
                # find the closest peers to us
                closest = yield self._iterativeFind(self.node_id, shortlist)
                yield _ping_contacts(closest)
                # query random hashes in our bucket key ranges to fill or split them
                random_ids_in_range = self._routingTable.getRefreshList(force=True)
                while random_ids_in_range:
                    yield self.iterativeFindNode(random_ids_in_range.pop())
                defer.returnValue(None)

        @defer.inlineCallbacks
        def _iterative_join(joined_d=None, last_buckets_with_contacts=None):
            log.info("Attempting to join the DHT network, %i contacts known so far", len(self.contacts))
            joined_d = joined_d or defer.Deferred()
            yield _initialize_routing()
            buckets_with_contacts = self.bucketsWithContacts()
            if last_buckets_with_contacts and last_buckets_with_contacts == buckets_with_contacts:
                if not joined_d.called:
                    joined_d.callback(True)
            elif buckets_with_contacts < 4:
                self.reactor_callLater(1, _iterative_join, joined_d, buckets_with_contacts)
            elif not joined_d.called:
                joined_d.callback(None)
            yield joined_d
            if not self._join_deferred.called:
                self._join_deferred.callback(True)
            defer.returnValue(None)

        yield _iterative_join()

    @defer.inlineCallbacks
    def start(self, known_node_addresses=None):
        """ Causes the Node to attempt to join the DHT network by contacting the
        known DHT nodes. This can be called multiple times if the previous attempt
        has failed or if the Node has lost all the contacts.

        @param known_node_addresses: A sequence of tuples containing IP address
                                   information for existing nodes on the
                                   Kademlia network, in the format:
                                   C{(<ip address>, (udp port>)}
        @type known_node_addresses: list
        """

        self.start_listening()
        yield self._protocol._listening
        # TODO: Refresh all k-buckets further away than this node's closest neighbour
        yield self.joinNetwork(known_node_addresses or [])

        self.safe_start_looping_call(self._change_token_lc, constants.tokenSecretChangeInterval)
        # Start refreshing k-buckets periodically, if necessary
        self.safe_start_looping_call(self._refresh_node_lc, constants.checkRefreshInterval)

    @property
    def contacts(self):
        def _inner():
            for i in range(len(self._routingTable._buckets)):
                for contact in self._routingTable._buckets[i]._contacts:
                    yield contact
        return list(_inner())

    def hasContacts(self):
        for bucket in self._routingTable._buckets:
            if bucket._contacts:
                return True
        return False

    def bucketsWithContacts(self):
        return self._routingTable.bucketsWithContacts()

    @defer.inlineCallbacks
    def announceHaveBlob(self, blob_hash):
        known_nodes = {}
        contacts = yield self.iterativeFindNode(blob_hash)
        # store locally if we're the closest node and there are less than k contacts to try storing to
        if self.externalIP is not None and contacts and len(contacts) < constants.k:
            is_closer = Distance(blob_hash).is_closer(self.node_id, contacts[-1].id)
            if is_closer:
                contacts.pop()
                self_contact = self.contact_manager.make_contact(self.node_id, self.externalIP,
                                                                 self.port, self._protocol)
                token = self.make_token(self_contact.compact_ip())
                yield self.store(self_contact, blob_hash, token, self.peerPort)
        elif self.externalIP is not None:
            pass
        else:
            raise Exception("Cannot determine external IP: %s" % self.externalIP)

        contacted = []

        @defer.inlineCallbacks
        def announce_to_contact(contact):
            known_nodes[contact.id] = contact
            try:
                responseMsg, originAddress = yield contact.findValue(blob_hash, rawResponse=True)
                res = yield contact.store(blob_hash, responseMsg.response['token'], self.peerPort)
                if res != "OK":
                    raise ValueError(res)
                contacted.append(contact)
                log.debug("Stored %s to %s (%s)", blob_hash.encode('hex'), contact.id.encode('hex'), originAddress[0])
            except protocol.TimeoutError:
                log.debug("Timeout while storing blob_hash %s at %s",
                          blob_hash.encode('hex')[:16], contact.log_id())
            except ValueError as err:
                log.error("Unexpected response: %s" % err.message)
            except Exception as err:
                log.error("Unexpected error while storing blob_hash %s at %s: %s",
                          binascii.hexlify(blob_hash), contact, err)

        dl = []
        for c in contacts:
            dl.append(announce_to_contact(c))

        yield defer.DeferredList(dl)

        log.debug("Stored %s to %i of %i attempted peers", blob_hash.encode('hex')[:16],
                  len(contacted), len(contacts))

        contacted_node_ids = [c.id.encode('hex') for c in contacted]
        defer.returnValue(contacted_node_ids)

    def change_token(self):
        self.old_token_secret = self.token_secret
        self.token_secret = self._generateID()

    def make_token(self, compact_ip):
        h = hashlib.new('sha384')
        h.update(self.token_secret + compact_ip)
        return h.digest()

    def verify_token(self, token, compact_ip):
        h = hashlib.new('sha384')
        h.update(self.token_secret + compact_ip)
        if not token == h.digest():
            h = hashlib.new('sha384')
            h.update(self.old_token_secret + compact_ip)
            if not token == h.digest():
                return False
        return True

    def iterativeFindNode(self, key):
        """ The basic Kademlia node lookup operation

        Call this to find a remote node in the P2P overlay network.

        @param key: the n-bit key (i.e. the node or value ID) to search for
        @type key: str

        @return: This immediately returns a deferred object, which will return
                 a list of k "closest" contacts (C{kademlia.contact.Contact}
                 objects) to the specified key as soon as the operation is
                 finished.
        @rtype: twisted.internet.defer.Deferred
        """
        return self._iterativeFind(key)

    @defer.inlineCallbacks
    def iterativeFindValue(self, key):
        """ The Kademlia search operation (deterministic)

        Call this to retrieve data from the DHT.

        @param key: the n-bit key (i.e. the value ID) to search for
        @type key: str

        @return: This immediately returns a deferred object, which will return
                 either one of two things:
                     - If the value was found, it will return a Python
                     dictionary containing the searched-for key (the C{key}
                     parameter passed to this method), and its associated
                     value, in the format:
                     C{<str>key: <str>data_value}
                     - If the value was not found, it will return a list of k
                     "closest" contacts (C{kademlia.contact.Contact} objects)
                     to the specified key
        @rtype: twisted.internet.defer.Deferred
        """

        if len(key) != constants.key_bits / 8:
            raise ValueError("invalid key length!")

        # Execute the search
        find_result = yield self._iterativeFind(key, rpc='findValue')
        if isinstance(find_result, dict):
            # We have found the value; now see who was the closest contact without it...
            # ...and store the key/value pair
            pass
        else:
            # The value wasn't found, but a list of contacts was returned
            # Now, see if we have the value (it might seem wasteful to search on the network
            # first, but it ensures that all values are properly propagated through the
            # network
            if self._dataStore.hasPeersForBlob(key):
                # Ok, we have the value locally, so use that
                # Send this value to the closest node without it
                peers = self._dataStore.getPeersForBlob(key)
                find_result = {key: peers}
            else:
                pass

        expanded_peers = []
        if find_result:
            if key in find_result:
                for peer in find_result[key]:
                    expanded = expand_peer(peer)
                    if expanded not in expanded_peers:
                        expanded_peers.append(expanded)
            # TODO: get this working
            # if 'closestNodeNoValue' in find_result:
            #     closest_node_without_value = find_result['closestNodeNoValue']
            #     try:
            #         response, address = yield closest_node_without_value.findValue(key, rawResponse=True)
            #         yield closest_node_without_value.store(key, response.response['token'], self.peerPort)
            #     except TimeoutError:
            #         pass
        defer.returnValue(expanded_peers)

    def addContact(self, contact):
        """ Add/update the given contact; simple wrapper for the same method
        in this object's RoutingTable object

        @param contact: The contact to add to this node's k-buckets
        @type contact: kademlia.contact.Contact
        """
        return self._routingTable.addContact(contact)

    def removeContact(self, contact):
        """ Remove the contact with the specified node ID from this node's
        table of known nodes. This is a simple wrapper for the same method
        in this object's RoutingTable object

        @param contact: The Contact object to remove
        @type contact: _Contact
        """
        self._routingTable.removeContact(contact)

    def findContact(self, contactID):
        """ Find a entangled.kademlia.contact.Contact object for the specified
        cotact ID

        @param contactID: The contact ID of the required Contact object
        @type contactID: str

        @return: Contact object of remote node with the specified node ID,
                 or None if the contact was not found
        @rtype: twisted.internet.defer.Deferred
        """
        try:
            contact = self._routingTable.getContact(contactID)
            df = defer.Deferred()
            df.callback(contact)
        except (ValueError, IndexError):
            def parseResults(nodes):
                node_ids = [c.id for c in nodes]
                if contactID in nodes:
                    contact = nodes[node_ids.index(contactID)]
                    return contact
                else:
                    return None

            df = self.iterativeFindNode(contactID)
            df.addCallback(parseResults)
        return df

    @rpcmethod
    def ping(self):
        """ Used to verify contact between two Kademlia nodes

        @rtype: str
        """
        return 'pong'

    @rpcmethod
    def store(self, rpc_contact, blob_hash, token, port, originalPublisherID=None, age=0):
        """ Store the received data in this node's local datastore

        @param blob_hash: The hash of the data
        @type blob_hash: str

        @param token: The token we previously returned when this contact sent us a findValue
        @type token: str

        @param port: The TCP port the contact is listening on for requests for this blob (the peerPort)
        @type port: int

        @param originalPublisherID: The node ID of the node that is the publisher of the data
        @type originalPublisherID: str

        @param age: The relative age of the data (time in seconds since it was
                    originally published). Note that the original publish time
                    isn't actually given, to compensate for clock skew between
                    different nodes.
        @type age: int

        @rtype: str
        """

        if originalPublisherID is None:
            originalPublisherID = rpc_contact.id
        compact_ip = rpc_contact.compact_ip()
        if not self.verify_token(token, compact_ip):
            raise ValueError("Invalid token")
        if 0 <= port <= 65536:
            compact_port = str(struct.pack('>H', port))
        else:
            raise TypeError('Invalid port')
        compact_address = compact_ip + compact_port + rpc_contact.id
        now = int(self.clock.seconds())
        originallyPublished = now - age
        self._dataStore.addPeerToBlob(rpc_contact, blob_hash, compact_address, now, originallyPublished,
                                      originalPublisherID)
        return 'OK'

    @rpcmethod
    def findNode(self, rpc_contact, key):
        """ Finds a number of known nodes closest to the node/value with the
        specified key.

        @param key: the n-bit key (i.e. the node or value ID) to search for
        @type key: str

        @return: A list of contact triples closest to the specified key.
                 This method will return C{k} (or C{count}, if specified)
                 contacts if at all possible; it will only return fewer if the
                 node is returning all of the contacts that it knows of.
        @rtype: list
        """
        if len(key) != constants.key_bits / 8:
            raise ValueError("invalid contact id length: %i" % len(key))

        contacts = self._routingTable.findCloseNodes(key, constants.k, rpc_contact.id)
        contact_triples = []
        for contact in contacts:
            contact_triples.append((contact.id, contact.address, contact.port))
        return contact_triples

    @rpcmethod
    def findValue(self, rpc_contact, key):
        """ Return the value associated with the specified key if present in
        this node's data, otherwise execute FIND_NODE for the key

        @param key: The hashtable key of the data to return
        @type key: str

        @return: A dictionary containing the requested key/value pair,
                 or a list of contact triples closest to the requested key.
        @rtype: dict or list
        """

        if len(key) != constants.key_bits / 8:
            raise ValueError("invalid blob hash length: %i" % len(key))

        response = {
            'token': self.make_token(rpc_contact.compact_ip()),
        }

        if self._dataStore.hasPeersForBlob(key):
            response[key] = self._dataStore.getPeersForBlob(key)
        else:
            response['contacts'] = self.findNode(rpc_contact, key)
        return response

    def _generateID(self):
        """ Generates an n-bit pseudo-random identifier

        @return: A globally unique n-bit pseudo-random identifier
        @rtype: str
        """
        return generate_id()

    @defer.inlineCallbacks
    def _iterativeFind(self, key, startupShortlist=None, rpc='findNode'):
        """ The basic Kademlia iterative lookup operation (for nodes/values)

        This builds a list of k "closest" contacts through iterative use of
        the "FIND_NODE" RPC, or if C{findValue} is set to C{True}, using the
        "FIND_VALUE" RPC, in which case the value (if found) may be returned
        instead of a list of contacts

        @param key: the n-bit key (i.e. the node or value ID) to search for
        @type key: str
        @param startupShortlist: A list of contacts to use as the starting
                                 shortlist for this search; this is normally
                                 only used when the node joins the network
        @type startupShortlist: list
        @param rpc: The name of the RPC to issue to remote nodes during the
                    Kademlia lookup operation (e.g. this sets whether this
                    algorithm should search for a data value (if
                    rpc='findValue') or not. It can thus be used to perform
                    other operations that piggy-back on the basic Kademlia
                    lookup operation (Entangled's "delete" RPC, for instance).
        @type rpc: str

        @return: If C{findValue} is C{True}, the algorithm will stop as soon
                 as a data value for C{key} is found, and return a dictionary
                 containing the key and the found value. Otherwise, it will
                 return a list of the k closest nodes to the specified key
        @rtype: twisted.internet.defer.Deferred
        """

        if len(key) != constants.key_bits / 8:
            raise ValueError("invalid key length: %i" % len(key))

        if startupShortlist is None:
            shortlist = self._routingTable.findCloseNodes(key, constants.k)
            # if key != self.node_id:
            #     # Update the "last accessed" timestamp for the appropriate k-bucket
            #     self._routingTable.touchKBucket(key)
            if len(shortlist) == 0:
                log.warning("This node doesnt know any other nodes")
                # This node doesn't know of any other nodes
                fakeDf = defer.Deferred()
                fakeDf.callback([])
                result = yield fakeDf
                defer.returnValue(result)
        else:
            # This is used during the bootstrap process
            shortlist = startupShortlist

        result = yield iterativeFind(self, shortlist, key, rpc)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def _refreshNode(self):
        """ Periodically called to perform k-bucket refreshes and data
        replication/republishing as necessary """
        yield self._refreshRoutingTable()
        self._dataStore.removeExpiredPeers()
        yield self._refreshStoringPeers()
        defer.returnValue(None)

    def _refreshContacts(self):
        return defer.DeferredList(
            [contact.ping() for contact in self.contacts], consumeErrors=True
        )

    def _refreshStoringPeers(self):
        storing_contacts = self._dataStore.getStoringContacts()
        return defer.DeferredList(
            [self._protocol._ping_queue.enqueue_maybe_ping(contact) for contact in storing_contacts],
            consumeErrors=True
        )

    @defer.inlineCallbacks
    def _refreshRoutingTable(self):
        nodeIDs = self._routingTable.getRefreshList(0, True)
        yield self._refreshContacts()
        while nodeIDs:
            searchID = nodeIDs.pop()
            yield self.iterativeFindNode(searchID)
        defer.returnValue(None)
