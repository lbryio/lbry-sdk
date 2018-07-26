from collections import UserDict
from . import constants


class DictDataStore(UserDict):
    """ A datastore using an in-memory Python dictionary """
    #implements(IDataStore)

    def __init__(self, getTime=None):
        # Dictionary format:
        # { <key>: (<contact>, <value>, <lastPublished>, <originallyPublished> <originalPublisherID>) }
        super().__init__()
        if not getTime:
            from twisted.internet import reactor
            getTime = reactor.seconds
        self._getTime = getTime
        self.completed_blobs = set()

    def filter_bad_and_expired_peers(self, key):
        """
        Returns only non-expired and unknown/good peers
        """
        return filter(
            lambda peer:
            self._getTime() - peer[3] < constants.dataExpireTimeout and peer[0].contact_is_good is not False,
            self[key]
        )

    def filter_expired_peers(self, key):
        """
        Returns only non-expired peers
        """
        return filter(lambda peer: self._getTime() - peer[3] < constants.dataExpireTimeout, self[key])

    def removeExpiredPeers(self):
        expired_keys = []
        for key in self.keys():
            unexpired_peers = list(self.filter_expired_peers(key))
            if not unexpired_peers:
                expired_keys.append(key)
            else:
                self[key] = unexpired_peers
        for key in expired_keys:
            del self[key]

    def hasPeersForBlob(self, key):
        return True if key in self and len(tuple(self.filter_bad_and_expired_peers(key))) else False

    def addPeerToBlob(self, contact, key, compact_address, lastPublished, originallyPublished, originalPublisherID):
        if key in self:
            if compact_address not in map(lambda store_tuple: store_tuple[1], self[key]):
                self[key].append(
                    (contact, compact_address, lastPublished, originallyPublished, originalPublisherID)
                )
        else:
            self[key] = [(contact, compact_address, lastPublished, originallyPublished, originalPublisherID)]

    def getPeersForBlob(self, key):
        return [] if key not in self else [val[1] for val in self.filter_bad_and_expired_peers(key)]

    def getStoringContacts(self):
        contacts = set()
        for key in self:
            for values in self[key]:
                contacts.add(values[0])
        return list(contacts)
