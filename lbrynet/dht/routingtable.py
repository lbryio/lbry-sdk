# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive
#
# The docstrings in this module contain epytext markup; API documentation
# may be created by processing this file with epydoc: http://epydoc.sf.net

import time
import random
from zope.interface import implements
import constants
import kbucket
import protocol
from interface import IRoutingTable
import logging

log = logging.getLogger(__name__)


class TreeRoutingTable(object):
    """ This class implements a routing table used by a Node class.

    The Kademlia routing table is a binary tree whose leaves are k-buckets,
    where each k-bucket contains nodes with some common prefix of their IDs.
    This prefix is the k-bucket's position in the binary tree; it therefore
    covers some range of ID values, and together all of the k-buckets cover
    the entire n-bit ID (or key) space (with no overlap).

    @note: In this implementation, nodes in the tree (the k-buckets) are
    added dynamically, as needed; this technique is described in the 13-page
    version of the Kademlia paper, in section 2.4. It does, however, use the
    C{PING} RPC-based k-bucket eviction algorithm described in section 2.2 of
    that paper.
    """
    implements(IRoutingTable)

    def __init__(self, parentNodeID):
        """
        @param parentNodeID: The n-bit node ID of the node to which this
                             routing table belongs
        @type parentNodeID: str
        """
        # Create the initial (single) k-bucket covering the range of the entire n-bit ID space
        self._buckets = [kbucket.KBucket(rangeMin=0, rangeMax=2 ** constants.key_bits)]
        self._parentNodeID = parentNodeID

    def addContact(self, contact):
        """ Add the given contact to the correct k-bucket; if it already
        exists, its status will be updated

        @param contact: The contact to add to this node's k-buckets
        @type contact: kademlia.contact.Contact
        """
        if contact.id == self._parentNodeID:
            return

        bucketIndex = self._kbucketIndex(contact.id)
        try:
            self._buckets[bucketIndex].addContact(contact)
            log.debug("Added %s", contact.id.encode('hex'))
        except kbucket.BucketFull:
            # The bucket is full; see if it can be split (by checking
            # if its range includes the host node's id)
            if self._buckets[bucketIndex].keyInRange(self._parentNodeID):
                self._splitBucket(bucketIndex)
                log.debug("Split bucket %i", bucketIndex)
                # Retry the insertion attempt
                self.addContact(contact)
            else:
                # We can't split the k-bucket
                # NOTE:
                # In section 2.4 of the 13-page version of the
                # Kademlia paper, it is specified that in this case,
                # the new contact should simply be dropped. However,
                # in section 2.2, it states that the head contact in
                # the k-bucket (i.e. the least-recently seen node)
                # should be pinged - if it does not reply, it should
                # be dropped, and the new contact added to the tail of
                # the k-bucket. This implementation follows section
                # 2.2 regarding this point.

                def replaceContact(failure, deadContactID):
                    """ Callback for the deferred PING RPC to see if the head
                    node in the k-bucket is still responding

                    @type failure: twisted.python.failure.Failure
                    """
                    failure.trap(protocol.TimeoutError)
                    if len(deadContactID) != constants.key_bits / 8:
                        raise ValueError("invalid contact id")
                    log.debug("Replacing dead contact: %s with %s", deadContactID.encode('hex'),
                              contact.id.encode('hex'))
                    try:
                        # Remove the old contact...
                        self._buckets[bucketIndex].removeContact(deadContactID)
                    except ValueError:
                        # The contact has already been removed (probably due to a timeout)
                        pass
                    # ...and add the new one at the tail of the bucket
                    self.addContact(contact)

                def success(result):
                    log.debug("Result: %s, peer doesnt need to be replaced", result)

                log.debug("Cant split bucket, trying to replace")
                # Ping the least-recently seen contact in this k-bucket
                head_contact = self._buckets[bucketIndex]._contacts[0]
                df = head_contact.ping()
                # If there's an error (i.e. timeout), remove the head
                # contact, and append the new one
                df.addCallbacks(success, lambda err: replaceContact(err, head_contact.id))
                df.addErrback(log.exception)

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
        bucketIndex = self._kbucketIndex(key)

        if bucketIndex < len(self._buckets):
            closestNodes = self._buckets[bucketIndex].getContacts(count, _rpcNodeID)
        else:
            closestNodes = []
        # This method must return k contacts (even if we have the node
        # with the specified key as node ID), unless there is less
        # than k remote nodes in the routing table
        i = 1
        canGoLower = bucketIndex - i >= 0
        canGoHigher = bucketIndex + i < len(self._buckets)
        # Fill up the node list to k nodes, starting with the closest neighbouring nodes known
        while len(closestNodes) < min(count, constants.k) and (canGoLower or canGoHigher):
            # TODO: this may need to be optimized
            if canGoLower:
                closestNodes.extend(
                    self._buckets[bucketIndex - i].getContacts(
                        constants.k - len(closestNodes), _rpcNodeID))
                canGoLower = bucketIndex - (i + 1) >= 0
            if canGoHigher:
                closestNodes.extend(
                    self._buckets[bucketIndex + i].getContacts(constants.k - len(closestNodes),
                                                               _rpcNodeID))
                canGoHigher = bucketIndex + (i + 1) < len(self._buckets)
            i += 1
        return closestNodes

    def getContact(self, contactID):
        """ Returns the (known) contact with the specified node ID

        @raise ValueError: No contact with the specified contact ID is known
                           by this node
        """
        bucketIndex = self._kbucketIndex(contactID)
        try:
            contact = self._buckets[bucketIndex].getContact(contactID)
        except ValueError:
            raise
        else:
            return contact

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
        bucketIndex = startIndex
        refreshIDs = []
        for bucket in self._buckets[startIndex:]:
            if force or (int(time.time()) - bucket.lastAccessed >= constants.refreshTimeout):
                searchID = self._randomIDInBucketRange(bucketIndex)
                refreshIDs.append(searchID)
            bucketIndex += 1
        return refreshIDs

    def removeContact(self, contactID):
        """ Remove the contact with the specified node ID from the routing
        table

        @param contactID: The node ID of the contact to remove
        @type contactID: str
        """
        bucketIndex = self._kbucketIndex(contactID)
        try:
            self._buckets[bucketIndex].removeContact(contactID)
        except ValueError:
            return

    def touchKBucket(self, key):
        """ Update the "last accessed" timestamp of the k-bucket which covers
        the range containing the specified key in the key/ID space

        @param key: A key in the range of the target k-bucket
        @type key: str
        """
        bucketIndex = self._kbucketIndex(key)
        self._buckets[bucketIndex].lastAccessed = int(time.time())

    def _kbucketIndex(self, key):
        """ Calculate the index of the k-bucket which is responsible for the
        specified key (or ID)

        @param key: The key for which to find the appropriate k-bucket index
        @type key: str

        @return: The index of the k-bucket responsible for the specified key
        @rtype: int
        """
        i = 0
        for bucket in self._buckets:
            if bucket.keyInRange(key):
                return i
            else:
                i += 1
        return i

    def _randomIDInBucketRange(self, bucketIndex):
        """ Returns a random ID in the specified k-bucket's range

        @param bucketIndex: The index of the k-bucket to use
        @type bucketIndex: int
        """
        idValue = random.randrange(
            self._buckets[bucketIndex].rangeMin, self._buckets[bucketIndex].rangeMax)
        randomID = hex(idValue)[2:]
        if randomID[-1] == 'L':
            randomID = randomID[:-1]
        if len(randomID) % 2 != 0:
            randomID = '0' + randomID
        randomID = randomID.decode('hex')
        randomID = (constants.key_bits / 8 - len(randomID)) * '\x00' + randomID
        return randomID

    def _splitBucket(self, oldBucketIndex):
        """ Splits the specified k-bucket into two new buckets which together
        cover the same range in the key/ID space

        @param oldBucketIndex: The index of k-bucket to split (in this table's
                               list of k-buckets)
        @type oldBucketIndex: int
        """
        # Resize the range of the current (old) k-bucket
        oldBucket = self._buckets[oldBucketIndex]
        splitPoint = oldBucket.rangeMax - (oldBucket.rangeMax - oldBucket.rangeMin) / 2
        # Create a new k-bucket to cover the range split off from the old bucket
        newBucket = kbucket.KBucket(splitPoint, oldBucket.rangeMax)
        oldBucket.rangeMax = splitPoint
        # Now, add the new bucket into the routing table tree
        self._buckets.insert(oldBucketIndex + 1, newBucket)
        # Finally, copy all nodes that belong to the new k-bucket into it...
        for contact in oldBucket._contacts:
            if newBucket.keyInRange(contact.id):
                newBucket.addContact(contact)
        # ...and remove them from the old bucket
        for contact in newBucket._contacts:
            oldBucket.removeContact(contact)


