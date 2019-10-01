import typing
import asyncio
import logging
import ipaddress
from binascii import hexlify
from dataclasses import dataclass, field
from functools import lru_cache

from lbry.dht import constants
from lbry.dht.serialization.datagram import make_compact_address, make_compact_ip, decode_compact_address

log = logging.getLogger(__name__)


@lru_cache(1024)
def make_kademlia_peer(node_id: typing.Optional[bytes], address: typing.Optional[str],
                       udp_port: typing.Optional[int] = None,
                       tcp_port: typing.Optional[int] = None) -> 'KademliaPeer':
    return KademliaPeer(address, node_id, udp_port, tcp_port=tcp_port)


def is_valid_ipv4(address):
    try:
        ip = ipaddress.ip_address(address)
        return ip.version == 4
    except ipaddress.AddressValueError:
        return False


class PeerManager:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._rpc_failures: typing.Dict[
            typing.Tuple[str, int], typing.Tuple[typing.Optional[float], typing.Optional[float]]
        ] = {}
        self._last_replied: typing.Dict[typing.Tuple[str, int], float] = {}
        self._last_sent: typing.Dict[typing.Tuple[str, int], float] = {}
        self._last_requested: typing.Dict[typing.Tuple[str, int], float] = {}
        self._node_id_mapping: typing.Dict[typing.Tuple[str, int], bytes] = {}
        self._node_id_reverse_mapping: typing.Dict[bytes, typing.Tuple[str, int]] = {}
        self._node_tokens: typing.Dict[bytes, (float, bytes)] = {}

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
        if ts and ts > self._loop.time() - constants.token_secret_refresh_interval:
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

    def prune(self):  # TODO: periodically call this
        now = self._loop.time()
        to_pop = []
        for (address, udp_port), (_, last_failure) in self._rpc_failures.items():
            if last_failure and last_failure < now - constants.rpc_attempts_pruning_window:
                to_pop.append((address, udp_port))
        while to_pop:
            del self._rpc_failures[to_pop.pop()]
        to_pop = []
        for node_id, (age, token) in self._node_tokens.items():
            if age < now - constants.token_secret_refresh_interval:
                to_pop.append(node_id)
        while to_pop:
            del self._node_tokens[to_pop.pop()]

    def contact_triple_is_good(self, node_id: bytes, address: str, udp_port: int):
        """
        :return: False if peer is bad, None if peer is unknown, or True if peer is good
        """

        delay = self._loop.time() - constants.check_refresh_interval

        # fixme: find a way to re-enable that without breaking other parts
        #if node_id not in self._node_id_reverse_mapping or (address, udp_port) not in self._node_id_mapping:
        #    return
        #addr_tup = (address, udp_port)
        #if self._node_id_reverse_mapping[node_id] != addr_tup or self._node_id_mapping[addr_tup] != node_id:
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

    def decode_tcp_peer_from_compact_address(self, compact_address: bytes) -> 'KademliaPeer':
        node_id, address, tcp_port = decode_compact_address(compact_address)
        return make_kademlia_peer(node_id, address, udp_port=None, tcp_port=tcp_port)


@dataclass(unsafe_hash=True)
class KademliaPeer:
    address: str = field(hash=True)
    _node_id: typing.Optional[bytes] = field(hash=True)
    udp_port: typing.Optional[int] = field(hash=True)
    tcp_port: typing.Optional[int] = field(compare=False, hash=False)
    protocol_version: typing.Optional[int] = field(default=1, compare=False, hash=False)

    def __post_init__(self):
        if self._node_id is not None:
            if not len(self._node_id) == constants.hash_length:
                raise ValueError("invalid node_id: {}".format(hexlify(self._node_id).decode()))
        if self.udp_port is not None and not 1 <= self.udp_port <= 65535:
            raise ValueError("invalid udp port")
        if self.tcp_port is not None and not 1 <= self.tcp_port <= 65535:
            raise ValueError("invalid tcp port")
        if not is_valid_ipv4(self.address):
            raise ValueError("invalid ip address")

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
