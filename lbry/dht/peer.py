import typing
import asyncio
import logging
from dataclasses import dataclass, field
from functools import lru_cache

from prometheus_client import Gauge

from lbry.utils import is_valid_public_ipv4 as _is_valid_public_ipv4, LRUCache
from lbry.dht import constants
from lbry.dht.serialization.datagram import make_compact_address, make_compact_ip, decode_compact_address

ALLOW_LOCALHOST = False
CACHE_SIZE = 16384
log = logging.getLogger(__name__)


@lru_cache(CACHE_SIZE)
def make_kademlia_peer(node_id: typing.Optional[bytes], address: typing.Optional[str],
                       udp_port: typing.Optional[int] = None,
                       tcp_port: typing.Optional[int] = None,
                       allow_localhost: bool = False) -> 'KademliaPeer':
    return KademliaPeer(address, node_id, udp_port, tcp_port=tcp_port, allow_localhost=allow_localhost)


def is_valid_public_ipv4(address, allow_localhost: bool = False):
    allow_localhost = bool(allow_localhost or ALLOW_LOCALHOST)
    return _is_valid_public_ipv4(address, allow_localhost)


class PeerManager:
    peer_manager_keys_metric = Gauge(
        "peer_manager_keys", "Number of keys tracked by PeerManager dicts (sum)", namespace="dht_node",
        labelnames=("scope",)
    )
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._rpc_failures: typing.Dict[
            typing.Tuple[str, int], typing.Tuple[typing.Optional[float], typing.Optional[float]]
        ] = LRUCache(CACHE_SIZE)
        self._last_replied: typing.Dict[typing.Tuple[str, int], float] = LRUCache(CACHE_SIZE)
        self._last_sent: typing.Dict[typing.Tuple[str, int], float] = LRUCache(CACHE_SIZE)
        self._last_requested: typing.Dict[typing.Tuple[str, int], float] = LRUCache(CACHE_SIZE)
        self._node_id_mapping: typing.Dict[typing.Tuple[str, int], bytes] = LRUCache(CACHE_SIZE)
        self._node_id_reverse_mapping: typing.Dict[bytes, typing.Tuple[str, int]] = LRUCache(CACHE_SIZE)
        self._node_tokens: typing.Dict[bytes, (float, bytes)] = LRUCache(CACHE_SIZE)

    def count_cache_keys(self):
        return len(self._rpc_failures) + len(self._last_replied) + len(self._last_sent) + len(
            self._last_requested) + len(self._node_id_mapping) + len(self._node_id_reverse_mapping) + len(
            self._node_tokens)

    def reset(self):
        for statistic in (self._rpc_failures, self._last_replied, self._last_sent, self._last_requested):
            statistic.clear()

    def report_failure(self, address: str, udp_port: int):
        now = self._loop.time()
        _, previous = self._rpc_failures.pop((address, udp_port), (None, None))
        self._rpc_failures[(address, udp_port)] = (previous, now)

    def report_last_sent(self, address: str, udp_port: int):
        now = self._loop.time()
        self._last_sent[(address, udp_port)] = now

    def report_last_replied(self, address: str, udp_port: int):
        now = self._loop.time()
        self._last_replied[(address, udp_port)] = now

    def report_last_requested(self, address: str, udp_port: int):
        now = self._loop.time()
        self._last_requested[(address, udp_port)] = now

    def clear_token(self, node_id: bytes):
        self._node_tokens.pop(node_id, None)

    def update_token(self, node_id: bytes, token: bytes):
        now = self._loop.time()
        self._node_tokens[node_id] = (now, token)

    def get_node_token(self, node_id: bytes) -> typing.Optional[bytes]:
        ts, token = self._node_tokens.get(node_id, (0, None))
        if ts and ts > self._loop.time() - constants.TOKEN_SECRET_REFRESH_INTERVAL:
            return token

    def get_last_replied(self, address: str, udp_port: int) -> typing.Optional[float]:
        return self._last_replied.get((address, udp_port))

    def update_contact_triple(self, node_id: bytes, address: str, udp_port: int):
        """
        Update the mapping of node_id -> address tuple and that of address tuple -> node_id
        This is to handle peers changing addresses and ids while assuring that the we only ever have
        one node id / address tuple mapped to each other
        """
        if (address, udp_port) in self._node_id_mapping:
            self._node_id_reverse_mapping.pop(self._node_id_mapping.pop((address, udp_port)))
        if node_id in self._node_id_reverse_mapping:
            self._node_id_mapping.pop(self._node_id_reverse_mapping.pop(node_id))
        self._node_id_mapping[(address, udp_port)] = node_id
        self._node_id_reverse_mapping[node_id] = (address, udp_port)
        self.peer_manager_keys_metric.labels("global").set(self.count_cache_keys())

    def get_node_id_for_endpoint(self, address, port):
        return self._node_id_mapping.get((address, port))

    def prune(self):  # TODO: periodically call this
        now = self._loop.time()
        to_pop = []
        for (address, udp_port), (_, last_failure) in self._rpc_failures.items():
            if last_failure and last_failure < now - constants.RPC_ATTEMPTS_PRUNING_WINDOW:
                to_pop.append((address, udp_port))
        while to_pop:
            del self._rpc_failures[to_pop.pop()]
        to_pop = []
        for node_id, (age, token) in self._node_tokens.items():  # pylint: disable=unused-variable
            if age < now - constants.TOKEN_SECRET_REFRESH_INTERVAL:
                to_pop.append(node_id)
        while to_pop:
            del self._node_tokens[to_pop.pop()]

    def contact_triple_is_good(self, node_id: bytes, address: str, udp_port: int):  # pylint: disable=too-many-return-statements
        """
        :return: False if peer is bad, None if peer is unknown, or True if peer is good
        """

        delay = self._loop.time() - constants.CHECK_REFRESH_INTERVAL

        # fixme: find a way to re-enable that without breaking other parts
        # if node_id not in self._node_id_reverse_mapping or (address, udp_port) not in self._node_id_mapping:
        #    return
        # addr_tup = (address, udp_port)
        # if self._node_id_reverse_mapping[node_id] != addr_tup or self._node_id_mapping[addr_tup] != node_id:
        #    return
        previous_failure, most_recent_failure = self._rpc_failures.get((address, udp_port), (None, None))
        last_requested = self._last_requested.get((address, udp_port))
        last_replied = self._last_replied.get((address, udp_port))
        if node_id is None:
            return None
        if most_recent_failure and last_replied:
            if delay < last_replied > most_recent_failure:
                return True
            elif last_replied > most_recent_failure:
                return
            return False
        elif previous_failure and most_recent_failure and most_recent_failure > delay:
            return False
        elif last_replied and last_replied > delay:
            return True
        elif last_requested and last_requested > delay:
            return None
        return

    def peer_is_good(self, peer: 'KademliaPeer'):
        return self.contact_triple_is_good(peer.node_id, peer.address, peer.udp_port)

    def decode_tcp_peer_from_compact_address(self, compact_address: bytes) -> 'KademliaPeer':  # pylint: disable=no-self-use
        node_id, address, tcp_port = decode_compact_address(compact_address)
        return make_kademlia_peer(node_id, address, udp_port=None, tcp_port=tcp_port)


