import logging
import socket
import functools
import hashlib
import asyncio
import typing
import binascii
from asyncio.protocols import DatagramProtocol
from asyncio.transports import DatagramTransport

from lbrynet.dht import constants
from lbrynet.dht.serialization.datagram import decode_datagram, ErrorDatagram, ResponseDatagram, RequestDatagram
from lbrynet.dht.serialization.datagram import RESPONSE_TYPE, ERROR_TYPE
from lbrynet.dht.error import RemoteException, TransportNotConnected
from lbrynet.dht.protocol.routing_table import TreeRoutingTable
from lbrynet.dht.protocol.data_store import DictDataStore

if typing.TYPE_CHECKING:
    from lbrynet.dht.peer import PeerManager, KademliaPeer

log = logging.getLogger(__name__)


old_protocol_errors = {
    "findNode() takes exactly 2 arguments (5 given)": "0.19.1",
    "findValue() takes exactly 2 arguments (5 given)": "0.19.1"
}


class KademliaRPC:
    def __init__(self, protocol: 'KademliaProtocol', loop: asyncio.BaseEventLoop, peer_port: int = 3333):
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

    def store(self, rpc_contact: 'KademliaPeer', blob_hash: bytes, token: bytes, port: int,
              original_publisher_id: bytes, age: int) -> bytes:
        if original_publisher_id is None:
            original_publisher_id = rpc_contact.node_id
        rpc_contact.update_tcp_port(port)
        if self.loop.time() - self.protocol.started_listening_time < constants.token_secret_refresh_interval:
            pass
        elif not self.verify_token(token, rpc_contact.compact_ip()):
            raise ValueError("Invalid token")
        now = int(self.loop.time())
        originally_published = now - age
        self.protocol.data_store.add_peer_to_blob(
            rpc_contact, blob_hash, rpc_contact.compact_address_tcp(), now, originally_published, original_publisher_id
        )
        return b'OK'

    def find_node(self, rpc_contact: 'KademliaPeer', key: bytes) -> typing.List[typing.Tuple[bytes, str, int]]:
        if len(key) != constants.hash_length:
            raise ValueError("invalid contact node_id length: %i" % len(key))

        contacts = self.protocol.routing_table.find_close_peers(key, sender_node_id=rpc_contact.node_id)
        contact_triples = []
        for contact in contacts:
            contact_triples.append((contact.node_id, contact.address, contact.udp_port))
        return contact_triples

    def find_value(self, rpc_contact: 'KademliaPeer', key: bytes):
        if len(key) != constants.hash_length:
            raise ValueError("invalid blob_exchange hash length: %i" % len(key))

        response = {
            b'token': self.make_token(rpc_contact.compact_ip()),
        }

        if self.protocol.protocol_version:
            response[b'protocolVersion'] = self.protocol.protocol_version

        # get peers we have stored for this blob_exchange
        has_other_peers = self.protocol.data_store.has_peers_for_blob(key)
        peers = []
        if has_other_peers:
            peers.extend([peer.compact_address_tcp() for peer in self.protocol.data_store.get_peers_for_blob(key)])

        # if we don't have k storing peers to return and we have this hash locally, include our contact information
        if len(peers) < constants.k and binascii.hexlify(key).decode() in self.protocol.data_store.completed_blobs:
            peers.append(self.compact_address())
        if peers:
            response[key] = peers
        else:
            response[b'contacts'] = self.find_node(rpc_contact, key)
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

    def __init__(self, loop: asyncio.BaseEventLoop, peer_tracker: 'PeerManager', protocol: 'KademliaProtocol',
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
        if len(blob_hash) != constants.hash_bits // 8:
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
        if len(key) != constants.hash_bits // 8:
            raise ValueError(f"invalid length of find node key: {len(key)}")
        response = await self.protocol.send_request(
            self.peer, RequestDatagram.make_find_node(self.protocol.node_id, key)
        )
        return [(node_id, address.decode(), udp_port) for node_id, address, udp_port in response.response]

    async def find_value(self, key: bytes) -> typing.Union[typing.Dict]:
        """
        :return: {
            b'token': <token bytes>,
            b'contacts': [(node_id, address, udp_port), ...]
            <key bytes>: [<blob_peer_compact_address, ...]
        }
        """
        if len(key) != constants.hash_bits // 8:
            raise ValueError(f"invalid length of find value key: {len(key)}")
        response = await self.protocol.send_request(
            self.peer, RequestDatagram.make_find_value(self.protocol.node_id, key)
        )
        await self.peer_tracker.update_token(self.peer.node_id, response.response[b'token'])
        return response.response


class PingQueue:
    def __init__(self, loop: asyncio.BaseEventLoop, protocol: 'KademliaProtocol'):
        self._loop = loop
        self._protocol = protocol
        self._enqueued_contacts: typing.List['KademliaPeer'] = []
        self._pending_contacts: typing.Dict['KademliaPeer', float] = {}
        self._process_task: asyncio.Task = None
        self._next_task: asyncio.Future = None
        self._next_timer: asyncio.TimerHandle = None
        self._lock = asyncio.Lock()
        self._running = False

    @property
    def running(self):
        return self._running

    async def enqueue_maybe_ping(self, *peers: 'KademliaPeer', delay: typing.Optional[float] = None):
        delay = constants.check_refresh_interval if delay is None else delay
        async with self._lock:
            for peer in peers:
                if delay and peer not in self._enqueued_contacts:
                    self._pending_contacts[peer] = self._loop.time() + delay
                elif peer not in self._enqueued_contacts:
                    self._enqueued_contacts.append(peer)
                    if peer in self._pending_contacts:
                        del self._pending_contacts[peer]

    async def _process(self):
        async def _ping(p: 'KademliaPeer'):
            try:
                if self._protocol.peer_manager.peer_is_good(p):
                    await self._protocol.add_peer(p)
                    return
                await self._protocol.get_rpc_peer(p).ping()
            except TimeoutError:
                pass

        while True:
            tasks = []

            async with self._lock:
                if self._enqueued_contacts or self._pending_contacts:
                    now = self._loop.time()
                    scheduled = [k for k, d in self._pending_contacts.items() if now >= d]
                    for k in scheduled:
                        del self._pending_contacts[k]
                        if k not in self._enqueued_contacts:
                            self._enqueued_contacts.append(k)
                    while self._enqueued_contacts:
                        peer = self._enqueued_contacts.pop()
                        tasks.append(self._loop.create_task(_ping(peer)))
            if tasks:
                await asyncio.wait(tasks, loop=self._loop)

            f = self._loop.create_future()
            self._loop.call_later(1.0, lambda: None if f.done() else f.set_result(None))
            await f

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
        if self._next_task:
            self._next_task.cancel()
            self._next_task = None
        if self._next_timer:
            self._next_timer.cancel()
            self._next_timer = None


class KademliaProtocol(DatagramProtocol):
    def __init__(self, loop: asyncio.BaseEventLoop, peer_manager: 'PeerManager', node_id: bytes, external_ip: str,
                 udp_port: int, peer_port: int, rpc_timeout: float = 5.0):
        self.peer_manager = peer_manager
        self.loop = loop
        self.node_id = node_id
        self.external_ip = external_ip
        self.udp_port = udp_port
        self.peer_port = peer_port
        self.is_seed_node = False
        self.partial_messages: typing.Dict[bytes, typing.Dict[bytes, bytes]] = {}
        self.sent_messages: typing.Dict[bytes, typing.Tuple['KademliaPeer', asyncio.Future, RequestDatagram]] = {}
        self.protocol_version = constants.protocol_version
        self.started_listening_time = 0
        self.transport: DatagramTransport = None
        self.old_token_secret = constants.generate_id()
        self.token_secret = constants.generate_id()
        self.routing_table = TreeRoutingTable(self.loop, self.peer_manager, self.node_id)
        self.data_store = DictDataStore(self.loop, self.peer_manager)
        self.ping_queue = PingQueue(self.loop, self)
        self.node_rpc = KademliaRPC(self, self.loop, self.peer_port)
        self.lock = asyncio.Lock(loop=self.loop)
        self.rpc_timeout = rpc_timeout
        self._split_lock = asyncio.Lock(loop=self.loop)

    def get_rpc_peer(self, peer: 'KademliaPeer') -> RemoteKademliaRPC:
        return RemoteKademliaRPC(self.loop, self.peer_manager, self, peer)

    def stop(self):
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
        bucket_index = self.routing_table.kbucket_index(peer.node_id)
        if self.routing_table.buckets[bucket_index].add_peer(peer):
            return True
        # The bucket is full; see if it can be split (by checking if its range includes the host node's node_id)
        if self.routing_table.should_split(bucket_index, peer.node_id):
            self.routing_table.split_bucket(bucket_index)
            # Retry the insertion attempt
            result = await self._add_peer(peer)
            self.routing_table.join_buckets()
            return result
        else:
            # We can't split the k-bucket
            #
            # The 13 page kademlia paper specifies that the least recently contacted node in the bucket
            # shall be pinged. If it fails to reply it is replaced with the new contact. If the ping is successful
            # the new contact is ignored and not added to the bucket (sections 2.2 and 2.4).
            #
            # A reasonable extension to this is BEP 0005, which extends the above:
            #
            #    Not all nodes that we learn about are equal. Some are "good" and some are not.
            #    Many nodes using the DHT are able to send queries and receive responses,
            #    but are not able to respond to queries from other nodes. It is important that
            #    each node's routing table must contain only known good nodes. A good node is
            #    a node has responded to one of our queries within the last 15 minutes. A node
            #    is also good if it has ever responded to one of our queries and has sent us a
            #    query within the last 15 minutes. After 15 minutes of inactivity, a node becomes
            #    questionable. Nodes become bad when they fail to respond to multiple queries
            #    in a row. Nodes that we know are good are given priority over nodes with unknown status.
            #
            # When there are bad or questionable nodes in the bucket, the least recent is selected for
            # potential replacement (BEP 0005). When all nodes in the bucket are fresh, the head (least recent)
            # contact is selected as described in section 2.2 of the kademlia paper. In both cases the new contact
            # is ignored if the pinged node replies.

            not_good_contacts = self.routing_table.buckets[bucket_index].get_bad_or_unknown_peers()
            not_recently_replied = []
            for p in not_good_contacts:
                last_replied = self.peer_manager.get_last_replied(p.address, p.udp_port)
                if not last_replied or last_replied + 60 < self.loop.time():
                    not_recently_replied.append(p)
            if not_recently_replied:
                to_replace = not_recently_replied[0]
            else:
                to_replace = self.routing_table.buckets[bucket_index].peers[0]
                last_replied = self.peer_manager.get_last_replied(to_replace.address, to_replace.udp_port)
                if last_replied and last_replied + 60 > self.loop.time():
                    return False
            log.debug("pinging %s:%s", to_replace.address, to_replace.udp_port)
            try:
                to_replace_rpc = self.get_rpc_peer(to_replace)
                await to_replace_rpc.ping()
                return False
            except asyncio.TimeoutError:
                log.debug("Replacing dead contact in bucket %i: %s:%i with %s:%i ", bucket_index,
                          to_replace.address, to_replace.udp_port, peer.address, peer.udp_port)
                if to_replace in self.routing_table.buckets[bucket_index]:
                    self.routing_table.buckets[bucket_index].remove_peer(to_replace)
                return await self._add_peer(peer)

    async def add_peer(self, peer: 'KademliaPeer') -> bool:
        if peer.node_id == self.node_id:
            return False
        async with self._split_lock:
            return await self._add_peer(peer)

    async def _handle_rpc(self, sender_contact: 'KademliaPeer', message: RequestDatagram):
        assert sender_contact.node_id != self.node_id, (binascii.hexlify(sender_contact.node_id)[:8].decode(),
                                                        binascii.hexlify(self.node_id)[:8].decode())
        method = message.method
        if method not in [b'ping', b'store', b'findNode', b'findValue']:
            raise AttributeError('Invalid method: %s' % message.method.decode())
        if message.args and isinstance(message.args[-1], dict) and b'protocolVersion' in message.args[-1]:
            # args don't need reformatting
            a, kw = tuple(message.args[:-1]), message.args[-1]
        else:
            a, kw = self._migrate_incoming_rpc_args(sender_contact, message.method, *message.args)
        log.debug("%s:%i RECV CALL %s %s:%i", self.external_ip, self.udp_port, message.method.decode(),
                  sender_contact.address, sender_contact.udp_port)

        if method == b'ping':
            result = self.node_rpc.ping()
        elif method == b'store':
            blob_hash, token, port, original_publisher_id, age = a
            result = self.node_rpc.store(sender_contact, blob_hash, token, port, original_publisher_id, age)
        elif method == b'findNode':
            key, = a
            result = self.node_rpc.find_node(sender_contact, key)
        else:
            assert method == b'findValue'
            key, = a
            result = self.node_rpc.find_value(sender_contact, key)

        await self.send_response(
            sender_contact, ResponseDatagram(RESPONSE_TYPE, message.rpc_id, self.node_id, result),
        )

    async def handle_request_datagram(self, address, request_datagram: RequestDatagram):
        # This is an RPC method request
        await self.peer_manager.report_last_requested(address[0], address[1])
        await self.peer_manager.update_contact_triple(request_datagram.node_id, address[0], address[1])
        # only add a requesting contact to the routing table if it has replied to one of our requests
        peer = self.peer_manager.get_kademlia_peer(request_datagram.node_id, address[0], address[1])
        try:
            await self._handle_rpc(peer, request_datagram)
            # if the contact is not known to be bad (yet) and we haven't yet queried it, send it a ping so that it
            # will be added to our routing table if successful
            is_good = self.peer_manager.peer_is_good(peer)
            if is_good is None:
                await self.ping_queue.enqueue_maybe_ping(peer)
            elif is_good is True:
                await self.add_peer(peer)

        except Exception as err:
            log.warning("error raised handling %s request from %s:%i - %s(%s)",
                        request_datagram.method, peer.address, peer.udp_port, str(type(err)),
                        str(err))
            await self.send_error(
                peer,
                ErrorDatagram(ERROR_TYPE, request_datagram.rpc_id, self.node_id, str(type(err)).encode(),
                              str(err).encode())
            )

    async def handle_response_datagram(self, address: typing.Tuple[str, int], response_datagram: ResponseDatagram):
        # Find the message that triggered this response
        if response_datagram.rpc_id in self.sent_messages:
            peer, df, request = self.sent_messages[response_datagram.rpc_id]
            if peer.address != address[0]:
                df.set_exception(RemoteException(
                    f"response from {address[0]}:{address[1]}, "
                    f"expected {peer.address}:{peer.udp_port}")
                )
                return
            peer.set_id(response_datagram.node_id)
            # We got a result from the RPC
            if peer.node_id == self.node_id:
                df.set_exception(RemoteException("node has our node id"))
                return
            elif response_datagram.node_id == self.node_id:
                df.set_exception(RemoteException("incoming message is from our node id"))
                return
            await self.peer_manager.report_last_replied(address[0], address[1])
            await self.peer_manager.update_contact_triple(peer.node_id, address[0], address[1])
            if not df.cancelled():
                df.set_result(response_datagram)
                await self.add_peer(peer)
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
            peer, df, request = self.sent_messages.pop(error_datagram.rpc_id)

            error_msg = f"" \
                f"Error sending '{request.method}' to {peer.address}:{peer.udp_port}\n" \
                f"Args: {request.args}\n" \
                f"Raised: {str(remote_exception)}"
            if error_datagram.response not in old_protocol_errors:
                log.warning(error_msg)
            else:
                log.warning("known dht protocol backwards compatibility error with %s:%i (lbrynet v%s)",
                            peer.address, peer.udp_port, old_protocol_errors[error_datagram.response])

            # reject replies coming from a different address than what we sent our request to
            if (peer.address, peer.udp_port) != address:
                log.error("node id mismatch in reply")
                remote_exception = TimeoutError(peer.node_id)
            df.set_exception(remote_exception)
            return
        else:
            if error_datagram.response not in old_protocol_errors:
                msg = f"Received error from {address[0]}:{address[1]}, but it isn't in response to a " \
                    f"pending request: {str(remote_exception)}"
                log.warning(msg)
            else:
                log.warning("known dht protocol backwards compatibility error with %s:%i (lbrynet v%s)",
                            address[0], address[1], old_protocol_errors[error_datagram.response])

    def datagram_received(self, datagram: bytes, address: typing.Tuple[str, int]) -> None:
        try:
            message = decode_datagram(datagram)
        except (ValueError, TypeError):
            self.loop.create_task(self.peer_manager.report_failure(address[0], address[1]))
            log.warning("Couldn't decode dht datagram from %s: %s", address, binascii.hexlify(datagram).decode())
            return

        if isinstance(message, RequestDatagram):
            self.loop.create_task(self.handle_request_datagram(address, message))
        elif isinstance(message, ErrorDatagram):
            self.handle_error_datagram(address, message)
        else:
            assert isinstance(message, ResponseDatagram), "sanity"
            self.loop.create_task(self.handle_response_datagram(address, message))

    async def send_request(self, peer: 'KademliaPeer', request: RequestDatagram) -> ResponseDatagram:
        await self._send(peer, request)
        response_fut = self.sent_messages[request.rpc_id][1]
        try:
            response = await asyncio.wait_for(response_fut, self.rpc_timeout)
            await self.peer_manager.report_last_replied(peer.address, peer.udp_port)
            return response
        except (asyncio.TimeoutError, RemoteException):
            await self.peer_manager.report_failure(peer.address, peer.udp_port)
            if self.peer_manager.peer_is_good(peer) is False:
                self.routing_table.remove_peer(peer)
            raise

    async def send_response(self, peer: 'KademliaPeer', response: ResponseDatagram):
        await self._send(peer, response)

    async def send_error(self, peer: 'KademliaPeer', error: ErrorDatagram):
        await self._send(peer, error)

    async def _send(self, peer: 'KademliaPeer', message: typing.Union[RequestDatagram, ResponseDatagram,
                                                                      ErrorDatagram]):
        if not self.transport:
            raise TransportNotConnected()

        data = message.bencode()
        if len(data) > constants.msg_size_limit:
            log.exception("unexpected: %i vs %i", len(data), constants.msg_size_limit)
            raise ValueError()
        if isinstance(message, (RequestDatagram, ResponseDatagram)):
            assert message.node_id == self.node_id, message
            if isinstance(message, RequestDatagram):
                assert self.node_id != peer.node_id

        def pop_from_sent_messages(_):
            if message.rpc_id in self.sent_messages:
                self.sent_messages.pop(message.rpc_id)

        async with self.lock:
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
            await self.peer_manager.report_last_sent(peer.address, peer.udp_port)
        elif isinstance(message, ErrorDatagram):
            await self.peer_manager.report_failure(peer.address, peer.udp_port)

    def change_token(self):
        self.old_token_secret = self.token_secret
        self.token_secret = constants.generate_id()

    def make_token(self, compact_ip):
        return constants.digest(self.token_secret + compact_ip)

    def verify_token(self, token, compact_ip):
        h = constants.hash_class()
        h.update(self.token_secret + compact_ip)
        if self.old_token_secret and not token == h.digest():  # TODO: why should we be accepting the previous token?
            h = constants.hash_class()
            h.update(self.old_token_secret + compact_ip)
            if not token == h.digest():
                return False
        return True

    async def store_to_peer(self, hash_value: bytes, peer: 'KademliaPeer') -> typing.Tuple[bytes, bool]:
        try:
            res = await self.get_rpc_peer(peer).store(hash_value)
            if res != b"OK":
                raise ValueError(res)
            log.info("Stored %s to %s", binascii.hexlify(hash_value).decode()[:8], peer)
            return peer.node_id, True
        except asyncio.TimeoutError:
            log.debug("Timeout while storing blob_hash %s at %s", binascii.hexlify(hash_value).decode()[:8], peer)
        except ValueError as err:
            log.error("Unexpected response: %s" % err)
        except Exception as err:
            if 'Invalid token' in str(err):
                await self.peer_manager.clear_token(peer.node_id)
            else:
                log.exception("Unexpected error while storing blob_hash")
        return peer.node_id, False

    def _write(self, data: bytes, address: typing.Tuple[str, int]):
        if self.transport:
            try:
                self.transport.sendto(data, address)
            except OSError as err:
                if err.errno == socket.EWOULDBLOCK:
                    # i'm scared this may swallow important errors, but i get a million of these
                    # on Linux and it doesn't seem to affect anything  -grin
                    log.warning("Can't send data to dht: EWOULDBLOCK")
                # elif err.errno == socket.ENETUNREACH:
                #     # this should probably try to retransmit when the network connection is back
                #     log.error("Network is unreachable")
                else:
                    log.error("DHT socket error sending %i bytes to %s:%i - %s (code %i)",
                              len(data), address[0], address[1], str(err), err.errno)
                    raise err
        else:
            raise TransportNotConnected()
