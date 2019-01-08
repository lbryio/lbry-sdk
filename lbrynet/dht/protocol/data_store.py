import asyncio
import typing
from collections import UserDict

from lbrynet.peer import Peer
from lbrynet.dht import constants


class DictDataStore(UserDict):
    def __init__(self, loop: asyncio.BaseEventLoop):
        # Dictionary format:
        # { <key>: (<contact>, <value>, <lastPublished>, <originallyPublished> <original_publisher_id>) }
        super().__init__()
        self._get_time = loop.time
        self.completed_blobs: typing.Set[str] = set()

    def filter_bad_and_expired_peers(self, key: bytes) -> typing.Iterator[Peer]:
        """
        Returns only non-expired and unknown/good peers
        """
        return filter(
            lambda peer:
            self._get_time() - peer[3] < constants.data_expiration and peer[0].contact_is_good is not False,
            self[key]
        )

    def filter_expired_peers(self, key: bytes) -> typing.Iterator[Peer]:
        """
        Returns only non-expired peers
        """
        return filter(lambda peer: self._get_time() - peer[3] < constants.data_expiration, self[key])

    def removed_expired_peers(self) -> None:
        expired_keys = []
        for key in self.keys():
            unexpired_peers = list(self.filter_expired_peers(key))
            if not unexpired_peers:
                expired_keys.append(key)
            else:
                self[key] = unexpired_peers
        for key in expired_keys:
            del self[key]

    def has_peers_for_blob(self, key: bytes) -> bool:
        return True if key in self and len(tuple(self.filter_bad_and_expired_peers(key))) else False

    def add_peer_to_blob(self, contact: Peer, key: bytes, compact_address: bytes, last_published: int,
                         originally_published: int, original_publisher_id: bytes) -> None:
        if key in self:
            if compact_address not in map(lambda store_tuple: store_tuple[1], self[key]):
                self[key].append(
                    (contact, compact_address, last_published, originally_published, original_publisher_id)
                )
        else:
            self[key] = [(contact, compact_address, last_published, originally_published, original_publisher_id)]

    def get_peers_for_blob(self, key: bytes) -> typing.List[Peer]:
        return [] if key not in self else [val[1] for val in self.filter_bad_and_expired_peers(key)]

    def get_storing_contacts(self) -> typing.List[Peer]:
        contacts = set()
        for key in self:
            for values in self[key]:
                contacts.add(values[0])
        return list(contacts)
