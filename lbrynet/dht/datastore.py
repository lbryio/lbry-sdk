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

        def notExpired(peer):
            if (now - peer[2]) > constants.dataExpireTimeout:
                return False
            return True

        for key in self._dict.keys():
            unexpired_peers = filter(notExpired, self._dict[key])
            self._dict[key] = unexpired_peers

    def hasPeersForBlob(self, key):
        if key in self._dict and len(self._dict[key]) > 0:
            return True
        return False

    def addPeerToBlob(self, key, value, lastPublished, originallyPublished, originalPublisherID):
        if key in self._dict:
            self._dict[key].append((value, lastPublished, originallyPublished, originalPublisherID))
        else:
            self._dict[key] = [(value, lastPublished, originallyPublished, originalPublisherID)]

    def getPeersForBlob(self, key):
        if key in self._dict:
            return [val[0] for val in self._dict[key]]

    def removePeer(self, value):
        for key in self._dict:
            self._dict[key] = [val for val in self._dict[key] if val[0] != value]
            if not self._dict[key]:
                del self._dict[key]
