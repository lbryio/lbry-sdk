# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive
#
# The docstrings in this module contain epytext markup; API documentation
# may be created by processing this file with epydoc: http://epydoc.sf.net

import random
from zope.interface import implements
from twisted.internet import defer
import constants
import kbucket
from error import TimeoutError
from distance import Distance
from interface import IRoutingTable
import logging

log = logging.getLogger(__name__)


class TreeRoutingTable(object):
    """ This class implements a routing table used by a Node class.

    The Kademlia routing table is a binary tree whFose leaves are k-buckets,
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

    def __init__(self, parentNodeID, getTime=None):
        """
        @param parentNodeID: The n-bit node ID of the node to which this
                             routing table belongs
        @type parentNodeID: str
        """
        # Create the initial (single) k-bucket covering the range of the entire n-bit ID space
        self._parentNodeID = parentNodeID
        self._buckets = [kbucket.KBucket(rangeMin=0, rangeMax=2 ** constants.key_bits, node_id=self._parentNodeID)]
        if not getTime:
            from twisted.internet import reactor
            getTime = reactor.seconds
        self._getTime = getTime

    def get_contacts(self):
        contacts = []
        for i in range(len(self._buckets)):
            for contact in self._buckets[i]._contacts:
                contacts.append(contact)
        return contacts

    def _shouldSplit(self, bucketIndex, toAdd):
        #  https://stackoverflow.com/questions/32129978/highly-unbalanced-kademlia-routing-table/32187456#32187456
        if self._buckets[bucketIndex].keyInRange(self._parentNodeID):
            return True
        contacts = self.get_contacts()
        distance = Distance(self._parentNodeID)
        contacts.sort(key=lambda c: distance(c.id))
        kth_contact = contacts[-1] if len(contacts) < constants.k else contacts[constants.k-1]
        return distance(toAdd) < distance(kth_contact.id)

    def addContact(self, contact):
        """ Add the given contact to the correct k-bucket; if it already
        exists, its status will be updated

        @param contact: The contact to add to this node's k-buckets
        @type contact: kademlia.contact.Contact

        @rtype: defer.Deferred
        """

        if contact.id == self._parentNodeID:
            return defer.succeed(None)
        bucketIndex = self._kbucketIndex(contact.id)
        try:
            self._buckets[bucketIndex].addContact(contact)
        except kbucket.BucketFull:
            # The bucket is full; see if it can be split (by checking if its range includes the host node's id)
            if self._shouldSplit(bucketIndex, contact.id):
                self._splitBucket(bucketIndex)
                # Retry the insertion attempt
                return self.addContact(contact)
            else:
                # We can't split the k-bucket
                #
                # The 13 page kademlia paper specifies that the least recently contacted node in the bucket
                # shall be pinged. If it fails to reply it is replaced with the new contact. If the ping is successful
                # the new contact is ignored and not added to the bucket (sections 2.2 and 2.4).
                #
                # A reasonable extension to this is BEP 0005, which extends the above:
                #
                #    Not all nodes that we learn about are equal. Some are "good" and some are not.
                #    Many nodes using the DHT are able to send queries and receive responses,
                #    but are not able to respond to queries from other nodes. It is important that
                #    each node's routing table must contain only known good nodes. A good node is
                #    a node has responded to one of our queries within the last 15 minutes. A node
                #    is also good if it has ever responded to one of our queries and has sent us a
                #    query within the last 15 minutes. After 15 minutes of inactivity, a node becomes
                #    questionable. Nodes become bad when they fail to respond to multiple queries
                #    in a row. Nodes that we know are good are given priority over nodes with unknown status.
                #
                # When there are bad or questionable nodes in the bucket, the least recent is selected for
                # potential replacement (BEP 0005). When all nodes in the bucket are fresh, the head (least recent)
                # contact is selected as described in section 2.2 of the kademlia paper. In both cases the new contact
                # is ignored if the pinged node replies.

                def replaceContact(failure, deadContact):
                    """
                    Callback for the deferred PING RPC to see if the node to be replaced in the k-bucket is still
                    responding

                    @type failure: twisted.python.failure.Failure
                    """
                    failure.trap(TimeoutError)
                    log.debug("Replacing dead contact in bucket %i: %s:%i (%s) with %s:%i (%s)", bucketIndex,
                              deadContact.address, deadContact.port, deadContact.log_id(), contact.address,
                              contact.port, contact.log_id())
                    try:
                        self._buckets[bucketIndex].removeContact(deadContact)
                    except ValueError:
                        # The contact has already been removed (probably due to a timeout)
                        pass
                    return self.addContact(contact)

                not_good_contacts = self._buckets[bucketIndex].getBadOrUnknownContacts()
                if not_good_contacts:
                    to_replace = not_good_contacts[0]
                else:
                    to_replace = self._buckets[bucketIndex]._contacts[0]
                df = to_replace.ping()
                df.addErrback(replaceContact, to_replace)
                return df
        else:
            self.touchKBucketByIndex(bucketIndex)
            return defer.succeed(None)

    def findCloseNodes(self, key, count, sender_node_id=None):
        """ Finds a number of known nodes closest to the node/value with the
        specified key.

        @param key: the n-bit key (i.e. the node or value ID) to search for
        @type key: str
        @param count: the amount of contacts to return
        @type count: int
        @param sender_node_id: Used during RPC, this is be the sender's Node ID
                               Whatever ID is passed in the paramater will get
                               excluded from the list of returned contacts.
        @type sender_node_id: str

        @return: A list of node contacts (C{kademlia.contact.Contact instances})
                 closest to the specified key.
                 This method will return C{k} (or C{count}, if specified)
                 contacts if at all possible; it will only return fewer if the
                 node is returning all of the contacts that it knows of.
        @rtype: list
        """
        bucketIndex = self._kbucketIndex(key)

        if bucketIndex < len(self._buckets):
            # sort these
            closestNodes = self._buckets[bucketIndex].getContacts(count, sender_node_id, sort_distance_to=key)
        else:
            closestNodes = []
        # This method must return k contacts (even if we have the node
        # with the specified key as node ID), unless there is less
        # than k remote nodes in the routing table
        i = 1
        canGoLower = bucketIndex - i >= 0
        canGoHigher = bucketIndex + i < len(self._buckets)

        def get_remain(closest):
            return min(count, constants.k) - len(closest)

        distance = Distance(key)

        while len(closestNodes) < min(count, constants.k) and (canGoLower or canGoHigher):
            iteration_contacts = []
            # get contacts from lower and/or higher buckets without sorting them
            if canGoLower and len(closestNodes) < min(count, constants.k):
                lower_bucket = self._buckets[bucketIndex - i]
                contacts = lower_bucket.getContacts(get_remain(closestNodes), sender_node_id, sort_distance_to=False)
                iteration_contacts.extend(contacts)
                canGoLower = bucketIndex - (i + 1) >= 0

            if canGoHigher and len(closestNodes) < min(count, constants.k):
                higher_bucket = self._buckets[bucketIndex + i]
                contacts = higher_bucket.getContacts(get_remain(closestNodes), sender_node_id, sort_distance_to=False)
                iteration_contacts.extend(contacts)
                canGoHigher = bucketIndex + (i + 1) < len(self._buckets)
            i += 1
            # sort the combined contacts and add as many as possible/needed to the combined contact list
            iteration_contacts.sort(key=lambda c: distance(c.id), reverse=True)
            while len(iteration_contacts) and len(closestNodes) < min(count, constants.k):
                closestNodes.append(iteration_contacts.pop())
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
        now = int(self._getTime())
        for bucket in self._buckets[startIndex:]:
            if force or now - bucket.lastAccessed >= constants.refreshTimeout:
                searchID = self._randomIDInBucketRange(bucketIndex)
                refreshIDs.append(searchID)
            bucketIndex += 1
        return refreshIDs

    def removeContact(self, contact):
        """
        Remove the contact from the routing table

        @param contact: The contact to remove
        @type contact: dht.contact._Contact
        """
        bucketIndex = self._kbucketIndex(contact.id)
        try:
            self._buckets[bucketIndex].removeContact(contact)
        except ValueError:
            return

    def touchKBucket(self, key):
        """ Update the "last accessed" timestamp of the k-bucket which covers
        the range containing the specified key in the key/ID space

        @param key: A key in the range of the target k-bucket
        @type key: str
        """
        self.touchKBucketByIndex(self._kbucketIndex(key))

    def touchKBucketByIndex(self, bucketIndex):
        self._buckets[bucketIndex].lastAccessed = int(self._getTime())

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
        newBucket = kbucket.KBucket(splitPoint, oldBucket.rangeMax, self._parentNodeID)
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

    def contactInRoutingTable(self, address_tuple):
        for bucket in self._buckets:
            for contact in bucket.getContacts(sort_distance_to=False):
                if address_tuple[0] == contact.address and address_tuple[1] == contact.port:
                    return True
        return False

    def bucketsWithContacts(self):
        count = 0
        for bucket in self._buckets:
            if len(bucket):
                count += 1
        return count
