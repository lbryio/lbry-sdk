import asyncio
import typing

from lbrynet.dht import constants
if typing.TYPE_CHECKING:
    from lbrynet.dht.peer import KademliaPeer, PeerManager


class DictDataStore:
    def __init__(self, loop: asyncio.BaseEventLoop, peer_manager: 'PeerManager'):
        # Dictionary format:
        # { <key>: [<contact>, <value>, <lastPublished>, <originallyPublished> <original_publisher_id>] }
        self._data_store: typing.Dict[bytes,
                                      typing.List[typing.Tuple['KademliaPeer', bytes, float, float, bytes]]] = {}
        self._get_time = loop.time
        self._peer_manager = peer_manager
        self.completed_blobs: typing.Set[str] = set()

    def filter_bad_and_expired_peers(self, key: bytes) -> typing.List['KademliaPeer']:
        """
        Returns only non-expired and unknown/good peers
        """
        peers = []
        for peer in map(lambda p: p[0],
                        filter(lambda peer: self._get_time() - peer[3] < constants.data_expiration,
                               self._data_store[key])):
            if self._peer_manager.peer_is_good(peer) is not False:
                peers.append(peer)
        return peers

    def filter_expired_peers(self, key: bytes) -> typing.List['KademliaPeer']:
        """
        Returns only non-expired peers
        """
        return list(
            map(
                lambda p: p[0],
                filter(lambda peer: self._get_time() - peer[3] < constants.data_expiration, self._data_store[key])
            )
        )

    def removed_expired_peers(self):
        expired_keys = []
        for key in self._data_store.keys():
            unexpired_peers = self.filter_expired_peers(key)
            if not unexpired_peers:
                expired_keys.append(key)
            else:
                self._data_store[key] = [x for x in self._data_store[key] if x[0] in unexpired_peers]
        for key in expired_keys:
            del self._data_store[key]

    def has_peers_for_blob(self, key: bytes) -> bool:
        return key in self._data_store and len(self.filter_bad_and_expired_peers(key)) > 0

    def add_peer_to_blob(self, contact: 'KademliaPeer', key: bytes, compact_address: bytes, last_published: int,
                         originally_published: int, original_publisher_id: bytes) -> None:
        if key in self._data_store:
            if compact_address not in map(lambda store_tuple: store_tuple[1], self._data_store[key]):
                self._data_store[key].append(
                    (contact, compact_address, last_published, originally_published, original_publisher_id)
                )
        else:
            self._data_store[key] = [(contact, compact_address, last_published, originally_published,
                                      original_publisher_id)]

    def get_peers_for_blob(self, key: bytes) -> typing.List['KademliaPeer']:
        return [] if key not in self._data_store else [peer for peer in self.filter_bad_and_expired_peers(key)]

    def get_storing_contacts(self) -> typing.List['KademliaPeer']:
        peers = set()
        for key in self._data_store:
            for values in self._data_store[key]:
                if values[0] not in peers:
                    peers.add(values[0])
        return list(peers)
