import logging
import socket
import functools
import hashlib
import asyncio
import time
import typing
import random
from asyncio.protocols import DatagramProtocol
from asyncio.transports import DatagramTransport

from prometheus_client import Gauge, Counter, Histogram

from lbry.dht import constants
from lbry.dht.serialization.bencoding import DecodeError
from lbry.dht.serialization.datagram import decode_datagram, ErrorDatagram, ResponseDatagram, RequestDatagram
from lbry.dht.serialization.datagram import RESPONSE_TYPE, ERROR_TYPE, PAGE_KEY
from lbry.dht.error import RemoteException, TransportNotConnected
from lbry.dht.protocol.routing_table import TreeRoutingTable
from lbry.dht.protocol.data_store import DictDataStore
from lbry.dht.peer import make_kademlia_peer

if typing.TYPE_CHECKING:
    from lbry.dht.peer import PeerManager, KademliaPeer

log = logging.getLogger(__name__)


OLD_PROTOCOL_ERRORS = {
    "findNode() takes exactly 2 arguments (5 given)": "0.19.1",
    "findValue() takes exactly 2 arguments (5 given)": "0.19.1"
}


class KademliaRPC:
    stored_blob_metric = Gauge(
        "stored_blobs", "Number of blobs announced by other peers", namespace="dht_node",
        labelnames=("scope",),
    )

    def __init__(self, protocol: 'KademliaProtocol', loop: asyncio.AbstractEventLoop, peer_port: int = 3333):
        self.protocol = protocol
        self.loop = loop
        self.peer_port = peer_port
        self.old_token_secret: bytes = None
        self.token_secret = constants.generate_id()

    def compact_address(self):
        compact_ip = functools.reduce(lambda buff, x: buff + bytearray([int(x)]),
                                      self.protocol.external_ip.split('.'), bytearray())
        compact_port = self.peer_port.to_bytes(2, 'big')
        return compact_ip + compact_port + self.protocol.node_id

    @staticmethod
    def ping():
        return b'pong'

    def store(self, rpc_contact: 'KademliaPeer', blob_hash: bytes, token: bytes, port: int) -> bytes:
        if len(blob_hash) != constants.HASH_BITS // 8:
            raise ValueError(f"invalid length of blob hash: {len(blob_hash)}")
        if not 0 < port < 65535:
            raise ValueError(f"invalid tcp port: {port}")
        rpc_contact.update_tcp_port(port)
        if not self.verify_token(token, rpc_contact.compact_ip()):
            if self.loop.time() - self.protocol.started_listening_time < constants.TOKEN_SECRET_REFRESH_INTERVAL:
                pass
            else:
                raise ValueError("Invalid token")
        self.protocol.data_store.add_peer_to_blob(
            rpc_contact, blob_hash
        )
        self.stored_blob_metric.labels("global").set(len(self.protocol.data_store))
        return b'OK'

    def find_node(self, rpc_contact: 'KademliaPeer', key: bytes) -> typing.List[typing.Tuple[bytes, str, int]]:
        if len(key) != constants.HASH_LENGTH:
            raise ValueError("invalid contact node_id length: %i" % len(key))

        contacts = self.protocol.routing_table.find_close_peers(key, sender_node_id=rpc_contact.node_id)
        contact_triples = []
        for contact in contacts[:constants.K * 2]:
            contact_triples.append((contact.node_id, contact.address, contact.udp_port))
        return contact_triples

    def find_value(self, rpc_contact: 'KademliaPeer', key: bytes, page: int = 0):
        page = page if page > 0 else 0

        if len(key) != constants.HASH_LENGTH:
            raise ValueError("invalid blob_exchange hash length: %i" % len(key))

        response = {
            b'token': self.make_token(rpc_contact.compact_ip()),
        }

        if not page:
            response[b'contacts'] = self.find_node(rpc_contact, key)[:constants.K]

        if self.protocol.protocol_version:
            response[b'protocolVersion'] = self.protocol.protocol_version

        # get peers we have stored for this blob_exchange
        peers = [
            peer.compact_address_tcp()
            for peer in self.protocol.data_store.get_peers_for_blob(key)
            if not rpc_contact.tcp_port or peer.compact_address_tcp() != rpc_contact.compact_address_tcp()
        ]
        # if we don't have k storing peers to return and we have this hash locally, include our contact information
        if len(peers) < constants.K and key.hex() in self.protocol.data_store.completed_blobs:
            peers.append(self.compact_address())
        if not peers:
            response[PAGE_KEY] = 0
        else:
            response[PAGE_KEY] = (len(peers) // (constants.K + 1)) + 1  # how many pages of peers we have for the blob
        if len(peers) > constants.K:
            random.Random(self.protocol.node_id).shuffle(peers)
        if page * constants.K < len(peers):
            response[key] = peers[page * constants.K:page * constants.K + constants.K]
        return response

    def refresh_token(self):  # TODO: this needs to be called periodically
        self.old_token_secret = self.token_secret
        self.token_secret = constants.generate_id()

    def make_token(self, compact_ip):
        h = hashlib.new('sha384')
        h.update(self.token_secret + compact_ip)
        return h.digest()

    def verify_token(self, token, compact_ip):
        h = hashlib.new('sha384')
        h.update(self.token_secret + compact_ip)
        if self.old_token_secret and not token == h.digest():  # TODO: why should we be accepting the previous token?
            h = hashlib.new('sha384')
            h.update(self.old_token_secret + compact_ip)
            if not token == h.digest():
                return False
        return True


class RemoteKademliaRPC:
    """
    Encapsulates RPC calls to remote Peers
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, peer_tracker: 'PeerManager', protocol: 'KademliaProtocol',
                 peer: 'KademliaPeer'):
        self.loop = loop
        self.peer_tracker = peer_tracker
        self.protocol = protocol
        self.peer = peer

    async def ping(self) -> bytes:
        """
        :return: b'pong'
        """
        response = await self.protocol.send_request(
            self.peer, RequestDatagram.make_ping(self.protocol.node_id)
        )
        return response.response

    async def store(self, blob_hash: bytes) -> bytes:
        """
        :param blob_hash: blob hash as bytes
        :return: b'OK'
        """
        if len(blob_hash) != constants.HASH_BITS // 8:
            raise ValueError(f"invalid length of blob hash: {len(blob_hash)}")
        if not self.protocol.peer_port or not 0 < self.protocol.peer_port < 65535:
            raise ValueError(f"invalid tcp port: {self.protocol.peer_port}")
        token = self.peer_tracker.get_node_token(self.peer.node_id)
        if not token:
            find_value_resp = await self.find_value(blob_hash)
            token = find_value_resp[b'token']
        response = await self.protocol.send_request(
            self.peer, RequestDatagram.make_store(self.protocol.node_id, blob_hash, token, self.protocol.peer_port)
        )
        return response.response

    async def find_node(self, key: bytes) -> typing.List[typing.Tuple[bytes, str, int]]:
        """
        :return: [(node_id, address, udp_port), ...]
        """
        if len(key) != constants.HASH_BITS // 8:
            raise ValueError(f"invalid length of find node key: {len(key)}")
        response = await self.protocol.send_request(
            self.peer, RequestDatagram.make_find_node(self.protocol.node_id, key)
        )
        return [(node_id, address.decode(), udp_port) for node_id, address, udp_port in response.response]

    async def find_value(self, key: bytes, page: int = 0) -> typing.Union[typing.Dict]:
        """
        :return: {
            b'token': <token bytes>,
            b'contacts': [(node_id, address, udp_port), ...]
            <key bytes>: [<blob_peer_compact_address, ...]
        }
        """
        if len(key) != constants.HASH_BITS // 8:
            raise ValueError(f"invalid length of find value key: {len(key)}")
        response = await self.protocol.send_request(
            self.peer, RequestDatagram.make_find_value(self.protocol.node_id, key, page=page)
        )
        self.peer_tracker.update_token(self.peer.node_id, response.response[b'token'])
        return response.response


class PingQueue:
    def __init__(self, loop: asyncio.AbstractEventLoop, protocol: 'KademliaProtocol'):
        self._loop = loop
        self._protocol = protocol
        self._pending_contacts: typing.Dict['KademliaPeer', float] = {}
        self._process_task: asyncio.Task = None
        self._running = False
        self._running_pings: typing.Set[asyncio.Task] = set()
        self._default_delay = constants.MAYBE_PING_DELAY

    @property
    def running(self):
        return self._running

    def enqueue_maybe_ping(self, *peers: 'KademliaPeer', delay: typing.Optional[float] = None):
        delay = delay if delay is not None else self._default_delay
        now = self._loop.time()
        for peer in peers:
            if peer not in self._pending_contacts or now + delay < self._pending_contacts[peer]:
                self._pending_contacts[peer] = delay + now

    def maybe_ping(self, peer: 'KademliaPeer'):
        async def ping_task():
            try:
                if self._protocol.peer_manager.peer_is_good(peer):
                    if not self._protocol.routing_table.get_peer(peer.node_id):
                        self._protocol.add_peer(peer)
                    return
                await self._protocol.get_rpc_peer(peer).ping()
            except (asyncio.TimeoutError, RemoteException):
                pass

        task = self._loop.create_task(ping_task())
        task.add_done_callback(lambda _: None if task not in self._running_pings else self._running_pings.remove(task))
        self._running_pings.add(task)

    async def _process(self):  # send up to 1 ping per second
        while True:
            enqueued = list(self._pending_contacts.keys())
            now = self._loop.time()
            for peer in enqueued:
                if self._pending_contacts[peer] <= now:
                    del self._pending_contacts[peer]
                    self.maybe_ping(peer)
                    break
            await asyncio.sleep(1, loop=self._loop)

    def start(self):
        assert not self._running
        self._running = True
        if not self._process_task:
            self._process_task = self._loop.create_task(self._process())

    def stop(self):
        assert self._running
        self._running = False
        if self._process_task:
            self._process_task.cancel()
            self._process_task = None
        while self._running_pings:
            self._running_pings.pop().cancel()


class KademliaProtocol(DatagramProtocol):
    request_sent_metric = Counter(
        "request_sent", "Number of requests send from DHT RPC protocol", namespace="dht_node",
        labelnames=("method",),
    )
    request_success_metric = Counter(
        "request_success", "Number of successful requests", namespace="dht_node",
        labelnames=("method",),
    )
    request_error_metric = Counter(
        "request_error", "Number of errors returned from request to other peers", namespace="dht_node",
        labelnames=("method",),
    )
    HISTOGRAM_BUCKETS = (
        .005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 3.0, 3.5, 4.0, 4.50, 5.0, 5.50, 6.0, float('inf')
    )
    response_time_metric = Histogram(
        "response_time", "Response times of DHT RPC requests", namespace="dht_node", buckets=HISTOGRAM_BUCKETS,
        labelnames=("method",)
    )
    received_request_metric = Counter(
        "received_request", "Number of received DHT RPC requests", namespace="dht_node",
        labelnames=("method",),
    )

    def __init__(self, loop: asyncio.AbstractEventLoop, peer_manager: 'PeerManager', node_id: bytes, external_ip: str,
                 udp_port: int, peer_port: int, rpc_timeout: float = constants.RPC_TIMEOUT,
                 split_buckets_under_index: int = constants.SPLIT_BUCKETS_UNDER_INDEX):
        self.peer_manager = peer_manager
        self.loop = loop
        self.node_id = node_id
        self.external_ip = external_ip
        self.udp_port = udp_port
        self.peer_port = peer_port
        self.is_seed_node = False
        self.partial_messages: typing.Dict[bytes, typing.Dict[bytes, bytes]] = {}
        self.sent_messages: typing.Dict[bytes, typing.Tuple['KademliaPeer', asyncio.Future, RequestDatagram]] = {}
        self.protocol_version = constants.PROTOCOL_VERSION
        self.started_listening_time = 0
        self.transport: DatagramTransport = None
        self.old_token_secret = constants.generate_id()
        self.token_secret = constants.generate_id()
        self.routing_table = TreeRoutingTable(self.loop, self.peer_manager, self.node_id, split_buckets_under_index)
        self.data_store = DictDataStore(self.loop, self.peer_manager)
        self.ping_queue = PingQueue(self.loop, self)
        self.node_rpc = KademliaRPC(self, self.loop, self.peer_port)
        self.rpc_timeout = rpc_timeout
        self._split_lock = asyncio.Lock(loop=self.loop)
        self._to_remove: typing.Set['KademliaPeer'] = set()
        self._to_add: typing.Set['KademliaPeer'] = set()
        self._wakeup_routing_task = asyncio.Event(loop=self.loop)
        self.maintaing_routing_task: typing.Optional[asyncio.Task] = None

    @functools.lru_cache(128)
    def get_rpc_peer(self, peer: 'KademliaPeer') -> RemoteKademliaRPC:
        return RemoteKademliaRPC(self.loop, self.peer_manager, self, peer)

    def start(self):
        self.maintaing_routing_task = self.loop.create_task(self.routing_table_task())

    def stop(self):
        if self.maintaing_routing_task:
            self.maintaing_routing_task.cancel()
        if self.transport:
            self.disconnect()

    def disconnect(self):
        self.transport.close()

    def connection_made(self, transport: DatagramTransport):
        self.transport = transport

    def connection_lost(self, exc):
        self.stop()

    @staticmethod
    def _migrate_incoming_rpc_args(peer: 'KademliaPeer', method: bytes, *args) -> typing.Tuple[typing.Tuple,
                                                                                               typing.Dict]:
        if method == b'store' and peer.protocol_version == 0:
            if isinstance(args[1], dict):
                blob_hash = args[0]
                token = args[1].pop(b'token', None)
                port = args[1].pop(b'port', -1)
                original_publisher_id = args[1].pop(b'lbryid', None)
                age = 0
                return (blob_hash, token, port, original_publisher_id, age), {}
        return args, {}

    async def _add_peer(self, peer: 'KademliaPeer'):
        async def probe(some_peer: 'KademliaPeer'):
            rpc_peer = self.get_rpc_peer(some_peer)
            await rpc_peer.ping()
        return await self.routing_table.add_peer(peer, probe)

    def add_peer(self, peer: 'KademliaPeer'):
        if peer.node_id == self.node_id:
            return False
        self._to_add.add(peer)
        self._wakeup_routing_task.set()

    def remove_peer(self, peer: 'KademliaPeer'):
        self._to_remove.add(peer)
        self._wakeup_routing_task.set()

    async def routing_table_task(self):
        while True:
            while self._to_remove:
                async with self._split_lock:
                    peer = self._to_remove.pop()
                    self.routing_table.remove_peer(peer)
            while self._to_add:
                async with self._split_lock:
                    await self._add_peer(self._to_add.pop())
            await asyncio.gather(self._wakeup_routing_task.wait(), asyncio.sleep(.1, loop=self.loop), loop=self.loop)
            self._wakeup_routing_task.clear()

    def _handle_rpc(self, sender_contact: 'KademliaPeer', message: RequestDatagram):
        assert sender_contact.node_id != self.node_id, (sender_contact.node_id.hex()[:8],
                                                        self.node_id.hex()[:8])
        method = message.method
        if method not in [b'ping', b'store', b'findNode', b'findValue']:
            raise AttributeError('Invalid method: %s' % message.method.decode())
        if message.args and isinstance(message.args[-1], dict) and b'protocolVersion' in message.args[-1]:
            # args don't need reformatting
            args, kwargs = tuple(message.args[:-1]), message.args[-1]
        else:
            args, kwargs = self._migrate_incoming_rpc_args(sender_contact, message.method, *message.args)
        log.debug("%s:%i RECV CALL %s %s:%i", self.external_ip, self.udp_port, message.method.decode(),
                  sender_contact.address, sender_contact.udp_port)

        if method == b'ping':
            result = self.node_rpc.ping()
        elif method == b'store':
            blob_hash, token, port, original_publisher_id, age = args[:5]  # pylint: disable=unused-variable
            result = self.node_rpc.store(sender_contact, blob_hash, token, port)
        else:
            key = args[0]
            page = kwargs.get(PAGE_KEY, 0)
            if method == b'findNode':
                result = self.node_rpc.find_node(sender_contact, key)
            else:
                assert method == b'findValue'
                result = self.node_rpc.find_value(sender_contact, key, page)

        self.send_response(
            sender_contact, ResponseDatagram(RESPONSE_TYPE, message.rpc_id, self.node_id, result),
        )

    def handle_request_datagram(self, address: typing.Tuple[str, int], request_datagram: RequestDatagram):
        # This is an RPC method request
        self.received_request_metric.labels(method=request_datagram.method).inc()
        self.peer_manager.report_last_requested(address[0], address[1])
        peer = self.routing_table.get_peer(request_datagram.node_id)
        if not peer:
            try:
                peer = make_kademlia_peer(request_datagram.node_id, address[0], address[1])
            except ValueError as err:
                log.warning("error replying to %s: %s", address[0], str(err))
                return
        try:
            self._handle_rpc(peer, request_datagram)
            # if the contact is not known to be bad (yet) and we haven't yet queried it, send it a ping so that it
            # will be added to our routing table if successful
            is_good = self.peer_manager.peer_is_good(peer)
            if is_good is None:
                self.ping_queue.enqueue_maybe_ping(peer)
            # only add a requesting contact to the routing table if it has replied to one of our requests
            elif is_good is True:
                self.add_peer(peer)
        except ValueError as err:
            log.debug("error raised handling %s request from %s:%i - %s(%s)",
                      request_datagram.method, peer.address, peer.udp_port, str(type(err)),
                      str(err))
            self.send_error(
                peer,
                ErrorDatagram(ERROR_TYPE, request_datagram.rpc_id, self.node_id, str(type(err)).encode(),
                              str(err).encode())
            )
        except Exception as err:
            log.warning("error raised handling %s request from %s:%i - %s(%s)",
                        request_datagram.method, peer.address, peer.udp_port, str(type(err)),
                        str(err))
            self.send_error(
                peer,
                ErrorDatagram(ERROR_TYPE, request_datagram.rpc_id, self.node_id, str(type(err)).encode(),
                              str(err).encode())
            )

    def handle_response_datagram(self, address: typing.Tuple[str, int], response_datagram: ResponseDatagram):
        # Find the message that triggered this response
        if response_datagram.rpc_id in self.sent_messages:
            peer, future, _ = self.sent_messages[response_datagram.rpc_id]
            if peer.address != address[0]:
                future.set_exception(
                    RemoteException(f"response from {address[0]}, expected {peer.address}")
                )
                return

            # We got a result from the RPC
            if peer.node_id == self.node_id:
                future.set_exception(RemoteException("node has our node id"))
                return
            elif response_datagram.node_id == self.node_id:
                future.set_exception(RemoteException("incoming message is from our node id"))
                return
            peer = make_kademlia_peer(response_datagram.node_id, address[0], address[1])
            self.peer_manager.report_last_replied(address[0], address[1])
            self.peer_manager.update_contact_triple(peer.node_id, address[0], address[1])
            if not future.cancelled():
                future.set_result(response_datagram)
                self.add_peer(peer)
            else:
                log.warning("%s:%i replied, but after we cancelled the request attempt",
                            peer.address, peer.udp_port)
        else:
            # If the original message isn't found, it must have timed out
            # TODO: we should probably do something with this...
            pass

    def handle_error_datagram(self, address, error_datagram: ErrorDatagram):
        # The RPC request raised a remote exception; raise it locally
        remote_exception = RemoteException(f"{error_datagram.exception_type}({error_datagram.response})")
        if error_datagram.rpc_id in self.sent_messages:
            peer, future, request = self.sent_messages.pop(error_datagram.rpc_id)
            if (peer.address, peer.udp_port) != address:
                future.set_exception(
                    RemoteException(
                        f"response from {address[0]}:{address[1]}, "
                        f"expected {peer.address}:{peer.udp_port}"
                    )
                )
                return
            error_msg = f"" \
                f"Error sending '{request.method}' to {peer.address}:{peer.udp_port}\n" \
                f"Args: {request.args}\n" \
                f"Raised: {str(remote_exception)}"
            if 'Invalid token' in error_msg:
                log.debug(error_msg)
            elif error_datagram.response not in OLD_PROTOCOL_ERRORS:
                log.warning(error_msg)
            else:
                log.debug(
                    "known dht protocol backwards compatibility error with %s:%i (lbrynet v%s)",
                    peer.address, peer.udp_port, OLD_PROTOCOL_ERRORS[error_datagram.response]
                )
            future.set_exception(remote_exception)
            return
        else:
            if error_datagram.response not in OLD_PROTOCOL_ERRORS:
                msg = f"Received error from {address[0]}:{address[1]}, but it isn't in response to a " \
                    f"pending request: {str(remote_exception)}"
                log.warning(msg)
            else:
                log.debug(
                    "known dht protocol backwards compatibility error with %s:%i (lbrynet v%s)",
                    address[0], address[1], OLD_PROTOCOL_ERRORS[error_datagram.response]
                )

    def datagram_received(self, datagram: bytes, address: typing.Tuple[str, int]) -> None:  # pylint: disable=arguments-renamed
        try:
            message = decode_datagram(datagram)
        except (ValueError, TypeError, DecodeError):
            self.peer_manager.report_failure(address[0], address[1])
            log.warning("Couldn't decode dht datagram from %s: %s", address, datagram.hex())
            return

        if isinstance(message, RequestDatagram):
            self.handle_request_datagram(address, message)
        elif isinstance(message, ErrorDatagram):
            self.handle_error_datagram(address, message)
        else:
            assert isinstance(message, ResponseDatagram), "sanity"
            self.handle_response_datagram(address, message)

    async def send_request(self, peer: 'KademliaPeer', request: RequestDatagram) -> ResponseDatagram:
        self._send(peer, request)
        response_fut = self.sent_messages[request.rpc_id][1]
        try:
            self.request_sent_metric.labels(method=request.method).inc()
            start = time.perf_counter()
            response = await asyncio.wait_for(response_fut, self.rpc_timeout)
            self.response_time_metric.labels(method=request.method).observe(time.perf_counter() - start)
            self.peer_manager.report_last_replied(peer.address, peer.udp_port)
            self.request_success_metric.labels(method=request.method).inc()
            return response
        except asyncio.CancelledError:
            if not response_fut.done():
                response_fut.cancel()
            raise
        except (asyncio.TimeoutError, RemoteException):
            self.request_error_metric.labels(method=request.method).inc()
            self.peer_manager.report_failure(peer.address, peer.udp_port)
            if self.peer_manager.peer_is_good(peer) is False:
                self.remove_peer(peer)
            raise

    def send_response(self, peer: 'KademliaPeer', response: ResponseDatagram):
        self._send(peer, response)

    def send_error(self, peer: 'KademliaPeer', error: ErrorDatagram):
        self._send(peer, error)

    def _send(self, peer: 'KademliaPeer', message: typing.Union[RequestDatagram, ResponseDatagram, ErrorDatagram]):
        if not self.transport or self.transport.is_closing():
            raise TransportNotConnected()

        data = message.bencode()
        if len(data) > constants.MSG_SIZE_LIMIT:
            log.warning("cannot send datagram larger than %i bytes (packet is %i bytes)",
                        constants.MSG_SIZE_LIMIT, len(data))
            log.debug("Packet is too large to send: %s", data[:3500].hex())
            raise ValueError(
                f"cannot send datagram larger than {constants.MSG_SIZE_LIMIT} bytes (packet is {len(data)} bytes)"
            )
        if isinstance(message, (RequestDatagram, ResponseDatagram)):
            assert message.node_id == self.node_id, message
            if isinstance(message, RequestDatagram):
                assert self.node_id != peer.node_id

        def pop_from_sent_messages(_):
            if message.rpc_id in self.sent_messages:
                self.sent_messages.pop(message.rpc_id)

        if isinstance(message, RequestDatagram):
            response_fut = self.loop.create_future()
            response_fut.add_done_callback(pop_from_sent_messages)
            self.sent_messages[message.rpc_id] = (peer, response_fut, message)
        try:
            self.transport.sendto(data, (peer.address, peer.udp_port))
        except OSError as err:
            # TODO: handle ENETUNREACH
            if err.errno == socket.EWOULDBLOCK:
                # i'm scared this may swallow important errors, but i get a million of these
                # on Linux and it doesn't seem to affect anything  -grin
                log.warning("Can't send data to dht: EWOULDBLOCK")
            else:
                log.error("DHT socket error sending %i bytes to %s:%i - %s (code %i)",
                          len(data), peer.address, peer.udp_port, str(err), err.errno)
            if isinstance(message, RequestDatagram):
                self.sent_messages[message.rpc_id][1].set_exception(err)
            else:
                raise err
        if isinstance(message, RequestDatagram):
            self.peer_manager.report_last_sent(peer.address, peer.udp_port)
        elif isinstance(message, ErrorDatagram):
            self.peer_manager.report_failure(peer.address, peer.udp_port)

    def change_token(self):
        self.old_token_secret = self.token_secret
        self.token_secret = constants.generate_id()

    def make_token(self, compact_ip):
        return constants.digest(self.token_secret + compact_ip)

    def verify_token(self, token, compact_ip):
        h = constants.HASH_CLASS()
        h.update(self.token_secret + compact_ip)
        if self.old_token_secret and not token == h.digest():  # TODO: why should we be accepting the previous token?
            h = constants.HASH_CLASS()
            h.update(self.old_token_secret + compact_ip)
            if not token == h.digest():
                return False
        return True

    async def store_to_peer(self, hash_value: bytes, peer: 'KademliaPeer',  # pylint: disable=too-many-return-statements
                            retry: bool = True) -> typing.Tuple[bytes, bool]:
        async def __store():
            res = await self.get_rpc_peer(peer).store(hash_value)
            if res != b"OK":
                raise ValueError(res)
            log.debug("Stored %s to %s", hash_value.hex()[:8], peer)
            return peer.node_id, True

        try:
            return await __store()
        except asyncio.TimeoutError:
            log.debug("Timeout while storing blob_hash %s at %s", hash_value.hex()[:8], peer)
            return peer.node_id, False
        except ValueError as err:
            log.error("Unexpected response: %s", err)
            return peer.node_id, False
        except RemoteException as err:
            if 'findValue() takes exactly 2 arguments (5 given)' in str(err):
                log.debug("peer %s:%i is running an incompatible version of lbrynet", peer.address, peer.udp_port)
                return peer.node_id, False
            if 'Invalid token' not in str(err):
                log.warning("Unexpected error while storing blob_hash: %s", err)
                return peer.node_id, False
        self.peer_manager.clear_token(peer.node_id)
        if not retry:
            return peer.node_id, False
        return await self.store_to_peer(hash_value, peer, retry=False)
