import binascii
import hashlib
import logging
from functools import reduce

from twisted.internet import defer, error, task

from lbrynet.core.utils import generate_id, DeferredDict
from lbrynet.core.call_later_manager import CallLaterManager
from lbrynet.core.PeerManager import PeerManager
from .error import TimeoutError
from . import constants
from . import routingtable
from . import datastore
from . import protocol
from .peerfinder import DHTPeerFinder
from .contact import ContactManager
from .iterativefind import iterativeFind

log = logging.getLogger(__name__)


def rpcmethod(func):
    """ Decorator to expose Node methods as remote procedure calls

    Apply this decorator to methods in the Node class (or a subclass) in order
    to make them remotely callable via the DHT's RPC mechanism.
    """
    func.rpcmethod = True
    return func


class MockKademliaHelper:
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
                 peer_manager=None, interface='', externalUDPPort=None):
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

        super().__init__(clock, callLater, resolve, listenUDP)
        self.node_id = node_id or self._generateID()
        self.port = udpPort
        self._listen_interface = interface
        self._change_token_lc = self.get_looping_call(self.change_token)
        self._refresh_node_lc = self.get_looping_call(self._refreshNode)
        self._refresh_contacts_lc = self.get_looping_call(self._refreshContacts)

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
        self.externalUDPPort = externalUDPPort or self.port
        self._dataStore = dataStore or datastore.DictDataStore(self.clock.seconds)
        self.peer_manager = peer_manager or PeerManager()
        self.peer_finder = peer_finder or DHTPeerFinder(self, self.peer_manager)
        self._join_deferred = None

    #def __del__(self):
    #    log.warning("unclean shutdown of the dht node")
    #    if hasattr(self, "_listeningPort") and self._listeningPort is not None:
    #        self._listeningPort.stopListening()

    def __str__(self):
        return '<%s.%s object; ID: %s, IP address: %s, UDP port: %d>' % (
            self.__module__, self.__class__.__name__, binascii.hexlify(self.node_id), self.externalIP, self.port)

    @defer.inlineCallbacks
    def stop(self):
        # stop LoopingCalls:
        yield self.safe_stop_looping_call(self._refresh_node_lc)
        yield self.safe_stop_looping_call(self._change_token_lc)
        yield self.safe_stop_looping_call(self._refresh_contacts_lc)
        if self._listeningPort is not None:
            yield self._listeningPort.stopListening()
        self._listeningPort = None

    def start_listening(self):
        if not self._listeningPort:
            try:
                self._listeningPort = self.reactor_listenUDP(self.port, self._protocol,
                                                             interface=self._listen_interface)
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
            if (self.externalIP, self.port) in known_node_resolution.values():
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
            for (host, port), ip_address in known_node_resolution.items():
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
            shortlist = list(ping_result.keys())
            if not shortlist:
                log.warning("failed to ping %i bootstrap contacts", len(bootstrap_contacts))
                defer.returnValue(None)
            else:
                # find the closest peers to us
                closest = yield self._iterativeFind(self.node_id, shortlist if not self.contacts else None)
                yield _ping_contacts(closest)
                # # query random hashes in our bucket key ranges to fill or split them
                # random_ids_in_range = self._routingTable.getRefreshList()
                # while random_ids_in_range:
                #     yield self.iterativeFindNode(random_ids_in_range.pop())
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
                self.reactor_callLater(0, _iterative_join, joined_d, buckets_with_contacts)
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
        self.start_looping_calls()

    def start_looping_calls(self):
        self.safe_start_looping_call(self._change_token_lc, constants.tokenSecretChangeInterval)
        # Start refreshing k-buckets periodically, if necessary
        self.safe_start_looping_call(self._refresh_node_lc, constants.checkRefreshInterval)
        self.safe_start_looping_call(self._refresh_contacts_lc, 60)

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
    def storeToContact(self, blob_hash, contact):
        try:
            if not contact.token:
                yield contact.findValue(blob_hash)
            res = yield contact.store(blob_hash, contact.token, self.peerPort, self.node_id, 0)
            if res != b"OK":
                raise ValueError(res)
            log.debug("Stored %s to %s (%s)", binascii.hexlify(blob_hash), contact.log_id(), contact.address)
            return True
        except protocol.TimeoutError:
            log.debug("Timeout while storing blob_hash %s at %s",
                      binascii.hexlify(blob_hash), contact.log_id())
        except ValueError as err:
            log.error("Unexpected response: %s" % err)
        except Exception as err:
            if 'Invalid token' in str(err):
                contact.update_token(None)
            log.error("Unexpected error while storing blob_hash %s at %s: %s",
                      binascii.hexlify(blob_hash), contact, err)
        return False

    @defer.inlineCallbacks
    def announceHaveBlob(self, blob_hash):
        contacts = yield self.iterativeFindNode(blob_hash)

        if not self.externalIP:
            raise Exception("Cannot determine external IP: %s" % self.externalIP)
        stored_to = yield DeferredDict({contact: self.storeToContact(blob_hash, contact) for contact in contacts})
        contacted_node_ids = [binascii.hexlify(contact.id) for contact in stored_to.keys() if stored_to[contact]]
        log.debug("Stored %s to %i of %i attempted peers", binascii.hexlify(blob_hash),
                  len(contacted_node_ids), len(contacts))
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
        if self.old_token_secret and not token == h.digest(): # TODO: why should we be accepting the previous token?
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
    def iterativeFindValue(self, key, exclude=None):
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

        if len(key) != constants.key_bits // 8:
            raise ValueError("invalid key length!")

        # Execute the search
        find_result = yield self._iterativeFind(key, rpc='findValue', exclude=exclude)
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

        defer.returnValue(list(set(find_result.get(key, []) if find_result else [])))
        # TODO: get this working
        # if 'closestNodeNoValue' in find_result:
        #     closest_node_without_value = find_result['closestNodeNoValue']
        #     try:
        #         response, address = yield closest_node_without_value.findValue(key, rawResponse=True)
        #         yield closest_node_without_value.store(key, response.response['token'], self.peerPort)
        #     except TimeoutError:
        #         pass

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
            df = defer.succeed(self._routingTable.getContact(contactID))
        except (ValueError, IndexError):
            df = self.iterativeFindNode(contactID)
            df.addCallback(lambda nodes: ([node for node in nodes if node.id == contactID] or (None,))[0])
        return df

    @rpcmethod
    def ping(self):
        """ Used to verify contact between two Kademlia nodes

        @rtype: str
        """
        return b'pong'

    @rpcmethod
    def store(self, rpc_contact, blob_hash, token, port, originalPublisherID, age):
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
        if self.clock.seconds() - self._protocol.started_listening_time < constants.tokenSecretChangeInterval:
            pass
        elif not self.verify_token(token, compact_ip):
            raise ValueError("Invalid token")
        if 0 <= port <= 65536:
            compact_port = port.to_bytes(2, 'big')
        else:
            raise TypeError(f'Invalid port: {port}')
        compact_address = compact_ip + compact_port + rpc_contact.id
        now = int(self.clock.seconds())
        originallyPublished = now - age
        self._dataStore.addPeerToBlob(rpc_contact, blob_hash, compact_address, now, originallyPublished,
                                      originalPublisherID)
        return b'OK'

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
        if len(key) != constants.key_bits // 8:
            raise ValueError("invalid contact id length: %i" % len(key))

        contacts = self._routingTable.findCloseNodes(key, sender_node_id=rpc_contact.id)
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

        if len(key) != constants.key_bits // 8:
            raise ValueError("invalid blob hash length: %i" % len(key))

        response = {
            b'token': self.make_token(rpc_contact.compact_ip()),
        }

        if self._protocol._protocolVersion:
            response[b'protocolVersion'] = self._protocol._protocolVersion

        # get peers we have stored for this blob
        has_other_peers = self._dataStore.hasPeersForBlob(key)
        peers = []
        if has_other_peers:
            peers.extend(self._dataStore.getPeersForBlob(key))

        # if we don't have k storing peers to return and we have this hash locally, include our contact information
        if len(peers) < constants.k and key in self._dataStore.completed_blobs:
            compact_ip = reduce(lambda buff, x: buff + bytearray([int(x)]), self.externalIP.split('.'), bytearray())
            compact_port = self.peerPort.to_bytes(2, 'big')
            compact_address = compact_ip + compact_port + self.node_id
            peers.append(compact_address)

        if peers:
            response[key] = peers
        else:
            response[b'contacts'] = self.findNode(rpc_contact, key)
        return response

    def _generateID(self):
        """ Generates an n-bit pseudo-random identifier

        @return: A globally unique n-bit pseudo-random identifier
        @rtype: str
        """
        return generate_id()

    # from lbrynet.core.utils import profile_deferred
    # @profile_deferred()
    @defer.inlineCallbacks
    def _iterativeFind(self, key, startupShortlist=None, rpc='findNode', exclude=None):
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

        if len(key) != constants.key_bits // 8:
            raise ValueError("invalid key length: %i" % len(key))

        if startupShortlist is None:
            shortlist = self._routingTable.findCloseNodes(key)
            # if key != self.node_id:
            #     # Update the "last accessed" timestamp for the appropriate k-bucket
            #     self._routingTable.touchKBucket(key)
            if len(shortlist) == 0:
                log.warning("This node doesn't know any other nodes")
                # This node doesn't know of any other nodes
                fakeDf = defer.Deferred()
                fakeDf.callback([])
                result = yield fakeDf
                defer.returnValue(result)
        else:
            # This is used during the bootstrap process
            shortlist = startupShortlist

        result = yield iterativeFind(self, shortlist, key, rpc, exclude=exclude)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def _refreshNode(self):
        """ Periodically called to perform k-bucket refreshes and data
        replication/republishing as necessary """
        yield self._refreshRoutingTable()
        self._dataStore.removeExpiredPeers()
        self._refreshStoringPeers()
        defer.returnValue(None)

    def _refreshContacts(self):
        self._protocol._ping_queue.enqueue_maybe_ping(*self.contacts, delay=0)

    def _refreshStoringPeers(self):
        self._protocol._ping_queue.enqueue_maybe_ping(*self._dataStore.getStoringContacts(), delay=0)

    @defer.inlineCallbacks
    def _refreshRoutingTable(self):
        nodeIDs = self._routingTable.getRefreshList(0, False)
        while nodeIDs:
            searchID = nodeIDs.pop()
            yield self.iterativeFindNode(searchID)
        defer.returnValue(None)
