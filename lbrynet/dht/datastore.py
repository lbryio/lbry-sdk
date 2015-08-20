#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive
#
# The docstrings in this module contain epytext markup; API documentation
# may be created by processing this file with epydoc: http://epydoc.sf.net

import UserDict
#import sqlite3
import cPickle as pickle
import time
import os
import constants



class DataStore(UserDict.DictMixin):
    """ Interface for classes implementing physical storage (for data
    published via the "STORE" RPC) for the Kademlia DHT
    
    @note: This provides an interface for a dict-like object
    """
    def keys(self):
        """ Return a list of the keys in this data store """

#    def lastPublished(self, key):
#        """ Get the time the C{(key, value)} pair identified by C{key}
#        was last published """

#    def originalPublisherID(self, key):
#        """ Get the original publisher of the data's node ID
#
#        @param key: The key that identifies the stored data
#        @type key: str
#
#        @return: Return the node ID of the original publisher of the
#        C{(key, value)} pair identified by C{key}.
#        """

#    def originalPublishTime(self, key):
#        """ Get the time the C{(key, value)} pair identified by C{key}
#        was originally published """

#    def setItem(self, key, value, lastPublished, originallyPublished, originalPublisherID):
#        """ Set the value of the (key, value) pair identified by C{key};
#        this should set the "last published" value for the (key, value)
#        pair to the current time
#        """

    def addPeerToBlob(self, key, value, lastPublished, originallyPublished, originalPublisherID):
        pass

#    def __getitem__(self, key):
#        """ Get the value identified by C{key} """

#    def __setitem__(self, key, value):
#        """ Convenience wrapper to C{setItem}; this accepts a tuple in the
#        format: (value, lastPublished, originallyPublished, originalPublisherID) """
#        self.setItem(key, *value)

#    def __delitem__(self, key):
#        """ Delete the specified key (and its value) """

class DictDataStore(DataStore):
    """ A datastore using an in-memory Python dictionary """
    def __init__(self):
        # Dictionary format:
        # { <key>: (<value>, <lastPublished>, <originallyPublished> <originalPublisherID>) }
        self._dict = {}

    def keys(self):
        """ Return a list of the keys in this data store """
        return self._dict.keys()

#    def lastPublished(self, key):
#        """ Get the time the C{(key, value)} pair identified by C{key}
#        was last published """
#        return self._dict[key][1]

#    def originalPublisherID(self, key):
#        """ Get the original publisher of the data's node ID
#
#        @param key: The key that identifies the stored data
#        @type key: str
#
#        @return: Return the node ID of the original publisher of the
#        C{(key, value)} pair identified by C{key}.
#        """
#        return self._dict[key][3]

#    def originalPublishTime(self, key):
#        """ Get the time the C{(key, value)} pair identified by C{key}
#        was originally published """
#        return self._dict[key][2]

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

#    def setItem(self, key, value, lastPublished, originallyPublished, originalPublisherID):
#        """ Set the value of the (key, value) pair identified by C{key};
#        this should set the "last published" value for the (key, value)
#        pair to the current time
#        """
#        self._dict[key] = (value, lastPublished, originallyPublished, originalPublisherID)

#    def __getitem__(self, key):
#        """ Get the value identified by C{key} """
#        return self._dict[key][0]

#    def __delitem__(self, key):
#        """ Delete the specified key (and its value) """
#        del self._dict[key]


#class SQLiteDataStore(DataStore):
#    """ Example of a SQLite database-based datastore
#    """
#    def __init__(self, dbFile=':memory:'):
#        """
#        @param dbFile: The name of the file containing the SQLite database; if
#                       unspecified, an in-memory database is used.
#        @type dbFile: str
#        """
#        createDB = not os.path.exists(dbFile)
#        self._db = sqlite3.connect(dbFile)
#        self._db.isolation_level = None
#        self._db.text_factory = str
#        if createDB:
#            self._db.execute('CREATE TABLE data(key, value, lastPublished, originallyPublished, originalPublisherID)')
#        self._cursor = self._db.cursor()

#    def keys(self):
#        """ Return a list of the keys in this data store """
#        keys = []
#        try:
#            self._cursor.execute("SELECT key FROM data")
#            for row in self._cursor:
#                keys.append(row[0].decode('hex'))
#        finally:
#            return keys

#    def lastPublished(self, key):
#        """ Get the time the C{(key, value)} pair identified by C{key}
#        was last published """
#        return int(self._dbQuery(key, 'lastPublished'))

#    def originalPublisherID(self, key):
#        """ Get the original publisher of the data's node ID

#        @param key: The key that identifies the stored data
#        @type key: str
        
#        @return: Return the node ID of the original publisher of the
#        C{(key, value)} pair identified by C{key}.
#        """
#        return self._dbQuery(key, 'originalPublisherID')

#    def originalPublishTime(self, key):
#        """ Get the time the C{(key, value)} pair identified by C{key}
#        was originally published """
#        return int(self._dbQuery(key, 'originallyPublished'))

#    def setItem(self, key, value, lastPublished, originallyPublished, originalPublisherID):
#        # Encode the key so that it doesn't corrupt the database
#        encodedKey = key.encode('hex')
#        self._cursor.execute("select key from data where key=:reqKey", {'reqKey': encodedKey})
#        if self._cursor.fetchone() == None:
#            self._cursor.execute('INSERT INTO data(key, value, lastPublished, originallyPublished, originalPublisherID) VALUES (?, ?, ?, ?, ?)', (encodedKey, buffer(pickle.dumps(value, pickle.HIGHEST_PROTOCOL)), lastPublished, originallyPublished, originalPublisherID))
#        else:
#            self._cursor.execute('UPDATE data SET value=?, lastPublished=?, originallyPublished=?, originalPublisherID=? WHERE key=?', (buffer(pickle.dumps(value, pickle.HIGHEST_PROTOCOL)), lastPublished, originallyPublished, originalPublisherID, encodedKey))
        
#    def _dbQuery(self, key, columnName, unpickle=False):
#        try:
#            self._cursor.execute("SELECT %s FROM data WHERE key=:reqKey" % columnName, {'reqKey': key.encode('hex')})
#            row = self._cursor.fetchone()
#            value = str(row[0])
#        except TypeError:
#            raise KeyError, key
#        else:
#            if unpickle:
#                return pickle.loads(value)
#            else:
#                return value

#    def __getitem__(self, key):
#        return self._dbQuery(key, 'value', unpickle=True)

#    def __delitem__(self, key):
#        self._cursor.execute("DELETE FROM data WHERE key=:reqKey", {'reqKey': key.encode('hex')})
