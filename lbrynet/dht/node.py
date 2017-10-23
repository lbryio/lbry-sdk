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
import operator
import struct
import time
from twisted.internet import defer, error, reactor, task

import constants
import routingtable
import datastore
import protocol

from contact import Contact
from hashwatcher import HashWatcher
from distance import Distance

import logging
from lbrynet.core.utils import generate_id

log = logging.getLogger(__name__)


def rpcmethod(func):
    """ Decorator to expose Node methods as remote procedure calls

    Apply this decorator to methods in the Node class (or a subclass) in order
    to make them remotely callable via the DHT's RPC mechanism.
    """
    func.rpcmethod = True
    return func


class Node(object):
    """ Local node in the Kademlia network

    This class represents a single local node in a Kademlia network; in other
    words, this class encapsulates an Entangled-using application's "presence"
    in a Kademlia network.

    In Entangled, all interactions with the Kademlia network by a client
    application is performed via this class (or a subclass).
    """

    def __init__(self, node_id=None, udpPort=4000, dataStore=None,
                 routingTableClass=None, networkProtocol=None,
                 externalIP=None, peerPort=None):
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
        self.node_id = node_id or self._generateID()
        self.port = udpPort
        self._listeningPort = None  # object implementing Twisted
        # IListeningPort This will contain a deferred created when
        # joining the network, to enable publishing/retrieving
        # information from the DHT as soon as the node is part of the
        # network (add callbacks to this deferred if scheduling such
        # operations before the node has finished joining the network)
        self._joinDeferred = None
        self.change_token_lc = task.LoopingCall(self.change_token)
        self.refresh_node_lc = task.LoopingCall(self._refreshNode)
        # Create k-buckets (for storing contacts)
        if routingTableClass is None:
            self._routingTable = routingtable.OptimizedTreeRoutingTable(self.node_id)
        else:
            self._routingTable = routingTableClass(self.node_id)

        # Initialize this node's network access mechanisms
        if networkProtocol is None:
            self._protocol = protocol.KademliaProtocol(self)
        else:
            self._protocol = networkProtocol
        # Initialize the data storage mechanism used by this node
        self.token_secret = self._generateID()
        self.old_token_secret = None
        if dataStore is None:
            self._dataStore = datastore.DictDataStore()
        else:
            self._dataStore = dataStore
            # Try to restore the node's state...
            if 'nodeState' in self._dataStore:
                state = self._dataStore['nodeState']
                self.node_id = state['id']
                for contactTriple in state['closestNodes']:
                    contact = Contact(
                        contactTriple[0], contactTriple[1], contactTriple[2], self._protocol)
                    self._routingTable.addContact(contact)
        self.externalIP = externalIP
        self.peerPort = peerPort
        self.hash_watcher = HashWatcher()

    def __del__(self):
        if self._listeningPort is not None:
            self._listeningPort.stopListening()

    def stop(self):
        # stop LoopingCalls:
        if self.refresh_node_lc.running:
            self.refresh_node_lc.stop()
        if self.change_token_lc.running:
            self.change_token_lc.stop()
        if self._listeningPort is not None:
            self._listeningPort.stopListening()
        self.hash_watcher.stop()

    def startNetwork(self):
        """ Causes the Node to start all the underlying components needed for the DHT
        to work. This should be called before any other DHT operations.
        """
        log.info("Starting DHT underlying components")

        # Prepare the underlying Kademlia protocol
        if self.port is not None:
            try:
                self._listeningPort = reactor.listenUDP(self.port, self._protocol)
            except error.CannotListenError as e:
                import traceback
                log.error("Couldn't bind to port %d. %s", self.port, traceback.format_exc())
                raise ValueError("%s lbrynet may already be running." % str(e))

        # Start the token looping call
        self.change_token_lc.start(constants.tokenSecretChangeInterval)
        #        #TODO: Refresh all k-buckets further away than this node's closest neighbour
        # Start refreshing k-buckets periodically, if necessary
        self.next_refresh_call = reactor.callLater(constants.checkRefreshInterval,
                                                   self._refreshNode)
        self.hash_watcher.tick()

    @defer.inlineCallbacks
    def joinNetwork(self, knownNodeAddresses=None):
        """ Causes the Node to attempt to join the DHT network by contacting the
        known DHT nodes. This can be called multiple times if the previous attempt
        has failed or if the Node has lost all the contacts.

        @param knownNodeAddresses: A sequence of tuples containing IP address
                                   information for existing nodes on the
                                   Kademlia network, in the format:
                                   C{(<ip address>, (udp port>)}
        @type knownNodeAddresses: tuple
        """
        log.info("Attempting to join the DHT network")

        # IGNORE:E1101
        # Create temporary contact information for the list of addresses of known nodes
        if knownNodeAddresses != None:
            bootstrapContacts = []
            for address, port in knownNodeAddresses:
                contact = Contact(self._generateID(), address, port, self._protocol)
                bootstrapContacts.append(contact)
        else:
            bootstrapContacts = None

        # Initiate the Kademlia joining sequence - perform a search for this node's own ID
        self._joinDeferred = self._iterativeFind(self.node_id, bootstrapContacts)
        #        #TODO: Refresh all k-buckets further away than this node's closest neighbour
        # Start refreshing k-buckets periodically, if necessary
        self.hash_watcher.tick()
        yield self._joinDeferred
        self.refresh_node_lc.start(constants.checkRefreshInterval)

    @property
    def contacts(self):
        def _inner():
            for i in range(len(self._routingTable._buckets)):
                for contact in self._routingTable._buckets[i]._contacts:
                    yield contact
        return list(_inner())

    def printContacts(self, *args):
        print '\n\nNODE CONTACTS\n==============='
        for i in range(len(self._routingTable._buckets)):
            print "bucket %i" % i
            for contact in self._routingTable._buckets[i]._contacts:
                print "    %s:%i" % (contact.address, contact.port)
        print '=================================='

    def hasContacts(self):
        for bucket in self._routingTable._buckets:
            if bucket._contacts:
                return True
        return False

    def getApproximateTotalDHTNodes(self):
        # get the deepest bucket and the number of contacts in that bucket and multiply it
        # by the number of equivalently deep buckets in the whole DHT to get a really bad
        # estimate!
        bucket = self._routingTable._buckets[self._routingTable._kbucketIndex(self.node_id)]
        num_in_bucket = len(bucket._contacts)
        factor = (2 ** constants.key_bits) / (bucket.rangeMax - bucket.rangeMin)
        return num_in_bucket * factor

    def getApproximateTotalHashes(self):
        # Divide the number of hashes we know about by k to get a really, really, really
        # bad estimate of the average number of hashes per node, then multiply by the
        # approximate number of nodes to get a horrendous estimate of the total number
        # of hashes in the DHT
        num_in_data_store = len(self._dataStore._dict)
        if num_in_data_store == 0:
            return 0
        return num_in_data_store * self.getApproximateTotalDHTNodes() / 8

    def announceHaveBlob(self, key):
        return self.iterativeAnnounceHaveBlob(key, {'port': self.peerPort, 'lbryid': self.node_id})

    @defer.inlineCallbacks
    def getPeersForBlob(self, blob_hash):
        result = yield self.iterativeFindValue(blob_hash)
        expanded_peers = []
        if result:
            if blob_hash in result:
                for peer in result[blob_hash]:
                    host = ".".join([str(ord(d)) for d in peer[:4]])
                    port, = struct.unpack('>H', peer[4:6])
                    if (host, port) not in expanded_peers:
                        expanded_peers.append((host, port))
        defer.returnValue(expanded_peers)

    def get_most_popular_hashes(self, num_to_return):
        return self.hash_watcher.most_popular_hashes(num_to_return)

    def get_bandwidth_stats(self):
        return self._protocol.bandwidth_stats

    def iterativeAnnounceHaveBlob(self, blob_hash, value):
        known_nodes = {}

        def log_error(err, n):
            if err.check(protocol.TimeoutError):
                log.debug(
                    "Timeout while storing blob_hash %s at %s",
                    binascii.hexlify(blob_hash), n)
            else:
                log.error(
                    "Unexpected error while storing blob_hash %s at %s: %s",
                    binascii.hexlify(blob_hash), n, err.getErrorMessage())

        def log_success(res):
            log.debug("Response to store request: %s", str(res))
            return res

        def announce_to_peer(responseTuple):
            """ @type responseMsg: kademlia.msgtypes.ResponseMessage """
            # The "raw response" tuple contains the response message,
            # and the originating address info
            responseMsg = responseTuple[0]
            originAddress = responseTuple[1]  # tuple: (ip adress, udp port)
            # Make sure the responding node is valid, and abort the operation if it isn't
            if not responseMsg.nodeID in known_nodes:
                return responseMsg.nodeID

            n = known_nodes[responseMsg.nodeID]

            result = responseMsg.response
            if 'token' in result:
                value['token'] = result['token']
                d = n.store(blob_hash, value, self.node_id, 0)
                d.addCallback(log_success)
                d.addErrback(log_error, n)
            else:
                d = defer.succeed(False)
            return d

        def requestPeers(contacts):
            if self.externalIP is not None and len(contacts) >= constants.k:
                is_closer = Distance(blob_hash).is_closer(self.node_id, contacts[-1].id)
                if is_closer:
                    contacts.pop()
                    self.store(blob_hash, value, self_store=True, originalPublisherID=self.node_id)
            elif self.externalIP is not None:
                self.store(blob_hash, value, self_store=True, originalPublisherID=self.node_id)
            ds = []
            for contact in contacts:
                known_nodes[contact.id] = contact
                rpcMethod = getattr(contact, "findValue")
                df = rpcMethod(blob_hash, rawResponse=True)
                df.addCallback(announce_to_peer)
                df.addErrback(log_error, contact)
                ds.append(df)
            return defer.DeferredList(ds)

        d = self.iterativeFindNode(blob_hash)
        d.addCallbacks(requestPeers)
        return d

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
        # Prepare a callback for this operation
        outerDf = defer.Deferred()

        def checkResult(result):
            if isinstance(result, dict):
                # We have found the value; now see who was the closest contact without it...
                # ...and store the key/value pair
                outerDf.callback(result)
            else:
                # The value wasn't found, but a list of contacts was returned
                # Now, see if we have the value (it might seem wasteful to search on the network
                # first, but it ensures that all values are properly propagated through the
                # network
                if self._dataStore.hasPeersForBlob(key):
                    # Ok, we have the value locally, so use that
                    peers = self._dataStore.getPeersForBlob(key)
                    # Send this value to the closest node without it
                    outerDf.callback({key: peers})
                else:
                    # Ok, value does not exist in DHT at all
                    outerDf.callback(result)

        # Execute the search
        iterative_find_result = yield self._iterativeFind(key, rpc='findValue')
        checkResult(iterative_find_result)
        result = yield outerDf
        defer.returnValue(result)

    def addContact(self, contact):
        """ Add/update the given contact; simple wrapper for the same method
        in this object's RoutingTable object

        @param contact: The contact to add to this node's k-buckets
        @type contact: kademlia.contact.Contact
        """
        self._routingTable.addContact(contact)

    def removeContact(self, contactID):
        """ Remove the contact with the specified node ID from this node's
        table of known nodes. This is a simple wrapper for the same method
        in this object's RoutingTable object

        @param contactID: The node ID of the contact to remove
        @type contactID: str
        """
        self._routingTable.removeContact(contactID)

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
        except ValueError:
            def parseResults(nodes):
                if contactID in nodes:
                    contact = nodes[nodes.index(contactID)]
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
    def store(self, key, value, originalPublisherID=None, self_store=False, **kwargs):
        """ Store the received data in this node's local hash table

        @param key: The hashtable key of the data
        @type key: str
        @param value: The actual data (the value associated with C{key})
        @type value: str
        @param originalPublisherID: The node ID of the node that is the
                                    B{original} publisher of the data
        @type originalPublisherID: str
        @param age: The relative age of the data (time in seconds since it was
                    originally published). Note that the original publish time
                    isn't actually given, to compensate for clock skew between
                    different nodes.
        @type age: int

        @rtype: str

        @todo: Since the data (value) may be large, passing it around as a buffer
               (which is the case currently) might not be a good idea... will have
               to fix this (perhaps use a stream from the Protocol class?)
        """
        # Get the sender's ID (if any)
        if originalPublisherID is None:
            if '_rpcNodeID' in kwargs:
                originalPublisherID = kwargs['_rpcNodeID']
            else:
                raise TypeError, 'No NodeID given. Therefore we can\'t store this node'

        if self_store is True and self.externalIP:
            contact = Contact(self.node_id, self.externalIP, self.port, None, None)
            compact_ip = contact.compact_ip()
        elif '_rpcNodeContact' in kwargs:
            contact = kwargs['_rpcNodeContact']
            compact_ip = contact.compact_ip()
        else:
            raise TypeError, 'No contact info available'

        if ((self_store is False) and
                ('token' not in value or not self.verify_token(value['token'], compact_ip))):
            raise ValueError('Invalid or missing token')

        if 'port' in value:
            port = int(value['port'])
            if 0 <= port <= 65536:
                compact_port = str(struct.pack('>H', port))
            else:
                raise TypeError, 'Invalid port'
        else:
            raise TypeError, 'No port available'

        if 'lbryid' in value:
            if len(value['lbryid']) != constants.key_bits / 8:
                raise ValueError('Invalid lbryid (%i bytes): %s' % (len(value['lbryid']),
                                                                    value['lbryid'].encode('hex')))
            else:
                compact_address = compact_ip + compact_port + value['lbryid']
        else:
            raise TypeError, 'No lbryid given'

        now = int(time.time())
        originallyPublished = now  # - age
        self._dataStore.addPeerToBlob(key, compact_address, now, originallyPublished,
                                      originalPublisherID)
        return 'OK'

    @rpcmethod
    def findNode(self, key, **kwargs):
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

        # Get the sender's ID (if any)
        if '_rpcNodeID' in kwargs:
            rpc_sender_id = kwargs['_rpcNodeID']
        else:
            rpc_sender_id = None
        contacts = self._routingTable.findCloseNodes(key, constants.k, rpc_sender_id)
        contact_triples = []
        for contact in contacts:
            contact_triples.append((contact.id, contact.address, contact.port))
        return contact_triples

    @rpcmethod
    def findValue(self, key, **kwargs):
        """ Return the value associated with the specified key if present in
        this node's data, otherwise execute FIND_NODE for the key

        @param key: The hashtable key of the data to return
        @type key: str

        @return: A dictionary containing the requested key/value pair,
                 or a list of contact triples closest to the requested key.
        @rtype: dict or list
        """

        if self._dataStore.hasPeersForBlob(key):
            rval = {key: self._dataStore.getPeersForBlob(key)}
        else:
            contact_triples = self.findNode(key, **kwargs)
            rval = {'contacts': contact_triples}
        if '_rpcNodeContact' in kwargs:
            contact = kwargs['_rpcNodeContact']
            compact_ip = contact.compact_ip()
            rval['token'] = self.make_token(compact_ip)
            self.hash_watcher.add_requested_hash(key, contact)
        return rval

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
        findValue = rpc != 'findNode'

        if startupShortlist is None:
            shortlist = self._routingTable.findCloseNodes(key, constants.k)
            if key != self.node_id:
                # Update the "last accessed" timestamp for the appropriate k-bucket
                self._routingTable.touchKBucket(key)
            if len(shortlist) == 0:
                log.warning("This node doesnt know any other nodes")
                # This node doesn't know of any other nodes
                fakeDf = defer.Deferred()
                fakeDf.callback([])
                result = yield fakeDf
                defer.returnValue(result)
        else:
            # This is used during the bootstrap process; node ID's are most probably fake
            shortlist = startupShortlist

        outerDf = defer.Deferred()

        helper = _IterativeFindHelper(self, outerDf, shortlist, key, findValue, rpc)
        # Start the iterations
        helper.searchIteration()
        result = yield outerDf
        defer.returnValue(result)

    @defer.inlineCallbacks
    def _refreshNode(self):
        """ Periodically called to perform k-bucket refreshes and data
        replication/republishing as necessary """

        yield self._refreshRoutingTable()
        self._dataStore.removeExpiredPeers()
        defer.returnValue(None)

    def _refreshRoutingTable(self):
        nodeIDs = self._routingTable.getRefreshList(0, False)
        outerDf = defer.Deferred()

        def searchForNextNodeID(dfResult=None):
            if len(nodeIDs) > 0:
                searchID = nodeIDs.pop()
                df = self.iterativeFindNode(searchID)
                df.addCallback(searchForNextNodeID)
            else:
                # If this is reached, we have finished refreshing the routing table
                outerDf.callback(None)

        # Start the refreshing cycle
        searchForNextNodeID()
        return outerDf


    # args put here because _refreshRoutingTable does outerDF.callback(None)
    def _removeExpiredPeers(self, *args):
        df = threads.deferToThread(self._dataStore.removeExpiredPeers)
        return df


