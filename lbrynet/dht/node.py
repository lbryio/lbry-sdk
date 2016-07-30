#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive
#
# The docstrings in this module contain epytext markup; API documentation
# may be created by processing this file with epydoc: http://epydoc.sf.net

import hashlib, random, struct, time, math, binascii
import argparse
from twisted.internet import defer, error
import constants
import routingtable
import datastore
import protocol
import twisted.internet.reactor
import twisted.internet.threads
import twisted.python.log
from contact import Contact
from hashwatcher import HashWatcher
import logging


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
    def __init__(self, id=None, udpPort=4000, dataStore=None, routingTableClass=None, networkProtocol=None, lbryid=None, externalIP=None):
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
        """
        if id != None:
            self.id = id
        else:
            self.id = self._generateID()
        self.lbryid = lbryid
        self.port = udpPort
        self._listeningPort = None # object implementing Twisted IListeningPort
        # This will contain a deferred created when joining the network, to enable publishing/retrieving information from
        # the DHT as soon as the node is part of the network (add callbacks to this deferred if scheduling such operations
        # before the node has finished joining the network)
        self._joinDeferred = None
        self.next_refresh_call = None
        self.next_change_token_call = None
        # Create k-buckets (for storing contacts)
        #self._buckets = []
        #for i in range(160):
        #    self._buckets.append(kbucket.KBucket())
        if routingTableClass == None:
            self._routingTable = routingtable.OptimizedTreeRoutingTable(self.id)
        else:
            self._routingTable = routingTableClass(self.id)

        # Initialize this node's network access mechanisms
        if networkProtocol == None:
            self._protocol = protocol.KademliaProtocol(self)
        else:
            self._protocol = networkProtocol
        # Initialize the data storage mechanism used by this node
        self.token_secret = self._generateID()
        self.old_token_secret = None
        self.change_token()
        if dataStore == None:
            self._dataStore = datastore.DictDataStore()
        else:
            self._dataStore = dataStore
            # Try to restore the node's state...
            if 'nodeState' in self._dataStore:
                state = self._dataStore['nodeState']
                self.id = state['id']
                for contactTriple in state['closestNodes']:
                    contact = Contact(contactTriple[0], contactTriple[1], contactTriple[2], self._protocol)
                    self._routingTable.addContact(contact)
        self.externalIP = externalIP
        self.hash_watcher = HashWatcher()

    def __del__(self):
        #self._persistState()
        if self._listeningPort is not None:
            self._listeningPort.stopListening()

    def stop(self):
        #cancel callLaters:
        if self.next_refresh_call is not None:
            self.next_refresh_call.cancel()
            self.next_refresh_call = None
        if self.next_change_token_call is not None:
            self.next_change_token_call.cancel()
            self.next_change_token_call = None
        if self._listeningPort is not None:
            self._listeningPort.stopListening()
        self.hash_watcher.stop()


    def joinNetwork(self, knownNodeAddresses=None):
        """ Causes the Node to join the Kademlia network; normally, this
        should be called before any other DHT operations.
        
        @param knownNodeAddresses: A sequence of tuples containing IP address
                                   information for existing nodes on the
                                   Kademlia network, in the format:
                                   C{(<ip address>, (udp port>)}
        @type knownNodeAddresses: tuple
        """
        # Prepare the underlying Kademlia protocol
        if self.port is not None:
            try:
                self._listeningPort = twisted.internet.reactor.listenUDP(self.port, self._protocol)
            except error.CannotListenError as e:
                import traceback
                log.error("Couldn't bind to port %d. %s", self.port, traceback.format_exc())
                raise ValueError("%s lbrynet may already be running." % str(e))
        #IGNORE:E1101
        # Create temporary contact information for the list of addresses of known nodes
        if knownNodeAddresses != None:
            bootstrapContacts = []
            for address, port in knownNodeAddresses:
                contact = Contact(self._generateID(), address, port, self._protocol)
                bootstrapContacts.append(contact)
        else:
            bootstrapContacts = None
        # Initiate the Kademlia joining sequence - perform a search for this node's own ID
        self._joinDeferred = self._iterativeFind(self.id, bootstrapContacts)
#        #TODO: Refresh all k-buckets further away than this node's closest neighbour
#        def getBucketAfterNeighbour(*args):
#            for i in range(160):
#                if len(self._buckets[i]) > 0:
#                    return i+1
#            return 160
#        df.addCallback(getBucketAfterNeighbour)
#        df.addCallback(self._refreshKBuckets)
        #protocol.reactor.callLater(10, self.printContacts)
        #self._joinDeferred.addCallback(self._persistState)
        #self._joinDeferred.addCallback(self.printContacts)
        # Start refreshing k-buckets periodically, if necessary
        self.next_refresh_call = twisted.internet.reactor.callLater(constants.checkRefreshInterval, self._refreshNode) #IGNORE:E1101
        self.hash_watcher.tick()
        return self._joinDeferred

    def printContacts(self, *args):
        print '\n\nNODE CONTACTS\n==============='
        for i in range(len(self._routingTable._buckets)):
            for contact in self._routingTable._buckets[i]._contacts:
                print contact
        print '=================================='
        #twisted.internet.reactor.callLater(10, self.printContacts)

    def getApproximateTotalDHTNodes(self):
        # get the deepest bucket and the number of contacts in that bucket and multiply it
        # by the number of equivalently deep buckets in the whole DHT to get a really bad
        # estimate!
        bucket = self._routingTable._buckets[self._routingTable._kbucketIndex(self.id)]
        num_in_bucket = len(bucket._contacts)
        factor = (2**constants.key_bits) / (bucket.rangeMax - bucket.rangeMin)
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

    def announceHaveBlob(self, key, port):
        return self.iterativeAnnounceHaveBlob(key, {'port': port, 'lbryid': self.lbryid})

    def getPeersForBlob(self, blob_hash):

        def expand_and_filter(result):
            expanded_peers = []
            if type(result) == dict:
                if blob_hash in result:
                    for peer in result[blob_hash]:
                        #print peer
                        if self.lbryid != peer[6:]:
                            host = ".".join([str(ord(d)) for d in peer[:4]])
                            if host == "127.0.0.1":
                                if "from_peer" in result:
                                    if result["from_peer"] != "self":
                                        host = result["from_peer"]
                            port, = struct.unpack('>H', peer[4:6])
                            expanded_peers.append((host, port))
            return expanded_peers

        def find_failed(err):
            #print "An exception occurred in the DHT"
            #print err.getErrorMessage()
            return []

        d = self.iterativeFindValue(blob_hash)
        d.addCallbacks(expand_and_filter, find_failed)
        return d

    def get_most_popular_hashes(self, num_to_return):
        return self.hash_watcher.most_popular_hashes(num_to_return)

    def iterativeAnnounceHaveBlob(self, blob_hash, value):

        known_nodes = {}

        def log_error(err, n):
            log.error("error storing blob_hash %s at %s", binascii.hexlify(blob_hash), str(n))
            log.error(err.getErrorMessage())
            log.error(err.getTraceback())

        def log_success(res):
            log.debug("Response to store request: %s", str(res))
            return res

        def announce_to_peer(responseTuple):
            """ @type responseMsg: kademlia.msgtypes.ResponseMessage """
            # The "raw response" tuple contains the response message, and the originating address info
            responseMsg = responseTuple[0]
            originAddress = responseTuple[1] # tuple: (ip adress, udp port)
            # Make sure the responding node is valid, and abort the operation if it isn't
            if not responseMsg.nodeID in known_nodes:
                return responseMsg.nodeID

            n = known_nodes[responseMsg.nodeID]

            result = responseMsg.response
            if 'token' in result:
                #print "Printing result...", result
                value['token'] = result['token']
                d = n.store(blob_hash, value, self.id, 0)
                d.addCallback(log_success)
                d.addErrback(log_error, n)
            else:
                d = defer.succeed(False)
            #else:
            #    print "result:", result
            #    print "No token where it should be"
            return d

        def requestPeers(contacts):
            if self.externalIP is not None and len(contacts) >= constants.k:
                if self._routingTable.distance(blob_hash, self.id) < self._routingTable.distance(blob_hash, contacts[-1].id):
                    contacts.pop()
                    self.store(blob_hash, value, self_store=True, originalPublisherID=self.id)
            elif self.externalIP is not None:
                #print "attempting to self-store"
                self.store(blob_hash, value, self_store=True, originalPublisherID=self.id)
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
        self.next_change_token_call = twisted.internet.reactor.callLater(constants.tokenSecretChangeInterval, self.change_token)

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
                #print 'invalid token found'
                return False
        return True

    # def iterativeStore(self, key, value, originalPublisherID=None, age=0):
    #     """ This is deprecated. Use iterativeAnnounceHaveBlob instead.
    #
    #     The Kademlia store operation
    #
    #     Call this to store/republish data in the DHT.
    #
    #     @param key: The hashtable key of the data
    #     @type key: str
    #     @param value: The actual data (the value associated with C{key})
    #     @type value: str
    #     @param originalPublisherID: The node ID of the node that is the
    #                                 B{original} publisher of the data
    #     @type originalPublisherID: str
    #     @param age: The relative age of the data (time in seconds since it was
    #                 originally published). Note that the original publish time
    #                 isn't actually given, to compensate for clock skew between
    #                 different nodes.
    #     @type age: int
    #     """
    #     #print '      iterativeStore called'
    #     if originalPublisherID == None:
    #         originalPublisherID = self.id
    #
    #     def log_error(err):
    #         log.error(err.getErrorMessage())
    #
    #     # Prepare a callback for doing "STORE" RPC calls
    #     def executeStoreRPCs(nodes):
    #         #print '        .....execStoreRPCs called'
    #         if len(nodes) >= constants.k:
    #             # If this node itself is closer to the key than the last (furthest) node in the list,
    #             # we should store the value at ourselves as well
    #             if self._routingTable.distance(key, self.id) < self._routingTable.distance(key, nodes[-1].id):
    #                 nodes.pop()
    #                 self.store(key, value, originalPublisherID=originalPublisherID, age=age)
    #         else:
    #             self.store(key, value, originalPublisherID=originalPublisherID, age=age)
    #         for contact in nodes:
    #             d = contact.store(key, value, originalPublisherID, age)
    #             d.addErrback(log_error)
    #         return nodes
    #     # Find k nodes closest to the key...
    #     df = self.iterativeFindNode(key)
    #     # ...and send them STORE RPCs as soon as they've been found
    #     df.addCallback(executeStoreRPCs)
    #     return df

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
            if type(result) == dict:
                # We have found the value; now see who was the closest contact without it...
#                if 'closestNodeNoValue' in result:
                    # ...and store the key/value pair
#                    contact = result['closestNodeNoValue']
#                    contact.store(key, result[key])
                outerDf.callback(result)
            else:
                # The value wasn't found, but a list of contacts was returned
                # Now, see if we have the value (it might seem wasteful to search on the network
                # first, but it ensures that all values are properly propagated through the
                # network
                #if key in self._dataStore:
                if self._dataStore.hasPeersForBlob(key):
                    # Ok, we have the value locally, so use that
                    peers = self._dataStore.getPeersForBlob(key)
                    # Send this value to the closest node without it
                    #if len(result) > 0:
                    #    contact = result[0]
                    #    contact.store(key, value)
                    outerDf.callback({key: peers, "from_peer": 'self'})
                else:
                    # Ok, value does not exist in DHT at all
                    outerDf.callback(result)

        # Execute the search
        df = self._iterativeFind(key, rpc='findValue')
        df.addCallback(checkResult)
        return outerDf

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
        if originalPublisherID == None:
            if '_rpcNodeID' in kwargs:
                originalPublisherID = kwargs['_rpcNodeID']
            else:
                raise TypeError, 'No NodeID given. Therefore we can\'t store this node'

        if self_store is True and self.externalIP:
            contact = Contact(self.id, self.externalIP, self.port, None, None)
            compact_ip = contact.compact_ip()
        elif '_rpcNodeContact' in kwargs:
            contact = kwargs['_rpcNodeContact']
            #print contact.address
            compact_ip = contact.compact_ip()
            #print compact_ip
        else:
            return 'Not OK'
            #raise TypeError, 'No contact info available'

        if ((self_store is False) and
            (not 'token' in value or not self.verify_token(value['token'], compact_ip))):
            #if not 'token' in value:
            #    print "Couldn't find token in value"
            #elif not self.verify_token(value['token'], contact.compact_ip()):
            #    print "Token is invalid"
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
            if len(value['lbryid']) > constants.key_bits:
                raise ValueError, 'Invalid lbryid'
            else:
                compact_address = compact_ip + compact_port + value['lbryid']
        else:
            raise TypeError, 'No lbryid given'

        #if originalPublisherID == None:
        #if rpcSenderID != None:
        #    originalPublisherID = rpcSenderID
        #else:
        #    raise TypeError, 'No publisher specifed, and RPC caller ID not available. Data requires an original publisher.'
        #if self_store is True:
        #    print "got this far"
        now = int(time.time())
        originallyPublished = now# - age
        #print compact_address
        self._dataStore.addPeerToBlob(key, compact_address, now, originallyPublished, originalPublisherID)
        #if self_store is True:
        #    print "looks like it was successful maybe"
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
            rpcSenderID = kwargs['_rpcNodeID']
        else:
            rpcSenderID = None
        contacts = self._routingTable.findCloseNodes(key, constants.k, rpcSenderID)
        contactTriples = []
        for contact in contacts:
            contactTriples.append( (contact.id, contact.address, contact.port) )
        return contactTriples

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
            contactTriples = self.findNode(key, **kwargs)
            rval = {'contacts': contactTriples}
        if '_rpcNodeContact' in kwargs:
            contact = kwargs['_rpcNodeContact']
            compact_ip = contact.compact_ip()
            rval['token'] = self.make_token(compact_ip)
            self.hash_watcher.add_requested_hash(key, compact_ip)
        return rval

#    def _distance(self, keyOne, keyTwo):
#        """ Calculate the XOR result between two string variables
#        
#        @return: XOR result of two long variables
#        @rtype: long
#        """
#        valKeyOne = long(keyOne.encode('hex'), 16)
#        valKeyTwo = long(keyTwo.encode('hex'), 16)
#        return valKeyOne ^ valKeyTwo

    def _generateID(self):
        """ Generates an n-bit pseudo-random identifier
        
        @return: A globally unique n-bit pseudo-random identifier
        @rtype: str
        """
        hash = hashlib.sha384()
        hash.update(str(random.getrandbits(255)))
        return hash.digest()

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
        if rpc != 'findNode':
            findValue = True
        else:
            findValue = False
        shortlist = []
        if startupShortlist == None:
            shortlist = self._routingTable.findCloseNodes(key, constants.alpha)
            if key != self.id:
                # Update the "last accessed" timestamp for the appropriate k-bucket
                self._routingTable.touchKBucket(key)
            if len(shortlist) == 0:
                # This node doesn't know of any other nodes
                fakeDf = defer.Deferred()
                fakeDf.callback([])
                return fakeDf
        else:
            # This is used during the bootstrap process; node ID's are most probably fake
            shortlist = startupShortlist

        # List of active queries; len() indicates number of active probes
        # - using lists for these variables, because Python doesn't allow binding a new value to a name in an enclosing (non-global) scope
        activeProbes = []
        # List of contact IDs that have already been queried
        alreadyContacted = []
        # Probes that were active during the previous iteration
        # A list of found and known-to-be-active remote nodes
        activeContacts = []
        # This should only contain one entry; the next scheduled iteration call
        pendingIterationCalls = []
        prevClosestNode = [None]
        findValueResult = {}
        slowNodeCount = [0]

        def extendShortlist(responseTuple):
            """ @type responseMsg: kademlia.msgtypes.ResponseMessage """
            # The "raw response" tuple contains the response message, and the originating address info
            responseMsg = responseTuple[0]
            originAddress = responseTuple[1] # tuple: (ip adress, udp port)
            # Make sure the responding node is valid, and abort the operation if it isn't
            if responseMsg.nodeID in activeContacts or responseMsg.nodeID == self.id:
                return responseMsg.nodeID

            # Mark this node as active
            if responseMsg.nodeID in shortlist:
                # Get the contact information from the shortlist...
                aContact = shortlist[shortlist.index(responseMsg.nodeID)]
            else:
                # If it's not in the shortlist; we probably used a fake ID to reach it
                # - reconstruct the contact, using the real node ID this time
                aContact = Contact(responseMsg.nodeID, originAddress[0], originAddress[1], self._protocol)
            activeContacts.append(aContact)
            # This makes sure "bootstrap"-nodes with "fake" IDs don't get queried twice
            if responseMsg.nodeID not in alreadyContacted:
                alreadyContacted.append(responseMsg.nodeID)
            # Now grow extend the (unverified) shortlist with the returned contacts
            result = responseMsg.response
            #TODO: some validation on the result (for guarding against attacks)
            # If we are looking for a value, first see if this result is the value
            # we are looking for before treating it as a list of contact triples
            if findValue is True and key in result and not 'contacts' in result:
                # We have found the value
                findValueResult[key] = result[key]
                findValueResult['from_peer'] = aContact.address
            else:
                if findValue is True:
                    # We are looking for a value, and the remote node didn't have it
                    # - mark it as the closest "empty" node, if it is
                    if 'closestNodeNoValue' in findValueResult:
                        if self._routingTable.distance(key, responseMsg.nodeID) < self._routingTable.distance(key, activeContacts[0].id):
                            findValueResult['closestNodeNoValue'] = aContact
                    else:
                        findValueResult['closestNodeNoValue'] = aContact
                    contactTriples = result['contacts']
                else:
                    contactTriples = result
                for contactTriple in contactTriples:
                    if isinstance(contactTriple, (list, tuple)) and len(contactTriple) == 3:
                        testContact = Contact(contactTriple[0], contactTriple[1], contactTriple[2], self._protocol)
                        if testContact not in shortlist:
                            shortlist.append(testContact)
            return responseMsg.nodeID

        def removeFromShortlist(failure):
            """ @type failure: twisted.python.failure.Failure """
            failure.trap(protocol.TimeoutError)
            deadContactID = failure.getErrorMessage()
            if deadContactID in shortlist:
                shortlist.remove(deadContactID)
            return deadContactID

        def cancelActiveProbe(contactID):
            activeProbes.pop()
            if len(activeProbes) <= constants.alpha/2 and len(pendingIterationCalls):
                # Force the iteration
                pendingIterationCalls[0].cancel()
                del pendingIterationCalls[0]
                #print 'forcing iteration ================='
                searchIteration()

        def log_error(err):
            log.error(err.getErrorMessage())

        # Send parallel, asynchronous FIND_NODE RPCs to the shortlist of contacts
        def searchIteration():
            #print '==> searchiteration'
            slowNodeCount[0] = len(activeProbes)
            # Sort the discovered active nodes from closest to furthest
            activeContacts.sort(lambda firstContact, secondContact, targetKey=key: cmp(self._routingTable.distance(firstContact.id, targetKey), self._routingTable.distance(secondContact.id, targetKey)))
            # This makes sure a returning probe doesn't force calling this function by mistake
            while len(pendingIterationCalls):
                del pendingIterationCalls[0]
            # See if should continue the search
            if key in findValueResult:
                #print '++++++++++++++ DONE (findValue found) +++++++++++++++\n\n'
                outerDf.callback(findValueResult)
                return
            elif len(activeContacts) and findValue == False:
                if (len(activeContacts) >= constants.k) or (activeContacts[0] == prevClosestNode[0] and len(activeProbes) == slowNodeCount[0]):
                    # TODO: Re-send the FIND_NODEs to all of the k closest nodes not already queried
                    # Ok, we're done; either we have accumulated k active contacts or no improvement in closestNode has been noted
                    #if len(activeContacts) >= constants.k:
                    #    print '++++++++++++++ DONE (test for k active contacts) +++++++++++++++\n\n'
                    #else:
                    #    print '++++++++++++++ DONE (test for closest node) +++++++++++++++\n\n'
                    outerDf.callback(activeContacts)
                    return
            # The search continues...
            if len(activeContacts):
                prevClosestNode[0] = activeContacts[0]
            contactedNow = 0
            shortlist.sort(lambda firstContact, secondContact, targetKey=key: cmp(self._routingTable.distance(firstContact.id, targetKey), self._routingTable.distance(secondContact.id, targetKey)))
            # Store the current shortList length before contacting other nodes
            prevShortlistLength = len(shortlist)
            for contact in shortlist:
                if contact.id not in alreadyContacted:
                    activeProbes.append(contact.id)
                    rpcMethod = getattr(contact, rpc)
                    df = rpcMethod(key, rawResponse=True)
                    df.addCallback(extendShortlist)
                    df.addErrback(removeFromShortlist)
                    df.addCallback(cancelActiveProbe)
                    df.addErrback(log_error)
                    alreadyContacted.append(contact.id)
                    contactedNow += 1
                if contactedNow == constants.alpha:
                    break
            if len(activeProbes) > slowNodeCount[0] \
                or (len(shortlist) < constants.k and len(activeContacts) < len(shortlist) and len(activeProbes) > 0):
                #print '----------- scheduling next call -------------'
                # Schedule the next iteration if there are any active calls (Kademlia uses loose parallelism)
                call = twisted.internet.reactor.callLater(constants.iterativeLookupDelay, searchIteration) #IGNORE:E1101
                pendingIterationCalls.append(call)
            # Check for a quick contact response that made an update to the shortList
            elif prevShortlistLength < len(shortlist):
                # Ensure that the closest contacts are taken from the updated shortList
                searchIteration()
            else:
                #print '++++++++++++++ DONE (logically) +++++++++++++\n\n'
                # If no probes were sent, there will not be any improvement, so we're done
                outerDf.callback(activeContacts)

        outerDf = defer.Deferred()
        # Start the iterations
        searchIteration()
        return outerDf

#    def _kbucketIndex(self, key):
#        """ Calculate the index of the k-bucket which is responsible for the
#        specified key
#
#        @param key: The key for which to find the appropriate k-bucket index
#        @type key: str
#
#        @return: The index of the k-bucket responsible for the specified key
#        @rtype: int
#        """
#        distance = self._distance(self.id, key)
#        bucketIndex = int(math.log(distance, 2))
#        return bucketIndex

#    def _randomIDInBucketRange(self, bucketIndex):
#        """ Returns a random ID in the specified k-bucket's range
#
#        @param bucketIndex: The index of the k-bucket to use
#        @type bucketIndex: int
#        """
#        def makeIDString(distance):
#            id = hex(distance)[2:]
#            if id[-1] == 'L':
#                id = id[:-1]
#            if len(id) % 2 != 0:
#                id = '0' + id
#            id = id.decode('hex')
#            id = (20 - len(id))*'\x00' + id
#            return id
#        min = math.pow(2, bucketIndex)
#        max = math.pow(2, bucketIndex+1)
#        distance = random.randrange(min, max)
#        distanceStr = makeIDString(distance)
#        randomID = makeIDString(self._distance(distanceStr, self.id))
#        return randomID

#    def _refreshKBuckets(self, startIndex=0, force=False):
#        """ Refreshes all k-buckets that need refreshing, starting at the
#        k-bucket with the specified index
#
#        @param startIndex: The index of the bucket to start refreshing at;
#                           this bucket and those further away from it will
#                           be refreshed. For example, when joining the
#                           network, this node will set this to the index of
#                           the bucket after the one containing it's closest
#                           neighbour.
#        @type startIndex: index
#        @param force: If this is C{True}, all buckets (in the specified range)
#                      will be refreshed, regardless of the time they were last
#                      accessed.
#        @type force: bool
#        """
#        #print '_refreshKbuckets called with index:',startIndex
#        bucketIndex = []
#        bucketIndex.append(startIndex + 1)
#        outerDf = defer.Deferred()
#        def refreshNextKBucket(dfResult=None):
#            #print '  refreshNexKbucket called; bucketindex is', bucketIndex[0]
#            bucketIndex[0] += 1
#            while bucketIndex[0] < 160:
#                if force or (int(time.time()) - self._buckets[bucketIndex[0]].lastAccessed >= constants.refreshTimeout):
#                    searchID = self._randomIDInBucketRange(bucketIndex[0])
#                    self._buckets[bucketIndex[0]].lastAccessed = int(time.time())
#                    #print '  refreshing bucket',bucketIndex[0]
#                    df = self.iterativeFindNode(searchID)
#                    df.addCallback(refreshNextKBucket)
#                    return
#                else:
#                    bucketIndex[0] += 1
#            # If this is reached, we have refreshed all the buckets
#            #print '  all buckets refreshed; initiating outer deferred callback'
#            outerDf.callback(None)
#        #print '_refreshKbuckets starting cycle'
#        refreshNextKBucket()
#        #print '_refreshKbuckets returning'
#        return outerDf

    #def _persistState(self, *args):
    #    state = {'id': self.id,
    #             'closestNodes': self.findNode(self.id)}
    #    now = int(time.time())
    #    self._dataStore.setItem('nodeState', state, now, now, self.id)

    def _refreshNode(self):
        """ Periodically called to perform k-bucket refreshes and data
        replication/republishing as necessary """
        #print 'refreshNode called'
        df = self._refreshRoutingTable()
        #df.addCallback(self._republishData)
        df.addCallback(self._removeExpiredPeers)
        df.addCallback(self._scheduleNextNodeRefresh)

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

    #def _republishData(self, *args):
    #    #print '---republishData() called'
    #    df = twisted.internet.threads.deferToThread(self._threadedRepublishData)
    #    return df

    def _scheduleNextNodeRefresh(self, *args):
        #print '==== sheduling next refresh'
        self.next_refresh_call = twisted.internet.reactor.callLater(constants.checkRefreshInterval, self._refreshNode)

    def _removeExpiredPeers(self, *args):#args put here because _refreshRoutingTable does outerDF.callback(None)
        df = twisted.internet.threads.deferToThread(self._dataStore.removeExpiredPeers)
        return df

    #def _threadedRepublishData(self, *args):
    #    """ Republishes and expires any stored data (i.e. stored
    #    C{(key, value pairs)} that need to be republished/expired
    #
    #    This method should run in a deferred thread
    #    """
    #    #print '== republishData called, node:',ord(self.id[0])
    #    expiredKeys = []
    #    for key in self._dataStore:
    #        # Filter internal variables stored in the datastore
    #        if key == 'nodeState':
    #            continue
    #        now = int(time.time())
    #        originalPublisherID = self._dataStore.originalPublisherID(key)
    #        age = now - self._dataStore.originalPublishTime(key)
    #        #print '  node:',ord(self.id[0]),'key:',ord(key[0]),'orig publishing time:',self._dataStore.originalPublishTime(key),'now:',now,'age:',age,'lastPublished age:',now - self._dataStore.lastPublished(key),'original pubID:', ord(originalPublisherID[0])
    #        if originalPublisherID == self.id:
    #            # This node is the original publisher; it has to republish
    #            # the data before it expires (24 hours in basic Kademlia)
    #            if age >= constants.dataExpireTimeout:
    #                #print '    REPUBLISHING key:', key
    #                #self.iterativeStore(key, self._dataStore[key])
    #                twisted.internet.reactor.callFromThread(self.iterativeStore, key, self._dataStore[key])
    #        else:
    #            # This node needs to replicate the data at set intervals,
    #            # until it expires, without changing the metadata associated with it
    #            # First, check if the data has expired
    #            if age >= constants.dataExpireTimeout:
    #                # This key/value pair has expired (and it has not been republished by the original publishing node
    #                # - remove it
    #                expiredKeys.append(key)
    #            elif now - self._dataStore.lastPublished(key) >= constants.replicateInterval:
    #                # ...data has not yet expired, and we need to replicate it
    #                #print '    replicating key:', key,'age:',age
    #                #self.iterativeStore(key=key, value=self._dataStore[key], originalPublisherID=originalPublisherID, age=age)
    #                twisted.internet.reactor.callFromThread(self.iterativeStore, key=key, value=self._dataStore[key], originalPublisherID=originalPublisherID, age=age)
    #    for key in expiredKeys:
    #        #print '    expiring key:', key
    #        del self._dataStore[key]
    #    #print 'done with threadedDataRefresh()'


def main():

    parser = argparse.ArgumentParser(description="Launch a dht node")
    parser.add_argument("udp_port", help="The UDP port on which the node will listen",
                        type=int)
    parser.add_argument("known_node_ip",
                        help="The IP of a known node to be used to bootstrap into the network",
                        nargs='?')
    parser.add_argument("known_node_port",
                        help="The port of a known node to be used to bootstrap into the network",
                        nargs='?', default=4000, type=int)

    args = parser.parse_args()

    if args.known_node_ip:
        known_nodes = [(args.known_node_ip, args.known_node_port)]
    else:
        known_nodes = []

    node = Node(udpPort=args.udp_port)
    node.joinNetwork(known_nodes)
    twisted.internet.reactor.run()

if __name__ == '__main__':
    main()