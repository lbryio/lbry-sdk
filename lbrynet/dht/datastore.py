from collections import UserDict
from . import constants


class DictDataStore(UserDict):
    """ A datastore using an in-memory Python dictionary """
    #implements(IDataStore)

    def __init__(self, getTime=None):
        # Dictionary format:
        # { <key>: (<contact>, <value>, <lastPublished>, <originallyPublished> <originalPublisherID>) }
        self._dict = {}
        if not getTime:
            from twisted.internet import reactor
            getTime = reactor.seconds
        self._getTime = getTime
        self.completed_blobs = set()

    def keys(self):
        """ Return a list of the keys in this data store """
        return self._dict.keys()

    def filter_bad_and_expired_peers(self, key):
        """
        Returns only non-expired and unknown/good peers
        """
        return filter(
            lambda peer:
            self._getTime() - peer[3] < constants.dataExpireTimeout and peer[0].contact_is_good is not False,
            self._dict[key]
        )

    def filter_expired_peers(self, key):
        """
        Returns only non-expired peers
        """
        return filter(lambda peer: self._getTime() - peer[3] < constants.dataExpireTimeout, self._dict[key])

    def removeExpiredPeers(self):
        for key in self._dict.keys():
            unexpired_peers = self.filter_expired_peers(key)
            if not unexpired_peers:
                del self._dict[key]
            else:
                self._dict[key] = unexpired_peers

    def hasPeersForBlob(self, key):
        return True if key in self._dict and len(self.filter_bad_and_expired_peers(key)) else False

    def addPeerToBlob(self, contact, key, compact_address, lastPublished, originallyPublished, originalPublisherID):
        if key in self._dict:
            if compact_address not in map(lambda store_tuple: store_tuple[1], self._dict[key]):
                self._dict[key].append(
                    (contact, compact_address, lastPublished, originallyPublished, originalPublisherID)
                )
        else:
            self._dict[key] = [(contact, compact_address, lastPublished, originallyPublished, originalPublisherID)]

    def getPeersForBlob(self, key):
        return [] if key not in self._dict else [val[1] for val in self.filter_bad_and_expired_peers(key)]

    def getStoringContacts(self):
        contacts = set()
        for key in self._dict:
            for values in self._dict[key]:
                contacts.add(values[0])
        return list(contacts)
