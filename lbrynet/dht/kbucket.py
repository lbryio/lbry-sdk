import logging
from . import constants
from .distance import Distance
from .error import BucketFull

log = logging.getLogger(__name__)


class KBucket(object):
    """ Description - later
    """

    def __init__(self, rangeMin, rangeMax, node_id):
        """
        @param rangeMin: The lower boundary for the range in the n-bit ID
                         space covered by this k-bucket
        @param rangeMax: The upper boundary for the range in the ID space
                         covered by this k-bucket
        """
        self.lastAccessed = 0
        self.rangeMin = rangeMin
        self.rangeMax = rangeMax
        self._contacts = list()
        self._node_id = node_id

    def addContact(self, contact):
        """ Add contact to _contact list in the right order. This will move the
        contact to the end of the k-bucket if it is already present.

        @raise kademlia.kbucket.BucketFull: Raised when the bucket is full and
                                            the contact isn't in the bucket
                                            already

        @param contact: The contact to add
        @type contact: dht.contact._Contact
        """
        if contact in self._contacts:
            # Move the existing contact to the end of the list
            # - using the new contact to allow add-on data
            #   (e.g. optimization-specific stuff) to pe updated as well
            self._contacts.remove(contact)
            self._contacts.append(contact)
        elif len(self._contacts) < constants.k:
            self._contacts.append(contact)
        else:
            raise BucketFull("No space in bucket to insert contact")

    def getContact(self, contactID):
        """Get the contact specified node ID

        @raise IndexError: raised if the contact is not in the bucket

        @param contactID: the node id of the contact to retrieve
        @type contactID: str

        @rtype: dht.contact._Contact
        """
        for contact in self._contacts:
            if contact.id == contactID:
                return contact
        raise IndexError(contactID)

    def getContacts(self, count=-1, excludeContact=None, sort_distance_to=None):
        """ Returns a list containing up to the first count number of contacts

        @param count: The amount of contacts to return (if 0 or less, return
                      all contacts)
        @type count: int
        @param excludeContact: A node id to exclude; if this contact is in
                               the list of returned values, it will be
                               discarded before returning. If a C{str} is
                               passed as this argument, it must be the
                               contact's ID.
        @type excludeContact: str

        @param sort_distance_to: Sort distance to the id, defaulting to the parent node id. If False don't
                                 sort the contacts

        @raise IndexError: If the number of requested contacts is too large

        @return: Return up to the first count number of contacts in a list
                If no contacts are present an empty is returned
        @rtype: list
        """
        contacts = [contact for contact in self._contacts if contact.id != excludeContact]

        # Return all contacts in bucket
        if count <= 0:
            count = len(contacts)

        # Get current contact number
        currentLen = len(contacts)

        # If count greater than k - return only k contacts
        if count > constants.k:
            count = constants.k

        if not currentLen:
            return contacts

        if sort_distance_to is False:
            pass
        else:
            sort_distance_to = sort_distance_to or self._node_id
            contacts.sort(key=lambda c: Distance(sort_distance_to)(c.id))

        return contacts[:min(currentLen, count)]

    def getBadOrUnknownContacts(self):
        contacts = self.getContacts(sort_distance_to=False)
        results = [contact for contact in contacts if contact.contact_is_good is False]
        results.extend(contact for contact in contacts if contact.contact_is_good is None)
        return results

    def removeContact(self, contact):
        """ Remove the contact from the bucket

        @param contact: The contact to remove
        @type contact: dht.contact._Contact

        @raise ValueError: The specified contact is not in this bucket
        """
        self._contacts.remove(contact)

    def keyInRange(self, key):
        """ Tests whether the specified key (i.e. node ID) is in the range
        of the n-bit ID space covered by this k-bucket (in otherwords, it
        returns whether or not the specified key should be placed in this
        k-bucket)

        @param key: The key to test
        @type key: str or int

        @return: C{True} if the key is in this k-bucket's range, or C{False}
                 if not.
        @rtype: bool
        """
        if isinstance(key, str):
            key = long(key.encode('hex'), 16)
        return self.rangeMin <= key < self.rangeMax

    def __len__(self):
        return len(self._contacts)

    def __contains__(self, item):
        return item in self._contacts
