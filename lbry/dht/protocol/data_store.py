import asyncio
import typing
from collections import deque

from lbry.dht import constants
if typing.TYPE_CHECKING:
    from lbry.dht.peer import KademliaPeer, PeerManager


class DictDataStore:
    def __init__(self, loop: asyncio.AbstractEventLoop, peer_manager: 'PeerManager'):
        # Dictionary format:
        # { <key>: [(<contact>, <age>), ...] }
        self._data_store: typing.Dict[bytes, typing.List[typing.Tuple['KademliaPeer', float]]] = {}

        self.loop = loop
        self._peer_manager = peer_manager
        self.completed_blobs: typing.Set[str] = set()

    def keys(self):
        return self._data_store.keys()

    def __len__(self):
        return self._data_store.__len__()

    def removed_expired_peers(self):
        now = self.loop.time()
        keys = list(self._data_store.keys())
        for key in keys:
            to_remove = []
            for (peer, ts) in self._data_store[key]:
                if ts + constants.DATA_EXPIRATION < now or self._peer_manager.peer_is_good(peer) is False:
                    to_remove.append((peer, ts))
            for item in to_remove:
                self._data_store[key].remove(item)
            if not self._data_store[key]:
                del self._data_store[key]

    def filter_bad_and_expired_peers(self, key: bytes) -> typing.Iterator['KademliaPeer']:
        """
        Returns only non-expired and unknown/good peers
        """
        for peer in self.filter_expired_peers(key):
            if self._peer_manager.peer_is_good(peer) is not False:
                yield peer

    def filter_expired_peers(self, key: bytes) -> typing.Iterator['KademliaPeer']:
        """
        Returns only non-expired peers
        """
        now = self.loop.time()
        for (peer, ts) in self._data_store.get(key, []):
            if ts + constants.DATA_EXPIRATION > now:
                yield peer

    def has_peers_for_blob(self, key: bytes) -> bool:
        return key in self._data_store

    def add_peer_to_blob(self, contact: 'KademliaPeer', key: bytes) -> None:
        now = self.loop.time()
        if key in self._data_store:
            current = list(filter(lambda x: x[0] == contact, self._data_store[key]))
            if len(current) > 0:
                self._data_store[key][self._data_store[key].index(current[0])] = contact, now
            else:
                self._data_store[key].append((contact, now))
        else:
            self._data_store[key] = [(contact, now)]

    def get_peers_for_blob(self, key: bytes) -> typing.List['KademliaPeer']:
        return list(self.filter_bad_and_expired_peers(key))

    def get_storing_contacts(self) -> typing.List['KademliaPeer']:
        peers = set()
        for _, stored in self._data_store.items():
            peers.update(set(map(lambda tup: tup[0], stored)))
        return list(peers)
