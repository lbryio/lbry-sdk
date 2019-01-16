import asyncio
import typing
from collections import UserDict

from lbrynet.dht import constants
if typing.TYPE_CHECKING:
    from lbrynet.dht.peer import KademliaPeer, PeerManager


class DictDataStore(UserDict):
    def __init__(self, loop: asyncio.BaseEventLoop, peer_manager: 'PeerManager'):
        # Dictionary format:
        # { <key>: (<contact>, <value>, <lastPublished>, <originallyPublished> <original_publisher_id>) }
        super().__init__()
        self._get_time = loop.time
        self._peer_manager = peer_manager
        self.completed_blobs: typing.Set[str] = set()

    def filter_bad_and_expired_peers(self, key: bytes) -> typing.List['KademliaPeer']:
        """
        Returns only non-expired and unknown/good peers
        """
        peers = []
        for peer in filter(lambda p: self._get_time() - p[3] < constants.data_expiration, self[key]):
            if self._peer_manager.contact_triple_is_good(peer.node_id, peer.address, peer.udp_port) is not False:
                peers.append(peer)
        return peers

    def filter_expired_peers(self, key: bytes) -> typing.List['KademliaPeer']:
        """
        Returns only non-expired peers
        """
        return list(filter(lambda peer: self._get_time() - peer[3] < constants.data_expiration, self[key]))

    def removed_expired_peers(self):
        expired_keys = []
        for key in self.keys():
            unexpired_peers = self.filter_expired_peers(key)
            if not unexpired_peers:
                expired_keys.append(key)
            else:
                self[key] = unexpired_peers
        for key in expired_keys:
            del self[key]

    def has_peers_for_blob(self, key: bytes) -> bool:
        return key in self and len(self.filter_bad_and_expired_peers(key)) > 0

    def add_peer_to_blob(self, contact: 'KademliaPeer', key: bytes, compact_address: bytes, last_published: int,
                         originally_published: int, original_publisher_id: bytes) -> None:
        if key in self:
            if compact_address not in map(lambda store_tuple: store_tuple[1], self[key]):
                self[key].append(
                    (contact, compact_address, last_published, originally_published, original_publisher_id)
                )
        else:
            self[key] = [(contact, compact_address, last_published, originally_published, original_publisher_id)]

    def get_peers_for_blob(self, key: bytes) -> typing.List['KademliaPeer']:
        return [] if key not in self else [peer for peer in self.filter_bad_and_expired_peers(key)]

    def get_storing_contacts(self) -> typing.List['KademliaPeer']:
        peers = set()
        for key in self:
            for values in self[key]:
                if values[0] not in peers:
                    peers.add(values[0])
        return list(peers)