# This was originally a set of nested methods in _iterativeFind
# but they have been moved into this helper class in-order to
# have better scoping and readability
class _IterativeFindHelper(object):
    # TODO: use polymorphism to search for a value or node
    #       instead of using a find_value flag
    def __init__(self, node, outer_d, shortlist, key, find_value, rpc):
        self.node = node
        self.outer_d = outer_d
        self.shortlist = shortlist
        self.key = key
        self.find_value = find_value
        self.rpc = rpc
        # all distance operations in this class only care about the distance
        # to self.key, so this makes it easier to calculate those
        self.distance = Distance(key)
        # List of active queries; len() indicates number of active probes
        #
        # n.b: using lists for these variables, because Python doesn't
        #   allow binding a new value to a name in an enclosing
        #   (non-global) scope
        self.active_probes = []
        # List of contact IDs that have already been queried
        self.already_contacted = []
        # Probes that were active during the previous iteration
        # A list of found and known-to-be-active remote nodes
        self.active_contacts = []
        # This should only contain one entry; the next scheduled iteration call
        self.pending_iteration_calls = []
        self.prev_closest_node = [None]
        self.find_value_result = {}
        self.slow_node_count = [0]

    def extendShortlist(self, responseTuple):
        """ @type responseMsg: kademlia.msgtypes.ResponseMessage """
        # The "raw response" tuple contains the response message,
        # and the originating address info
        responseMsg = responseTuple[0]
        originAddress = responseTuple[1]  # tuple: (ip adress, udp port)
        # Make sure the responding node is valid, and abort the operation if it isn't
        if responseMsg.nodeID in self.active_contacts or responseMsg.nodeID == self.node.node_id:
            return responseMsg.nodeID

        # Mark this node as active
        aContact = self._getActiveContact(responseMsg, originAddress)
        self.active_contacts.append(aContact)

        # This makes sure "bootstrap"-nodes with "fake" IDs don't get queried twice
        if responseMsg.nodeID not in self.already_contacted:
            self.already_contacted.append(responseMsg.nodeID)

        # Now grow extend the (unverified) shortlist with the returned contacts
        result = responseMsg.response
        # TODO: some validation on the result (for guarding against attacks)
        # If we are looking for a value, first see if this result is the value
        # we are looking for before treating it as a list of contact triples
        if self.find_value is True and self.key in result and not 'contacts' in result:
            # We have found the value
            self.find_value_result[self.key] = result[self.key]
        else:
            if self.find_value is True:
                self._setClosestNodeValue(responseMsg, aContact)
            self._keepSearching(result)
        return responseMsg.nodeID

    def _getActiveContact(self, responseMsg, originAddress):
        if responseMsg.nodeID in self.shortlist:
            # Get the contact information from the shortlist...
            return self.shortlist[self.shortlist.index(responseMsg.nodeID)]
        else:
            # If it's not in the shortlist; we probably used a fake ID to reach it
            # - reconstruct the contact, using the real node ID this time
            return Contact(
                responseMsg.nodeID, originAddress[0], originAddress[1], self.node._protocol)

    def _keepSearching(self, result):
        contactTriples = self._getContactTriples(result)
        for contactTriple in contactTriples:
            self._addIfValid(contactTriple)

    def _getContactTriples(self, result):
        if self.find_value is True:
            return result['contacts']
        else:
            return result

    def _setClosestNodeValue(self, responseMsg, aContact):
        # We are looking for a value, and the remote node didn't have it
        # - mark it as the closest "empty" node, if it is
        if 'closestNodeNoValue' in self.find_value_result:
            if self._is_closer(responseMsg):
                self.find_value_result['closestNodeNoValue'] = aContact
        else:
            self.find_value_result['closestNodeNoValue'] = aContact

    def _is_closer(self, responseMsg):
        return self.distance.is_closer(responseMsg.nodeID, self.active_contacts[0].id)

    def _addIfValid(self, contactTriple):
        if isinstance(contactTriple, (list, tuple)) and len(contactTriple) == 3:
            testContact = Contact(
                contactTriple[0], contactTriple[1], contactTriple[2], self.node._protocol)
            if testContact not in self.shortlist:
                self.shortlist.append(testContact)

    def removeFromShortlist(self, failure, deadContactID):
        """ @type failure: twisted.python.failure.Failure """
        failure.trap(protocol.TimeoutError)
        if len(deadContactID) != constants.key_bits / 8:
            raise ValueError("invalid lbry id")
        if deadContactID in self.shortlist:
            self.shortlist.remove(deadContactID)
        return deadContactID

    def cancelActiveProbe(self, contactID):
        self.active_probes.pop()
        if len(self.active_probes) <= constants.alpha / 2 and len(self.pending_iteration_calls):
            # Force the iteration
            self.pending_iteration_calls[0].cancel()
            del self.pending_iteration_calls[0]
            self.searchIteration()

    def sortByDistance(self, contact_list):
        """Sort the list of contacts in order by distance from key"""
        ExpensiveSort(contact_list, self.distance.to_contact).sort()

    # Send parallel, asynchronous FIND_NODE RPCs to the shortlist of contacts
    def searchIteration(self):
        self.slow_node_count[0] = len(self.active_probes)
        # Sort the discovered active nodes from closest to furthest
        self.sortByDistance(self.active_contacts)
        # This makes sure a returning probe doesn't force calling this function by mistake
        while len(self.pending_iteration_calls):
            del self.pending_iteration_calls[0]
        # See if should continue the search
        if self.key in self.find_value_result:
            self.outer_d.callback(self.find_value_result)
            return
        elif len(self.active_contacts) and self.find_value is False:
            if self._is_all_done():
                # TODO: Re-send the FIND_NODEs to all of the k closest nodes not already queried
                #
                # Ok, we're done; either we have accumulated k active
                # contacts or no improvement in closestNode has been
                # noted
                self.outer_d.callback(self.active_contacts)
                return

        # The search continues...
        if len(self.active_contacts):
            self.prev_closest_node[0] = self.active_contacts[0]
        contactedNow = 0
        self.sortByDistance(self.shortlist)
        # Store the current shortList length before contacting other nodes
        prevShortlistLength = len(self.shortlist)
        for contact in self.shortlist:
            if contact.id not in self.already_contacted:
                self._probeContact(contact)
                contactedNow += 1
            if contactedNow == constants.alpha:
                break
        if self._should_lookup_active_calls():
            # Schedule the next iteration if there are any active
            # calls (Kademlia uses loose parallelism)
            call = reactor.callLater(constants.iterativeLookupDelay, self.searchIteration)
            self.pending_iteration_calls.append(call)
        # Check for a quick contact response that made an update to the shortList
        elif prevShortlistLength < len(self.shortlist):
            # Ensure that the closest contacts are taken from the updated shortList
            self.searchIteration()
        else:
            # If no probes were sent, there will not be any improvement, so we're done
            self.outer_d.callback(self.active_contacts)

    def _probeContact(self, contact):
        self.active_probes.append(contact.id)
        rpcMethod = getattr(contact, self.rpc)
        df = rpcMethod(self.key, rawResponse=True)
        df.addCallback(self.extendShortlist)
        df.addErrback(self.removeFromShortlist, contact.id)
        df.addCallback(self.cancelActiveProbe)
        df.addErrback(lambda _: log.exception('Failed to contact %s', contact))
        self.already_contacted.append(contact.id)

    def _should_lookup_active_calls(self):
        return (
            len(self.active_probes) > self.slow_node_count[0] or
            (
                len(self.shortlist) < constants.k and
                len(self.active_contacts) < len(self.shortlist) and
                len(self.active_probes) > 0
            )
        )

    def _is_all_done(self):
        return (
            len(self.active_contacts) >= constants.k or
            (
                self.active_contacts[0] == self.prev_closest_node[0] and
                len(self.active_probes) == self.slow_node_count[0]
            )
        )


class ExpensiveSort(object):
    """Sort a list in place.

    The result of `key(item)` is cached for each item in the `to_sort`
    list as an optimization.  This can be useful when `key` is
    expensive.

    Attributes:
        to_sort: a list of items to sort
        key: callable, like `key` in normal python sort
        attr: the attribute name used to cache the value on each item.
    """

    def __init__(self, to_sort, key, attr='__value'):
        self.to_sort = to_sort
        self.key = key
        self.attr = attr

    def sort(self):
        self._cacheValues()
        self._sortByValue()
        self._removeValue()

    def _cacheValues(self):
        for item in self.to_sort:
            setattr(item, self.attr, self.key(item))

    def _sortByValue(self):
        self.to_sort.sort(key=operator.attrgetter(self.attr))

    def _removeValue(self):
        for item in self.to_sort:
            delattr(item, self.attr)
