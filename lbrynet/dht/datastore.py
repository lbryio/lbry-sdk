import UserDict
import constants
from interface import IDataStore
from zope.interface import implements


class DictDataStore(UserDict.DictMixin):
    """ A datastore using an in-memory Python dictionary """
    implements(IDataStore)

    def __init__(self, getTime=None):
        # Dictionary format:
        # { <key>: (<value>, <lastPublished>, <originallyPublished> <originalPublisherID>) }
        self._dict = {}
        if not getTime:
            from twisted.internet import reactor
            getTime = reactor.seconds
        self._getTime = getTime

    def keys(self):
        """ Return a list of the keys in this data store """
        return self._dict.keys()

    def removeExpiredPeers(self):
        now = int(self._getTime())
        for key in self._dict.keys():
            unexpired_peers = filter(lambda peer: now - peer[2] < constants.dataExpireTimeout, self._dict[key])
            if not unexpired_peers:
                del self._dict[key]
            else:
                self._dict[key] = unexpired_peers

    def hasPeersForBlob(self, key):
        if key in self._dict and len(filter(lambda peer: self._getTime() - peer[2] < constants.dataExpireTimeout,
                                            self._dict[key])):
            return True
        return False

    def addPeerToBlob(self, key, value, lastPublished, originallyPublished, originalPublisherID):
        if key in self._dict:
            if value not in map(lambda store_tuple: store_tuple[0], self._dict[key]):
                self._dict[key].append((value, lastPublished, originallyPublished, originalPublisherID))
        else:
            self._dict[key] = [(value, lastPublished, originallyPublished, originalPublisherID)]

    def getPeersForBlob(self, key):
        return [] if key not in self._dict else [
            val[0] for val in filter(lambda peer: self._getTime() - peer[2] < constants.dataExpireTimeout,
                                     self._dict[key])
        ]

    def removePeer(self, value):
        for key in self._dict:
            self._dict[key] = [val for val in self._dict[key] if val[0] != value]
            if not self._dict[key]:
                del self._dict[key]
