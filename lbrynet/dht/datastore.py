#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive
#
# The docstrings in this module contain epytext markup; API documentation
# may be created by processing this file with epydoc: http://epydoc.sf.net

import UserDict
import time
import constants



class DataStore(UserDict.DictMixin):
    """ Interface for classes implementing physical storage (for data
    published via the "STORE" RPC) for the Kademlia DHT
    
    @note: This provides an interface for a dict-like object
    """
    def keys(self):
        """ Return a list of the keys in this data store """

    def addPeerToBlob(self, key, value, lastPublished, originallyPublished, originalPublisherID):
        pass

class DictDataStore(DataStore):
    """ A datastore using an in-memory Python dictionary """
    def __init__(self):
        # Dictionary format:
        # { <key>: (<value>, <lastPublished>, <originallyPublished> <originalPublisherID>) }
        self._dict = {}

    def keys(self):
        """ Return a list of the keys in this data store """
        return self._dict.keys()

    def removeExpiredPeers(self):
        now = int(time.time())
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
