import UserDict
import time
import os
import json
import constants
from copy import deepcopy
from interface import IDataStore
from zope.interface import implements
from lbrynet import conf

NODE_ID = "node_id"
CLOSEST_NODES = "closestNodes"
NODE_STATE = "nodeState"
DATA_STORE = "dataStore"


class DictDataStore(UserDict.DictMixin):
    """ A datastore using an in-memory Python dictionary """
    implements(IDataStore)

    def __init__(self):
        # Dictionary format:
        # { <key>: (<value>, <lastPublished>, <originallyPublished> <originalPublisherID>) }
        self._dict = {}
        self._node_state = {}

    def __getitem__(self, item):
        return self._dict[item]

    def __setitem__(self, key, value):
        self._dict[key] = value
        return

    def keys(self):
        """ Return a list of the keys in this data store """
        return self._dict.keys()

    def getNodeState(self):
        return self._node_state

    def removeExpiredPeers(self):
        now = int(time.time())

        def notExpired(peer):
            if (now - peer[2]) > constants.dataExpireTimeout:
                return False
            return True

        for key in self.keys():
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
        keys = self.keys()
        for key in keys:
            self._dict[key] = [val for val in self._dict[key] if val[0] != value]
            if not self._dict[key]:
                del self._dict[key]

    def Load(self):
        pass

    def Save(self, contacts):
        pass


class JSONFileDataStore(DictDataStore):
    def __init__(self, node, path, file_name=None):
        DictDataStore.__init__(self)
        self._node = node
        self._path = os.path.join(path, file_name or "dht_datastore.json")

    def Load(self):
        nodeState = {}
        encodedDataStore = {}
        encodedNodeState = {}
        if os.path.isfile(self._path):
            with open(self._path, "r") as datastore_file:
                try:
                    encodedDataStore.update(json.loads(datastore_file.read()))
                    encodedNodeState = encodedDataStore.pop(NODE_STATE, {})
                except ValueError:
                    pass
        if NODE_ID in encodedNodeState:
            nodeState[NODE_ID] = encodedNodeState.pop(NODE_ID).decode('hex')
        else:
            nodeState[NODE_ID] = conf.settings.node_id
        if CLOSEST_NODES in encodedNodeState:
            contacts = encodedNodeState[CLOSEST_NODES]
            contact_triples = [(contact_id.decode('hex'), address, int(port))
                                for (contact_id, address, port) in contacts]
            nodeState[CLOSEST_NODES] = contact_triples
        self._node_state.update(nodeState)
        encodedDataStoreValues = encodedDataStore.pop(DATA_STORE, {})
        for key in encodedDataStoreValues.keys():
            items = encodedDataStoreValues.pop(key)
            self[key.decode('hex')] = [(v.decode('hex'), int(l), int(o), p.decode('hex'))
                                       for (v, l, o, p) in items]

    def Save(self, contacts):
        rawDataStore = deepcopy(self._dict)
        encodedDataStore = {DATA_STORE: {}}
        nodeState = self.getNodeState()
        for k in rawDataStore.keys():
            items = [(v.encode('hex'), int(l), int(o), p.encode('hex'))
                     for (v, l, o, p) in rawDataStore[k]]
            encodedDataStore[DATA_STORE][k.encode('hex')] = items
        nodeState[NODE_ID] = conf.settings.node_id.encode('hex')
        nodeState[CLOSEST_NODES] = [(contact.id.encode('hex'), str(contact.address),
                                     int(contact.port))
                                    for contact in contacts]
        encodedDataStore[NODE_STATE] = nodeState
        with open(self._path, "w") as datastore_file:
            datastore_file.write(json.dumps(encodedDataStore, indent=2))
