import ipaddress
import typing
import binascii
import asyncio
import logging
from binascii import hexlify
from functools import reduce
from lbrynet import conf
from lbrynet.dht import constants
from lbrynet.dht.error import RemoteException
from lbrynet.dht.serialization.datagram import RequestDatagram

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from lbrynet.blob_exchange.client import BlobExchangeClientProtocol
    from lbrynet.dht.protocol.protocol import KademliaProtocol
    from lbrynet.blob.blob_file import BlobFile


log = logging.getLogger(__name__)


def is_valid_ipv4(address):
    try:
        ip = ipaddress.ip_address(address)
        return ip.version == 4
    except ipaddress.AddressValueError:
        return False


class Peer:
    def __init__(self, loop: asyncio.BaseEventLoop, peer_manager, address: str, node_id: typing.Optional[bytes] = None,
                 udp_port: typing.Optional[int] = None, first_contacted: typing.Optional[int] = None,
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
        self.udp_port = udp_port
        self.tcp_port = tcp_port
        self.first_contacted = first_contacted
        self.last_replied = None
        self.last_requested = None
        self.protocol_version = 1
        self._token = (None, 0)  # token, timestamp

        self.tcp_last_down = None
        self.blob_score = 0
        self.blob_request_lock = asyncio.Lock(loop=self.loop)
        self.blob_exchange_protocol_connections: typing.Dict['BlobFile', asyncio.Future] = {}

    def update_tcp_port(self, tcp_port: int):
        self.tcp_port = tcp_port

    def update_udp_port(self, udp_port: int):
        self.udp_port = udp_port

    def update_token(self, token):
        self._token = token, self.loop.time() if token else 0

    @property
    def token(self) -> typing.Optional[bytes]:
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
        return self.peer_manager._rpc_failures.get((self.address, self.udp_port), [])

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
        return (self.node_id, self.address, self.udp_port) == (other.node_id, other.address, other.udp_port)

    def __hash__(self):
        return hash((self.node_id, self.address, self.udp_port))

    def compact_ip(self) -> bytearray:
        return reduce(lambda buff, x: buff + bytearray([int(x)]), self.address.split('.'), bytearray())

    def compact_address_tcp(self) -> bytearray:
        if not 0 <= self.tcp_port <= 65536:
            raise TypeError(f'Invalid port: {self.tcp_port}')
        return self.compact_ip() + self.tcp_port.to_bytes(2, 'big') + self.node_id

    def compact_address_udp(self) -> bytearray:
        if not 0 <= self.udp_port <= 65536:
            raise TypeError(f'Invalid port: {self.udp_port}')
        return self.compact_ip() + self.udp_port.to_bytes(2, 'big') + self.node_id

    def set_id(self, node_id):
        if not self._node_id:
            self._node_id = node_id

    def update_last_replied(self):
        self.last_replied = int(self.loop.time())

    def update_last_requested(self):
        self.last_requested = int(self.loop.time())

    def update_last_failed(self):
        failures = self.peer_manager._rpc_failures.get((self.address, self.udp_port), [])
        failures.append(self.loop.time())
        self.peer_manager._rpc_failures[(self.address, self.udp_port)] = failures
        if not self.contact_is_good:
            log.debug("remove %s:%i from routing (%i failures)", self.address, self.udp_port, len(failures))
            self.peer_manager.dht_protocol.routing_table.remove_peer(self)

    def update_protocol_version(self, version):
        self.protocol_version = version

    def __str__(self):
        return f"{'blob peer' if not self.node_id else binascii.hexlify(self.node_id).decode()[:8]} @ " \
            f"{self.address} udp:{self.udp_port}/tcp:{self.tcp_port}"

    # DHT RPC functions
    async def _send_kademlia_rpc(self, datagram: RequestDatagram):
        try:
            response_fut = asyncio.Future(loop=self.loop)
            self.peer_manager.dht_protocol.send(self, datagram, (self.address, self.udp_port), response_fut)
            result = await asyncio.wait_for(response_fut, conf.settings['node_rpc_timeout'], loop=self.loop)
            log.debug('%s:%i replied to %s', self.address, self.udp_port, datagram.method)
            self.update_last_replied()
            return result
        except asyncio.CancelledError as err:
            log.debug("dht cancelled")
            raise err
        except asyncio.TimeoutError as err:
            self.update_last_failed()
            log.debug("dht timeout")
            raise err
        except RemoteException as err:
            self.update_last_failed()
            raise RemoteException(err)
        except Exception as err:
            log.exception("error sending %s to %s:%i", datagram.method, self.address, self.udp_port)
            raise err

    async def ping(self) -> bytes:
        assert self.peer_manager.dht_protocol is not None
        return await self._send_kademlia_rpc(RequestDatagram.make_ping(self.peer_manager.dht_protocol.node_id))

    async def store(self, blob_hash: bytes) -> bytes:
        assert len(blob_hash) == constants.hash_bits // 8
        assert self.peer_manager.dht_protocol is not None
        assert self.peer_manager.dht_protocol.peer_port is not None and \
                (0 < self.peer_manager.dht_protocol.peer_port < 65535)
        assert self.token is not None

        request = RequestDatagram.make_store(self.peer_manager.dht_protocol.node_id, blob_hash, self.token,
                                             self.peer_manager.dht_protocol.peer_port)
        return await self._send_kademlia_rpc(request)

    async def find_node(self, key: bytes) -> typing.List[typing.Tuple[bytes, str, int]]:
        assert len(key) == constants.hash_bits // 8
        assert self.peer_manager.dht_protocol is not None
        triples = await self._send_kademlia_rpc(
            RequestDatagram.make_find_node(self.peer_manager.dht_protocol.node_id, key)
        )
        return [(node_id, address.decode(), udp_port) for node_id, address, udp_port in triples]

    async def find_value(self, key: bytes) -> typing.Union[typing.Dict]:
        """
        :return: {
            b'token': <token bytes>,
            b'contacts': [(node_id, address, udp_port), ...]
            <key bytes>: [<blob_peer_compact_address, ...]
        }
        """
        assert len(key) == constants.hash_bits // 8
        assert self.peer_manager.dht_protocol is not None
        result = await self._send_kademlia_rpc(
            RequestDatagram.make_find_value(self.peer_manager.dht_protocol.node_id, key)
        )
        if b'token' in result:
            self.update_token(result[b'token'])
        else:
            log.warning("failed to update token for %s", self)
        return result

    # Blob exchange functions

    async def _request_blob(self, blob: 'BlobFile', protocol: 'BlobExchangeClientProtocol',
                            peer_connect_timeout: float) -> bool:
        fut = self.blob_exchange_protocol_connections[blob]
        connected = protocol.transport is not None
        try:

            if blob.get_is_verified():
                log.info("already verified")
                fut.set_result(False)
            else:
                if not connected:
                    await asyncio.wait_for(self.loop.create_connection(lambda: protocol, self.address, self.tcp_port),
                                           peer_connect_timeout, loop=self.loop)
                    self.report_tcp_up()
                    log.info("connected to %s:%i", self.address, self.tcp_port)
                log.info("download blob from %s:%i", self.address, self.tcp_port)
                success = await protocol.download_blob(blob)
                if success:
                    log.info("downloaded blob from %s:%i", self.address, self.tcp_port)
                else:
                    log.info("failed to download blob from %s:%i", self.address, self.tcp_port)
                fut.set_result(success)
        except asyncio.CancelledError:
            fut.set_result(False)
            return await fut
        except (asyncio.TimeoutError, ConnectionRefusedError, ConnectionAbortedError, OSError) as err:
            log.warning("%s:%i is down, %s %s", self.address, self.tcp_port, str(type(err)), str(err))
            self.report_tcp_down()
            fut.set_result(False)
        return await fut

    async def request_blob(self, blob: 'BlobFile', protocol: 'BlobExchangeClientProtocol',
                           peer_connect_timeout: float) -> bool:
        if blob in self.blob_exchange_protocol_connections:
            return await self.blob_exchange_protocol_connections[blob]
        if blob.get_is_verified():
            return False
        async with self.blob_request_lock:
            fut = asyncio.Future(loop=self.loop)
            self.blob_exchange_protocol_connections[blob] = fut
        try:
            return await self._request_blob(blob, protocol, peer_connect_timeout)
        finally:
            async with self.blob_request_lock:
                if blob in self.blob_exchange_protocol_connections:
                    del self.blob_exchange_protocol_connections[blob]

    def report_tcp_down(self):
        self.tcp_last_down = self.loop.time()

    def report_tcp_up(self):
        self.tcp_last_down = None

    def update_score(self, score_change):
        self.blob_score += score_change


class PeerManager:
    def __init__(self, loop: asyncio.BaseEventLoop):
        self._loop = loop
        self._contacts: typing.Dict[typing.Tuple[bytes, str, int], Peer] = {}
        self._rpc_failures = {}
        self._blob_peers = {}
        self._dht_protocol: 'KademliaProtocol' = None

    def register_dht_protocol(self, protocol: 'KademliaProtocol'):
        self._dht_protocol = protocol

    @property
    def dht_protocol(self) -> typing.Optional['KademliaProtocol']:
        return self._dht_protocol

    def get_peer(self, address: str, node_id: typing.Optional[bytes] = None, udp_port: typing.Optional[int] = None,
                 tcp_port: typing.Optional[int] = None) -> Peer:
        assert not all((udp_port is None, tcp_port is None))
        for contact in self._contacts.values():
            if address != contact.address:
                continue
            if node_id and contact.node_id != node_id:
                continue
            if udp_port and contact.udp_port and contact.udp_port != udp_port:
                continue
            if udp_port and not contact.udp_port:
                contact.update_udp_port(udp_port)
            if tcp_port and tcp_port != contact.tcp_port:
                contact.update_tcp_port(tcp_port)
            return contact

    def make_peer(self, address: str, node_id: typing.Optional[bytes] = None, udp_port: typing.Optional[int] = None,
                  first_contacted: typing.Optional[int] = None, tcp_port: typing.Optional[int] = None) -> Peer:
        contact = self.get_peer(address, node_id, udp_port, tcp_port)
        if contact:
            if tcp_port:
                contact.update_tcp_port(tcp_port)
            return contact
        contact = Peer(
            self._loop, self, address, node_id, udp_port, first_contacted, tcp_port
        )
        self._contacts[(node_id, address, udp_port)] = contact
        return contact

    def make_tcp_peer_from_compact_address(self, compact_address: bytes) -> Peer:
        host = "{}.{}.{}.{}".format(*compact_address[:4])
        tcp_port = int.from_bytes(compact_address[4:6], 'big')
        peer_node_id = compact_address[6:]
        return self.make_peer(host, node_id=peer_node_id, tcp_port=tcp_port)

    def is_ignored(self, origin_tuple) -> bool:
        failed_rpc_count = len(self._prune_failures(origin_tuple))
        return failed_rpc_count > constants.rpc_attempts

    def _prune_failures(self, origin_tuple) -> typing.List:
        # Prunes recorded failures to the last time window of attempts
        pruning_limit = self._loop.time() - constants.rpc_attempts_pruning_window
        pruned = list(filter(lambda t: t >= pruning_limit, self._rpc_failures.get(origin_tuple, [])))
        self._rpc_failures[origin_tuple] = pruned
        return pruned
