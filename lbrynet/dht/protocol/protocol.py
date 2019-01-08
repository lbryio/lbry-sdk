import binascii
import logging
import typing
import socket
import asyncio
from asyncio.protocols import DatagramProtocol
from asyncio.transports import DatagramTransport

from lbrynet.peer import Peer, PeerManager
from lbrynet.dht import constants
from lbrynet.dht.serialization.datagram import decode_datagram, ErrorDatagram, ResponseDatagram, RequestDatagram
from lbrynet.dht.serialization.datagram import RESPONSE_TYPE, ERROR_TYPE
from lbrynet.dht.error import UnknownRemoteException, TransportNotConnected
from lbrynet.dht.protocol.ping_queue import PingQueue
from lbrynet.dht.protocol.rpc import KademliaRPC
from lbrynet.dht.routing.routing_table import TreeRoutingTable
from lbrynet.dht.protocol.data_store import DictDataStore

log = logging.getLogger(__name__)


class KademliaProtocol(DatagramProtocol):
    def __init__(self, peer_manager: PeerManager, loop: asyncio.BaseEventLoop, node_id: bytes, external_ip: str,
                 udp_port: int, peer_port: int):
        self.peer_manager = peer_manager
        self.loop = loop
        self.node_id = node_id
        self.external_ip = external_ip
        self.udp_port = udp_port
        self.peer_port = peer_port
        self.is_seed_node = False
        self.partial_messages: typing.Dict[bytes, typing.Dict[bytes, bytes]] = {}
        self.sent_messages: typing.Dict[bytes, typing.Tuple[Peer, asyncio.Future, RequestDatagram]] = {}
        self.protocol_version = constants.protocol_version
        self.started_listening_time = 0
        self.transport: DatagramTransport = None
        self.old_token_secret = constants.generate_id()
        self.token_secret = constants.generate_id()
        self.routing_table = TreeRoutingTable(self.node_id, self.loop)
        self.data_store = DictDataStore(self.loop)
        self.ping_queue = PingQueue(self.peer_manager, self.loop)
        self.node_rpc = KademliaRPC(self, self.loop, self.peer_port)

        self.peer_manager.register_dht_protocol(self)

    def connection_made(self, transport: DatagramTransport):
        self.transport = transport

    def stop(self):
        if self.transport:
            self.disconnect()

    def disconnect(self):
        self.transport.close()

    def connection_lost(self, exc):
        self.stop()

    def _migrate_incoming_rpc_args(self, contact: Peer, method: bytes, *args) -> typing.Tuple[
        typing.Tuple, typing.Dict
    ]:
        if method == b'store' and contact.protocol_version == 0:
            if isinstance(args[1], dict):
                blob_hash = args[0]
                token = args[1].pop(b'token', None)
                port = args[1].pop(b'port', -1)
                original_publisher_id = args[1].pop(b'lbryid', None)
                age = 0
                return (blob_hash, token, port, original_publisher_id, age), {}
        return args, {}

    def _migrate_outgoing_rpc_args(self, peer: Peer, request: RequestDatagram):
        """
        This will reformat protocol version 0 arguments for the store function and will add the
        protocol version keyword argument to calls to contacts who will accept it
        """
        if peer.protocol_version == 0:
            if request.method == b'store':
                blob_hash, token, port, originalPublisherID, age = request.args
                request.args = [
                    blob_hash, {
                        b'token': token,
                        b'port': port,
                        b'lbryid': originalPublisherID
                    }
                ]
            return
        if request.args and isinstance(request.args[-1], dict):
            request.args[-1][b'protocolVersion'] = self.protocol_version
            return
        request.args = list((() if not request else tuple(request.args)) + (
            {b'protocolVersion': self.protocol_version},))

    def handle_rpc(self, sender_contact: Peer, message: RequestDatagram):
        assert sender_contact.node_id != self.node_id, (binascii.hexlify(sender_contact.node_id)[:8].decode(),
                                                        binascii.hexlify(self.node_id)[:8].decode())
        method = message.method
        if method not in [b'ping', b'store', b'findNode', b'findValue']:
            raise AttributeError('Invalid method: %s' % message.method.decode())
        if message.args and isinstance(message.args[-1], dict) and b'protocolVersion' in message.args[-1]:
            # args don't need reformatting
            sender_contact.update_protocol_version(int(message.args[-1].pop(b'protocolVersion')))
            a, kw = tuple(message.args[:-1]), message.args[-1]
            # log.info("peer %s:%i is using a supported version (version %i)", sender_contact.address,
            #             sender_contact.udp_port, sender_contact.protocol_version)
        else:
            sender_contact.update_protocol_version(0)
            a, kw = self._migrate_incoming_rpc_args(sender_contact, message.method, *message.args)
            # log.warning("peer %s:%i is using an unsupported version (version %i)", sender_contact.address,
            #             sender_contact.udp_port, sender_contact.protocol_version)
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

        self.loop.create_task(self.send(
            sender_contact,
            ResponseDatagram(RESPONSE_TYPE, message.rpc_id, self.node_id, result),
            (sender_contact.address, sender_contact.udp_port)
        ))

    def handle_request_datagram(self, address, request_datagram: RequestDatagram):
        # This is an RPC method request
        remote_contact = self.peer_manager.make_peer(address[0], request_datagram.node_id, udp_port=address[1])
        remote_contact.update_last_requested()

        # only add a requesting contact to the routing table if it has replied to one of our requests
        if remote_contact.contact_is_good is not False and not self.peer_manager.is_ignored(address):
            self.loop.create_task(self.routing_table.add_peer(remote_contact))

        try:
            self.handle_rpc(remote_contact, request_datagram)
            # if the contact is not known to be bad (yet) and we haven't yet queried it, send it a ping so that it
            # will be added to our routing table if successful
            if remote_contact.contact_is_good is None and remote_contact.last_replied is None:
                self.loop.create_task(self.ping_queue.enqueue_maybe_ping(remote_contact))
        except Exception as err:
            log.warning("error raised handling %s request from %s:%i - %s(%s)",
                        request_datagram.method, remote_contact.address, remote_contact.udp_port, str(type(err)),
                        str(err))
            self.loop.create_task(self.send(
                remote_contact,
                ErrorDatagram(ERROR_TYPE, request_datagram.rpc_id, self.node_id, str(type(err)).encode(),
                              str(err).encode()), (remote_contact.address, remote_contact.udp_port)
            ))

    def handle_response_datagram(self, address, response_datagram: ResponseDatagram):
        # Find the message that triggered this response
        if response_datagram.rpc_id in self.sent_messages:
            remote_contact, df, request = self.sent_messages[response_datagram.rpc_id]

            # When joining the network we made Contact objects for the seed nodes with node ids set to None
            # Thus, the sent_to_id will also be None, and the contact objects need the ids to be manually set.
            # These replies have be distinguished from those where the node node_id in the datagram does not match
            # the node node_id of the node we sent a message to (these messages are treated as an error)
            if remote_contact.node_id and remote_contact.node_id != response_datagram.node_id:
                log.warning(
                    "mismatch: (%s) %s:%i (%s vs %s)", request.method, remote_contact.address,
                    remote_contact.udp_port, remote_contact.log_id(False),
                    binascii.hexlify(response_datagram.node_id).decode()
                )
                df.set_exception(TimeoutError(remote_contact.node_id))
                return
            elif not remote_contact.node_id:
                remote_contact.set_id(response_datagram.node_id)

            # We got a result from the RPC
            if remote_contact.node_id == self.node_id:
                df.set_exception(UnknownRemoteException("node has our node id"))
                return
            elif response_datagram.node_id == self.node_id:
                df.set_exception(UnknownRemoteException("incoming message is from our node id"))
                return
            elif remote_contact.address != address[0]:
                df.set_exception(UnknownRemoteException(
                    f"response from {address[0]}:{address[1]}, "
                    f"expected {remote_contact.address}:{remote_contact.udp_port}")
                )
                return
            if not df.cancelled():
                self.loop.create_task(self.routing_table.add_peer(remote_contact))
                df.set_result(response_datagram.response)
            else:
                log.warning("%s:%i replied, but after we cancelled the request attempt",
                            remote_contact.address, remote_contact.udp_port)
        else:
            # If the original message isn't found, it must have timed out
            # TODO: we should probably do something with this...
            pass

    def handle_error_datagram(self, address, error_datagram: ErrorDatagram):
        # The RPC request raised a remote exception; raise it locally
        remote_exception = UnknownRemoteException(f"{error_datagram.exception_type}({error_datagram.response})")
        if error_datagram.rpc_id in self.sent_messages:
            remote_contact, df, request = self.sent_messages.pop(error_datagram.rpc_id)

            error_msg = f"" \
                f"Error sending '{request.method}' to {remote_contact.address}:{remote_contact.udp_port}\n" \
                f"Args: {request.args}\n" \
                f"Raised: {str(remote_exception)}"

            log.error(error_msg)

            # reject replies coming from a different address than what we sent our request to
            if (remote_contact.address, remote_contact.udp_port) != address:
                log.error("Sent request to node %s at %s:%i, got reply from %s:%i",
                          remote_contact.log_id(), remote_contact.address,
                          remote_contact.udp_port, address[0], address[1])
                remote_exception = TimeoutError(remote_contact.node_id)
            df.set_exception(remote_exception)
            return
        else:
            log.warning(f"Received error from {address[0]}:{address[1]}, "
                        f"but it isn't in response to a pending request: {str(remote_exception)}")

    def datagram_received(self, datagram: bytes, address: typing.Tuple[str, int]) -> None:
        """ Handles and parses incoming RPC messages (and responses)

        @note: This is automatically called by Twisted when the protocol
               receives a UDP datagram
        """
        # print(f"{self.external_ip}:{self.udp_port} rx {len(datagram)} bytes from {address[0]}:{address[1]}")

        if chr(datagram[0]) == '\x00' and chr(datagram[25]) == '\x00':
            total_packets = (datagram[1] << 8) | datagram[2]
            msg_id = datagram[5:25]
            seq_number = (datagram[3] << 8) | datagram[4]
            if msg_id not in self.partial_messages:
                self.partial_messages[msg_id] = {}
            self.partial_messages[msg_id][seq_number] = datagram[26:]
            if len(self.partial_messages[msg_id]) == total_packets:
                keys = list(self.partial_messages[msg_id].keys())
                keys.sort()
                data = b''
                for key in keys:
                    data += self.partial_messages[msg_id][key]
                    datagram = data
                del self.partial_messages[msg_id]
            else:
                return
        try:
            message = decode_datagram(datagram)
        except Exception:
            log.warning("Couldn't decode dht datagram from %s: %s", address, binascii.hexlify(datagram).decode())
            return

        if isinstance(message, RequestDatagram):
            return self.handle_request_datagram(address, message)
        elif isinstance(message, ErrorDatagram):
            return self.handle_error_datagram(address, message)
        else:
            assert isinstance(message, ResponseDatagram), "sanity"
            return self.handle_response_datagram(address, message)

    async def send(self, peer: Peer, message: typing.Union[RequestDatagram, ResponseDatagram, ErrorDatagram],
                   address: typing.Tuple[str, int]):
        """ Transmit the specified data over UDP, breaking it up into several
        packets if necessary

        If the data is spread over multiple UDP datagrams, the packets have the
        following structure::
            |           |     |      |      |        ||||||||||||   0x00   |
            |Transmission|Total number|Sequence number| RPC ID   |Header end|
            | type ID   | of packets |of this packet |          | indicator|
            | (1 byte)  | (2 bytes)  |  (2 bytes)    |(20 bytes)| (1 byte) |
            |           |     |      |      |        ||||||||||||          |

        @note: The header used for breaking up large data segments will
               possibly be moved out of the KademliaProtocol class in the
               future, into something similar to a message translator/encoder
               class (see C{kademlia.msgformat} and C{kademlia.encoding}).
        """
        if isinstance(message, (RequestDatagram, ResponseDatagram)):
            assert message.node_id == self.node_id, message
        # if isinstance(message, RequestDatagram):
        #     self._migrate_outgoing_rpc_args(peer, message)
        data = message.bencode()
        if len(data) > constants.msg_size_limit:
            # We have to spread the data over multiple UDP datagrams,
            # and provide sequencing information
            #
            # 1st byte is transmission type node_id, bytes 2 & 3 are the
            # total number of packets in this transmission, bytes 4 &
            # 5 are the sequence number for this specific packet
            total_packets = len(data) // constants.msg_size_limit
            if len(data) % constants.msg_size_limit > 0:
                total_packets += 1
            enc_total_packets = chr(total_packets >> 8) + chr(total_packets & 0xff)
            seq_number = 0
            start_pos = 0
            while seq_number < total_packets:
                packet_data = data[start_pos:start_pos + constants.msg_size_limit]
                enc_seq_number = chr(seq_number >> 8) + chr(seq_number & 0xff)
                tx_data = f'\x00{enc_total_packets}{enc_seq_number}{message.rpc_id}\x00{packet_data}'
                self.loop.call_soon(self._write, tx_data, address)
                start_pos += constants.msg_size_limit
                seq_number += 1
        else:
            self.loop.call_soon(self._write, data, address)
        fut = asyncio.Future(loop=self.loop)

        def timeout(_):
            if message.rpc_id in self.sent_messages:
                self.sent_messages.pop(message.rpc_id)

        fut.add_done_callback(timeout)

        if isinstance(message, RequestDatagram):
            assert self.node_id != peer.node_id
            assert self.node_id == message.node_id
            self.sent_messages[message.rpc_id] = (
                self.peer_manager.make_peer(address[0], peer.node_id, udp_port=address[1]), fut,
                message
            )
        else:
            fut.set_result(None)
        return await fut

    def get_pending_message_future(self, rpc_id: bytes) -> asyncio.Future:
        return self.sent_messages[rpc_id][1]

    def change_token(self):
        self.old_token_secret = self.token_secret
        self.token_secret = constants.generate_id()

    def make_token(self, compact_ip):
        return constants.digest(self.token_secret + compact_ip)

    def verify_token(self, token, compact_ip):
        h = constants.hash_class()
        h.update(self.token_secret + compact_ip)
        if self.old_token_secret and not token == h.digest(): # TODO: why should we be accepting the previous token?
            h = constants.hash_class()
            h.update(self.old_token_secret + compact_ip)
            if not token == h.digest():
                return False
        return True

    async def store_to_peer(self, hash_value: bytes, peer: Peer) -> typing.Tuple[bytes, bool]:
        try:
            if not peer.token:
                await peer.find_value(hash_value)
            res = await peer.store(hash_value)
            if res != b"OK":
                raise ValueError(res)
            log.info("Stored %s to %s (%s) version %i", binascii.hexlify(hash_value).decode()[:8], peer.log_id(),
                     peer.address, peer.protocol_version)
            return peer.node_id, True
        except asyncio.TimeoutError:
            log.debug("Timeout while storing blob_hash %s at %s",
                      binascii.hexlify(hash_value), peer.log_id())
        except ValueError as err:
            log.error("Unexpected response: %s" % err)
        except Exception as err:
            if 'Invalid token' in str(err):
                peer.update_token(None)
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
