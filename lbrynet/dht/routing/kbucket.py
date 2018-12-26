import logging
import typing

from lbrynet.peer import Peer
from lbrynet.dht import constants
from lbrynet.dht.routing.distance import Distance

log = logging.getLogger(__name__)


class KBucket:
    """ Description - later
    """

    def __init__(self, range_min: int, range_max: int, node_id: bytes):
        """
        @param range_min: The lower boundary for the range in the n-bit ID
                         space covered by this k-bucket
        @param range_max: The upper boundary for the range in the ID space
                         covered by this k-bucket
        """
        self.last_accessed = 0
        self.range_min = range_min
        self.range_max = range_max
        self._contacts: typing.List[Peer] = []
        self._node_id = node_id

    def add_peer(self, contact: Peer) -> bool:
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
            return True
        elif len(self._contacts) < constants.k:
            self._contacts.append(contact)
            return True
        else:
            return False
            # raise BucketFull("No space in bucket to insert contact")

    def get_peer(self, contact_id: bytes) -> Peer:
        """Get the contact specified node ID

        @raise IndexError: raised if the contact is not in the bucket

        @param contactID: the node node_id of the contact to retrieve
        @type contactID: str

        @rtype: dht.contact._Contact
        """
        for contact in self._contacts:
            if contact.node_id == contact_id:
                return contact
        raise IndexError(contact_id)

    def get_peers(self, count=-1, exclude_contact=None, sort_distance_to=None) -> typing.List[Peer]:
        """ Returns a list containing up to the first count number of contacts

        @param count: The amount of contacts to return (if 0 or less, return
                      all contacts)
        @type count: int
        @param exclude_contact: A node node_id to exclude; if this contact is in
                               the list of returned values, it will be
                               discarded before returning. If a C{str} is
                               passed as this argument, it must be the
                               contact's ID.
        @type exclude_contact: str

        @param sort_distance_to: Sort distance to the node_id, defaulting to the parent node node_id. If False don't
                                 sort the contacts

        @raise IndexError: If the number of requested contacts is too large

        @return: Return up to the first count number of contacts in a list
                If no contacts are present an empty is returned
        @rtype: list
        """
        contacts = [contact for contact in self._contacts if contact.node_id != exclude_contact]

        # Return all contacts in bucket
        if count <= 0:
            count = len(contacts)

        # Get current contact number
        current_len = len(contacts)

        # If count greater than k - return only k contacts
        if count > constants.k:
            count = constants.k

        if not current_len:
            return contacts

        if sort_distance_to is False:
            pass
        else:
            sort_distance_to = sort_distance_to or self._node_id
            contacts.sort(key=lambda c: Distance(sort_distance_to)(c.node_id))

        return contacts[:min(current_len, count)]

    def get_bad_or_unknown_peers(self) -> typing.List[Peer]:
        contacts = self.get_peers(sort_distance_to=False)
        results = [contact for contact in contacts if contact.contact_is_good is False]
        results.extend(contact for contact in contacts if contact.contact_is_good is None)
        return results

    def remove_peer(self, peer: Peer) -> None:
        self._contacts.remove(peer)

    def key_in_range(self, key: bytes) -> bool:
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
        return self.range_min <= int.from_bytes(key, 'big') < self.range_max

    def __len__(self) -> int:
        return len(self._contacts)

    def __contains__(self, item) -> bool:
        return item in self._contacts
