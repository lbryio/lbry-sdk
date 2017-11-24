from zope.interface import Interface


class IDataStore(Interface):
    """ Interface for classes implementing physical storage (for data
    published via the "STORE" RPC) for the Kademlia DHT

    @note: This provides an interface for a dict-like object
    """

    def keys(self):
        """ Return a list of the keys in this data store """
        pass

    def removeExpiredPeers(self):
        pass

    def hasPeersForBlob(self, key):
        pass

    def addPeerToBlob(self, key, value, lastPublished, originallyPublished, originalPublisherID):
        pass

    def getPeersForBlob(self, key):
        pass

    def removePeer(self, key):
        pass


class IRoutingTable(Interface):
    """ Interface for RPC message translators/formatters

    Classes inheriting from this should provide a suitable routing table for
    a parent Node object (i.e. the local entity in the Kademlia network)
    """

    def __init__(self, parentNodeID):
        """
        @param parentNodeID: The n-bit node ID of the node to which this
                             routing table belongs
        @type parentNodeID: str
        """

    def addContact(self, contact):
        """ Add the given contact to the correct k-bucket; if it already
        exists, its status will be updated

        @param contact: The contact to add to this node's k-buckets
        @type contact: kademlia.contact.Contact
        """

    def findCloseNodes(self, key, count, _rpcNodeID=None):
        """ Finds a number of known nodes closest to the node/value with the
        specified key.

        @param key: the n-bit key (i.e. the node or value ID) to search for
        @type key: str
        @param count: the amount of contacts to return
        @type count: int
        @param _rpcNodeID: Used during RPC, this is be the sender's Node ID
                           Whatever ID is passed in the paramater will get
                           excluded from the list of returned contacts.
        @type _rpcNodeID: str

        @return: A list of node contacts (C{kademlia.contact.Contact instances})
                 closest to the specified key.
                 This method will return C{k} (or C{count}, if specified)
                 contacts if at all possible; it will only return fewer if the
                 node is returning all of the contacts that it knows of.
        @rtype: list
        """

    def getContact(self, contactID):
        """ Returns the (known) contact with the specified node ID

        @raise ValueError: No contact with the specified contact ID is known
                           by this node
        """

    def getRefreshList(self, startIndex=0, force=False):
        """ Finds all k-buckets that need refreshing, starting at the
        k-bucket with the specified index, and returns IDs to be searched for
        in order to refresh those k-buckets

        @param startIndex: The index of the bucket to start refreshing at;
                           this bucket and those further away from it will
                           be refreshed. For example, when joining the
                           network, this node will set this to the index of
                           the bucket after the one containing it's closest
                           neighbour.
        @type startIndex: index
        @param force: If this is C{True}, all buckets (in the specified range)
                      will be refreshed, regardless of the time they were last
                      accessed.
        @type force: bool

        @return: A list of node ID's that the parent node should search for
                 in order to refresh the routing Table
        @rtype: list
        """

    def removeContact(self, contactID):
        """ Remove the contact with the specified node ID from the routing
        table

        @param contactID: The node ID of the contact to remove
        @type contactID: str
        """

    def touchKBucket(self, key):
        """ Update the "last accessed" timestamp of the k-bucket which covers
        the range containing the specified key in the key/ID space

        @param key: A key in the range of the target k-bucket
        @type key: str
        """
