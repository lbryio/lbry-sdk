import ipaddress
import typing
import asyncio
from binascii import hexlify
from collections import defaultdict
from functools import reduce
from lbrynet.dht import constants
from lbrynet.dht.serialization.datagram import RequestDatagram, REQUEST_TYPE


def is_valid_ipv4(address):
    try:
        ip = ipaddress.ip_address(address)
        return ip.version == 4
    except ipaddress.AddressValueError:
        return False


class Peer:
    def __init__(self, loop: asyncio.BaseEventLoop, peer_manager, address: str, node_id: typing.Optional[bytes],
                 udp_port: typing.Optional[int] = None, dht_protocol=None, first_contacted: typing.Optional[int] = None,
                 tcp_port: typing.Optional[int] = None):
        if node_id is not None:
            if not len(node_id) == constants.hash_length:
                raise ValueError("invalid node_id: {}".format(hexlify(node_id).decode()))
        if udp_port is not None and not 0 <= udp_port <= 65536:
            raise ValueError("invalid udp port")
        if tcp_port and not 0 <= tcp_port <= 65536:
            raise ValueError("invalid tcp port")
        if not is_valid_ipv4(address):
            raise ValueError("invalid ip address")
        self.loop = loop
        self.peer_manager: PeerManager = peer_manager
        self._node_id = node_id
        self.address = address
        self.port = udp_port
        self.tcp_port = tcp_port
        self.dht_protocol = dht_protocol
        self.first_contacted = first_contacted
        self.last_replied = None
        self.last_requested = None
        self.protocol_version = 0
        self._token = (None, 0)  # token, timestamp

        self.down_count = 0
        # Number of successful connections (with full protocol completion) to this peer
        self.success_count = 0
        self.score = 0
        self.stats = defaultdict(float)  # {string stat_type, float count}

    def update_tcp_port(self, tcp_port: int):
        self.tcp_port = tcp_port

    def update_token(self, token):
        self._token = token, self.loop.time() if token else 0

    @property
    def token(self):
        # expire the token 1 minute early to be safe
        if self._token[1] + constants.token_secret_refresh_interval - 60 > self.loop.time():
            return self._token[0]

    @property
    def last_interacted(self):
        return max(self.last_requested or 0, self.last_replied or 0, self.last_failed or 0)

    @property
    def node_id(self):
        return self._node_id

    def log_id(self, short=True):
        if not self.node_id:
            return "not initialized"
        id_hex = hexlify(self.node_id)
        return id_hex if not short else id_hex[:8]

    @property
    def failed_rpcs(self):
        return len(self.failures)

    @property
    def last_failed(self):
        return (self.failures or [None])[-1]

    @property
    def failures(self):
        return self.peer_manager._rpc_failures.get((self.address, self.port), [])

    @property
    def contact_is_good(self):
        """
        :return: False if contact is bad, None if contact is unknown, or True if contact is good
        """
        failures = self.failures
        now = self.loop.time()
        delay = constants.check_refresh_interval

        if failures:
            if self.last_replied and len(failures) >= 2 and self.last_replied < failures[-2]:
                return False
            elif self.last_replied and len(failures) >= 2 and self.last_replied > failures[-2]:
                pass  # handled below
            elif len(failures) >= 2:
                return False

        if self.last_replied and self.last_replied > now - delay:
            return True
        if self.last_replied and self.last_requested and self.last_requested > now - delay:
            return True
        return None

    def __eq__(self, other):
        if not isinstance(other, Peer):
            raise TypeError("invalid type to compare with Contact: %s" % str(type(other)))
        return (self.node_id, self.address, self.port) == (other.node_id, other.address, other.port)

    def __hash__(self):
        return hash((self.node_id, self.address, self.port))

    def compact_ip(self):
        compact_ip = reduce(
            lambda buff, x: buff + bytearray([int(x)]), self.address.split('.'), bytearray())
        return compact_ip

    def set_id(self, node_id):
        if not self._node_id:
            self._node_id = node_id

    def update_last_replied(self):
        self.last_replied = int(self.loop.time())

    def update_last_requested(self):
        self.last_requested = int(self.loop.time())

    def update_last_failed(self):
        failures = self.peer_manager._rpc_failures.get((self.address, self.port), [])
        failures.append(self.loop.time())
        self.peer_manager._rpc_failures[(self.address, self.port)] = failures

    def update_protocol_version(self, version):
        self.protocol_version = version

    def __str__(self):
        return '<%s.%s object; IP address: %s, UDP port: %d>' % (
            self.__module__, self.__class__.__name__, self.address, self.port)

    # DHT RPC functions

    async def ping(self) -> bytes:
        assert self.dht_protocol is not None
        packet = RequestDatagram(
            REQUEST_TYPE, constants.generate_id()[:constants.rpc_id_length], self.dht_protocol.node_id, 'ping', []
        )
        return await asyncio.wait_for(
            asyncio.ensure_future(self.dht_protocol.send(self, packet, (self.address, self.port))),
            constants.rpc_timeout
        )

    async def store(self, blob_hash: bytes, token: bytes, port: int, original_publisher_id: bytes, age: int) -> bytes:
        assert self.dht_protocol is not None
        packet = RequestDatagram(
            REQUEST_TYPE, constants.generate_id()[:constants.rpc_id_length], self.dht_protocol.node_id, 'store',
            [blob_hash, token, port, original_publisher_id, age]
        )
        return await asyncio.wait_for(
            asyncio.ensure_future(self.dht_protocol.send(self, packet, (self.address, self.port))),
            constants.rpc_timeout
        )

    async def find_node(self, key: bytes) -> typing.List[typing.Tuple[bytes, str, int]]:
        assert self.dht_protocol is not None
        packet = RequestDatagram(
            REQUEST_TYPE, constants.generate_id()[:constants.rpc_id_length], self.dht_protocol.node_id, 'findNode',
            [key]
        )
        return await asyncio.wait_for(
            asyncio.ensure_future(self.dht_protocol.send(self, packet, (self.address, self.port))),
            constants.rpc_timeout
        )

    async def find_value(self, key: bytes) -> typing.Union[typing.List[typing.Tuple[bytes, str, int]], typing.Dict]:
        assert self.dht_protocol is not None
        packet = RequestDatagram(
            REQUEST_TYPE, constants.generate_id()[:constants.rpc_id_length], self.dht_protocol.node_id, 'findValue',
            [key]
        )
        return await asyncio.wait_for(
            asyncio.ensure_future(self.dht_protocol.send(self, packet, (self.address, self.port))),
            constants.rpc_timeout
        )

    # Blob functions, clean up

    @staticmethod
    def is_available():
        # if self.attempt_connection_at is None or utils.today() > self.attempt_connection_at:
        #     return True
        return False

    def report_up(self):
        self.down_count = 0
        # self.attempt_connection_at = None

    def report_success(self):
        self.success_count += 1

    def report_down(self):
        self.down_count += 1
        # timeout_time = datetime.timedelta(seconds=60 * self.down_count)
        # self.attempt_connection_at = utils.today() + timeout_time

    def update_score(self, score_change):
        self.score += score_change

    def update_stats(self, stat_type, count):
        self.stats[stat_type] += count