@dataclass(unsafe_hash=True)
class KademliaPeer:
    address: str = field(hash=True)
    _node_id: typing.Optional[bytes] = field(hash=True)
    udp_port: typing.Optional[int] = field(hash=True)
    tcp_port: typing.Optional[int] = field(compare=False, hash=False)
    protocol_version: typing.Optional[int] = field(default=1, compare=False, hash=False)
    allow_localhost: bool = field(default=False, compare=False, hash=False)

    def __post_init__(self):
        if self._node_id is not None:
            if not len(self._node_id) == constants.HASH_LENGTH:
                raise ValueError("invalid node_id: {}".format(self._node_id.hex()))
        if self.udp_port is not None and not 1024 <= self.udp_port <= 65535:
            raise ValueError(f"invalid udp port: {self.address}:{self.udp_port}")
        if self.tcp_port is not None and not 1024 <= self.tcp_port <= 65535:
            raise ValueError(f"invalid tcp port: {self.address}:{self.tcp_port}")
        if not is_valid_public_ipv4(self.address, self.allow_localhost):
            raise ValueError(f"invalid ip address: '{self.address}'")

    def update_tcp_port(self, tcp_port: int):
        self.tcp_port = tcp_port

    @property
    def node_id(self) -> bytes:
        return self._node_id

    def compact_address_udp(self) -> bytearray:
        return make_compact_address(self.node_id, self.address, self.udp_port)

    def compact_address_tcp(self) -> bytearray:
        return make_compact_address(self.node_id, self.address, self.tcp_port)

    def compact_ip(self):
        return make_compact_ip(self.address)

    def __str__(self):
        return f"{self.__class__.__name__}({self.node_id.hex()[:8]}@{self.address}:{self.udp_port}-{self.tcp_port})"