class OptimizedTreeRoutingTable(TreeRoutingTable):
    """ A version of the "tree"-type routing table specified by Kademlia,
    along with contact accounting optimizations specified in section 4.1 of
    of the 13-page version of the Kademlia paper.
    """

    def __init__(self, parentNodeID):
        TreeRoutingTable.__init__(self, parentNodeID)
        # Cache containing nodes eligible to replace stale k-bucket entries
        self._replacementCache = {}

    def addContact(self, contact):
        """ Add the given contact to the correct k-bucket; if it already
        exists, its status will be updated

        @param contact: The contact to add to this node's k-buckets
        @type contact: kademlia.contact.Contact
        """
        if contact.id == self._parentNodeID:
            return

        # Initialize/reset the "successively failed RPC" counter
        contact.failedRPCs = 0

        bucketIndex = self._kbucketIndex(contact.id)
        try:
            self._buckets[bucketIndex].addContact(contact)
        except kbucket.BucketFull:
            # The bucket is full; see if it can be split (by checking
            # if its range includes the host node's id)
            if self._buckets[bucketIndex].keyInRange(self._parentNodeID):
                self._splitBucket(bucketIndex)
                # Retry the insertion attempt
                self.addContact(contact)
            else:
                # We can't split the k-bucket
                # NOTE: This implementation follows section 4.1 of the 13 page version
                # of the Kademlia paper (optimized contact accounting without PINGs
                # - results in much less network traffic, at the expense of some memory)

                # Put the new contact in our replacement cache for the
                # corresponding k-bucket (or update it's position if
                # it exists already)
                if bucketIndex not in self._replacementCache:
                    self._replacementCache[bucketIndex] = []
                if contact in self._replacementCache[bucketIndex]:
                    self._replacementCache[bucketIndex].remove(contact)
                elif len(self._replacementCache[bucketIndex]) >= constants.replacementCacheSize:
                    self._replacementCache[bucketIndex].pop(0)
                self._replacementCache[bucketIndex].append(contact)

    def removeContact(self, contactID):
        """ Remove the contact with the specified node ID from the routing
        table

        @param contactID: The node ID of the contact to remove
        @type contactID: str
        """
        bucketIndex = self._kbucketIndex(contactID)
        try:
            contact = self._buckets[bucketIndex].getContact(contactID)
        except ValueError:
            return
        contact.failedRPCs += 1
        if contact.failedRPCs >= constants.rpcAttempts:
            self._buckets[bucketIndex].removeContact(contactID)
            # Replace this stale contact with one from our replacement cache, if we have any
            if bucketIndex in self._replacementCache:
                if len(self._replacementCache[bucketIndex]) > 0:
                    self._buckets[bucketIndex].addContact(
                        self._replacementCache[bucketIndex].pop())