class PeerManager:
    def __init__(self, loop: asyncio.BaseEventLoop):

        self._loop = loop
        self._contacts = {}
        self._rpc_failures = {}
        self._blob_peers = {}

    def get_peer(self, node_id: bytes, address: str, udp_port: int) -> Peer:
        for contact in self._contacts.values():
            if contact.node_id == node_id and contact.address == address and contact.port == udp_port:
                return contact

    def make_peer(self, address: str, node_id: bytes, dht_protocol=None, udp_port: typing.Optional[int] = None,
                  first_contacted: typing.Optional[int] = None, tcp_port: typing.Optional[int] = None) -> Peer:
        contact = self.get_peer(node_id, address, udp_port)
        if contact:
            if tcp_port:
                contact.update_tcp_port(tcp_port)
            return contact
        contact = Peer(
            self._loop, self, address, node_id, udp_port, dht_protocol, first_contacted, tcp_port
        )
        self._contacts[(node_id, address, udp_port)] = contact
        return contact

    def is_ignored(self, origin_tuple) -> bool:
        failed_rpc_count = len(self._prune_failures(origin_tuple))
        return failed_rpc_count > constants.rpc_attempts

    def _prune_failures(self, origin_tuple) -> typing.List:
        # Prunes recorded failures to the last time window of attempts
        pruning_limit = self._loop.time() - constants.rpc_attempts_pruning_window
        pruned = list(filter(lambda t: t >= pruning_limit, self._rpc_failures.get(origin_tuple, [])))
        self._rpc_failures[origin_tuple] = pruned
        return pruned
