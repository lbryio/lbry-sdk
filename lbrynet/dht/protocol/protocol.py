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
from lbrynet.dht.error import UnknownRemoteException, TransportNotConnected
from lbrynet.dht.protocol.ping_queue import PingQueue
from lbrynet.dht.protocol.rpc import KademliaRPC
from lbrynet.dht.routing.routing_table import TreeRoutingTable
from lbrynet.dht.protocol.data_store import DictDataStore
from lbrynet.dht.iterative_find import IterativeFinder

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
        self.sent_messages: typing.Dict[bytes, typing.Tuple[Peer, asyncio.Future, str]] = {}
        self.protocol_version = constants.protocol_version
        self.started_listening_time = 0
        self.transport: DatagramTransport = None
        self.old_token_secret = constants.generate_id()
        self.token_secret = constants.generate_id()
        self.routing_table = TreeRoutingTable(self.node_id, self.loop)
        self.data_store = DictDataStore(self.loop)
        self.ping_queue = PingQueue(self.peer_manager, self.loop)
        self.node_rpc = KademliaRPC(self, self.loop, self.peer_port)
        self.refresh_task: asyncio.Task = None
        self._lock = asyncio.Lock()
        self.peer_manager.register_dht_protocol(self)

    def connection_made(self, transport: DatagramTransport):
        log.info("create refresh task")
        self.transport = transport
        self.ping_queue.start()
        self.refresh_task = asyncio.create_task(self.refresh_node())

    def connection_lost(self, exc):
        log.info("stop refresh task")
        self.refresh_task.cancel()
        self.ping_queue.stop()

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

    def _migrate_outgoing_rpc_args(self, contact, method, *args):
        """
        This will reformat protocol version 0 arguments for the store function and will add the
        protocol version keyword argument to calls to contacts who will accept it
        """
        if contact.protocolVersion == 0:
            if method == b'store':
                blob_hash, token, port, originalPublisherID, age = args
                args = (
                    blob_hash, {
                        b'token': token,
                        b'port': port,
                        b'lbryid': originalPublisherID
                    }, originalPublisherID, False
                )
                return args
            return args
        if args and isinstance(args[-1], dict):
            args[-1][b'protocolVersion'] = self.protocol_version
            return args
        return args + ({b'protocolVersion': self.protocol_version},)

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
        except Exception as err:
            log.warning("Couldn't decode dht datagram from %s: %s", address, binascii.hexlify(datagram).decode())
            return

        if isinstance(message, RequestDatagram):
            # This is an RPC method request
            remote_contact = self.peer_manager.make_peer(address[0], message.node_id, udp_port=address[1])
            remote_contact.update_last_requested()

            # only add a requesting contact to the routing table if it has replied to one of our requests
            if remote_contact.contact_is_good is not False and not self.peer_manager.is_ignored(address):
                asyncio.create_task(self.routing_table.add_contact(remote_contact))

            self.handle_rpc(remote_contact, message)

            # if the contact is not known to be bad (yet) and we haven't yet queried it, send it a ping so that it
            # will be added to our routing table if successful
            if remote_contact.contact_is_good is None and remote_contact.last_replied is None:
                asyncio.create_task(self.ping_queue.enqueue_maybe_ping(remote_contact))
            return
        elif isinstance(message, ErrorDatagram):
            # The RPC request raised a remote exception; raise it locally
            remote_exception = UnknownRemoteException(message.response)
            log.error("DHT RECV REMOTE EXCEPTION FROM %s:%i: %s", address[0],
                      address[1], remote_exception)
            if message.rpc_id in self.sent_messages:
                remote_contact, df, method = self.sent_messages.pop(message.rpc_id)

                # reject replies coming from a different address than what we sent our request to
                if (remote_contact.address, remote_contact.udp_port) != address:
                    print("Sent request to node %s at %s:%i, got reply from %s:%i" % (
                        remote_contact.log_id(), remote_contact.address,
                        remote_contact.udp_port, address[0], address[1]))
                    df.set_exception(TimeoutError(remote_contact.node_id))
                    return

                # this error is returned by nodes that can be contacted but have an old
                # and broken version of the ping command, if they return it the node can
                # be contacted, so we'll treat it as a successful ping
                old_ping_error = "ping() got an unexpected keyword argument '_rpcNodeContact'"
                if isinstance(remote_exception, TypeError) and \
                        message.response == old_ping_error:
                    log.debug("old pong error")
                    df.set_result(b'pong')
                else:
                    df.set_exception(remote_exception)
        elif isinstance(message, ResponseDatagram):
            # Find the message that triggered this response
            if message.rpc_id in self.sent_messages:
                # Cancel timeout timer for this RPC
                remote_contact, df, method = self.sent_messages[message.rpc_id]
                log.debug("%s:%i got response to %s from %s:%i" % (self.external_ip, self.udp_port,
                          method, remote_contact.address, remote_contact.udp_port))

                # When joining the network we made Contact objects for the seed nodes with node ids set to None
                # Thus, the sent_to_id will also be None, and the contact objects need the ids to be manually set.
                # These replies have be distinguished from those where the node node_id in the datagram does not match
                # the node node_id of the node we sent a message to (these messages are treated as an error)
                # if remote_contact.node_id and self.node_id != message.node_id:  # sent_to_id will be None for bootstrap
                #     # print("mismatch: (%s) %s:%i (%s vs %s)" % (method, remote_contact.address, remote_contact.port,
                #     #           remote_contact.log_id(False), binascii.hexlify(message.node_id)))
                #     print(binascii.hexlify(message.node_id),  binascii.hexlify(self.node_id))
                #     df.set_exception(TimeoutError(remote_contact.node_id))
                #     return
                # elif not remote_contact.node_id:
                #     remote_contact.set_id(message.node_id)

                # We got a result from the RPC
                try:
                    assert remote_contact.node_id != self.node_id
                    assert message.node_id != self.node_id
                    if remote_contact.node_id is None:
                        remote_contact.set_id(message.node_id)
                    err_str = f"response from {address[0]}:{address[1]}, " \
                              f"expected {remote_contact.address}:{remote_contact.udp_port}"
                    assert (remote_contact.address, remote_contact.udp_port) == address, AssertionError(err_str)

                except AssertionError as err:
                    df.set_exception(err)
                    return
                # else:
                #     assert message.node_id == self.node_id
                asyncio.create_task(self.routing_table.add_contact(remote_contact))
                df.set_result(message.response)
            else:
                # If the original message isn't found, it must have timed out
                # TODO: we should probably do something with this...
                pass

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
        else:
            sender_contact.update_protocol_version(0)
            a, kw = self._migrate_incoming_rpc_args(sender_contact, message.method, *message.args)

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
        log.debug("%s:%i RECV CALL %s %s:%i", self.external_ip, self.udp_port, message.method.decode(),
                  sender_contact.address, sender_contact.udp_port)
        asyncio.create_task(self.send(
            sender_contact,
            ResponseDatagram(1, message.rpc_id, self.node_id, result),
            (sender_contact.address, sender_contact.udp_port)
        ))

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
                self._schedule_send_next(tx_data, address)
                start_pos += constants.msg_size_limit
                seq_number += 1
        else:
            self._schedule_send_next(data, address)
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
                message.method
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

    async def refresh_node(self):
        """ Periodically called to perform k-bucket refreshes and data
        replication/republishing as necessary """
        while True:
            self.data_store.removed_expired_peers()
            await self.ping_queue.enqueue_maybe_ping(*self.routing_table.get_contacts(), delay=0)
            await self.ping_queue.enqueue_maybe_ping(*self.data_store.get_storing_contacts(), delay=0)
            await self.refresh_routing_table()
            fut = asyncio.Future(loop=self.loop)
            self.loop.call_later(constants.refresh_interval, fut.set_result, None)
            await fut

    async def refresh_routing_table(self):
        node_ids = self.routing_table.get_refresh_list(0, True)
        buckets_with_contacts = self.routing_table.buckets_with_contacts()
        if buckets_with_contacts <= 3:
            for i in range(buckets_with_contacts):
                node_ids.append(self.routing_table.random_id_in_bucket_range(i))
                node_ids.append(self.routing_table.random_id_in_bucket_range(i))
        while node_ids:
            await self.cumulative_find_node(node_ids.pop())

    def get_find_iterator(self, rpc: str, key: bytes, shortlist: typing.Optional[typing.List] = None,
                          bottom_out_limit: int = constants.bottom_out_limit,
                          max_results: int = constants.k):
        return self._get_find_iterator(rpc, key, shortlist, bottom_out_limit).iterative_find(max_results)

    def _get_find_iterator(self, rpc: str, key: bytes, shortlist: typing.Optional[typing.List] = None,
                          bottom_out_limit: int = constants.bottom_out_limit) -> IterativeFinder:
        return IterativeFinder(self.loop, self.peer_manager, self.routing_table, self, shortlist, key, rpc,
                               bottom_out_limit=bottom_out_limit)

    async def cumulative_find(self, rpc: str, key: bytes, shortlist: typing.Optional[typing.List] = None,
                              bottom_out_limit: int = constants.bottom_out_limit,
                              max_results: int = constants.k) -> typing.List[Peer]:
        results = []
        async for iteration_result in self.get_find_iterator(rpc, key, shortlist, bottom_out_limit, max_results):
            assert isinstance(iteration_result, list)
            for i in iteration_result:
                if i not in results:
                    results.append(i)
            log.debug("%s, %i, %i", rpc, len(iteration_result), len(results))
        return results

    async def cumulative_find_node(self, key: bytes, shortlist: typing.Optional[typing.List] = None,
                                   bottom_out_limit: int = constants.bottom_out_limit,
                                   max_results: int = constants.k) -> typing.List[Peer]:
        return await self.cumulative_find('findNode', key, shortlist, bottom_out_limit, max_results)

    async def cumulative_find_value(self, key: bytes, shortlist: typing.Optional[typing.List] = None,
                                    bottom_out_limit: int = constants.bottom_out_limit,
                                    max_results: int = constants.k) -> typing.List[Peer]:
        return await self.cumulative_find('findValue', key, shortlist, bottom_out_limit, max_results)

    async def store_to_contact(self, hash_value: bytes, contact: Peer) -> typing.Tuple[bytes, bool]:
        try:
            if not contact.token:
                await contact.find_value(hash_value)
            res = await contact.store(hash_value, contact.token, self.peer_port, self.node_id, 0)
            if res != b"OK":
                raise ValueError(res)
            log.debug("Stored %s to %s (%s)", binascii.hexlify(hash_value), contact.log_id(), contact.address)
            return contact.node_id, True
        except TimeoutError:
            log.debug("Timeout while storing blob_hash %s at %s",
                      binascii.hexlify(hash_value), contact.log_id())
        except ValueError as err:
            log.error("Unexpected response: %s" % err)
        except Exception as err:
            if 'Invalid token' in str(err):
                contact.update_token(None)
            log.error("Unexpected error while storing blob_hash %s at %s: %s",
                      binascii.hexlify(hash_value), contact, err)
        return contact.node_id, False

    # async def iterative_announce_hash(self, hash_value: bytes) -> typing.List[bytes]:
    #     assert len(hash_value) == constants.hash_length
    #     contacts = await self.cumulative_find_node(hash_value)
    #
    #     if not self.external_ip:
    #         raise Exception("Cannot determine external IP")
    #
    #     stored_to_tup = await asyncio.gather(*(asyncio.ensure_future(
    #         self.store_to_contact(hash_value, self.peer_manager.get_peer(peer.node_id, peer.host, peer.))) for peer in contacts
    #     ))
    #     contacted_node_ids = [binascii.hexlify(node_id) for node_id, contacted in stored_to_tup if contacted]
    #     log.debug("Stored %s to %i of %i attempted peers", binascii.hexlify(hash_value),
    #               len(contacted_node_ids), len(contacts))
    #     return contacted_node_ids

    def _schedule_send_next(self, txData, address):
        """Schedule the sending of the next UDP packet """
        delayed_call = self.loop.call_soon(self._write, txData, address)

    def _write(self, txData, address):
        if self.transport:
            try:
                self.transport.sendto(txData, address)
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
                              len(txData), address[0], address[1], str(err), err.errno)
                    print("write error")
                    raise err
        else:
            raise TransportNotConnected()


    #
    # def startProtocol(self):
    #     log.info("DHT listening on UDP %i (ext port %i)", self._node.port, self._node.externalUDPPort)
    #     if self._listening.called:
    #         self._listening = defer.Deferred()
    #     self._listening.callback(True)
    #     self.started_listening_time = self._node.clock.seconds()
    #     return self._ping_queue.start()


    # def _msgTimeout(self, messageID):
    #     """ Called when an RPC request message times out """
    #     # Find the message that timed out
    #     if messageID not in self._sentMessages:
    #         # This should never be reached
    #         log.error("deferred timed out, but is not present in sent messages list!")
    #         return
    #     remoteContact, df, timeout_call, timeout_canceller, method, args = self._sentMessages[messageID]
    #     if messageID in self._partialMessages:
    #         # We are still receiving this message
    #         self._msgTimeoutInProgress(messageID, timeout_canceller, remoteContact, df, method, args)
    #         return
    #     del self._sentMessages[messageID]
    #     # The message's destination node is now considered to be dead;
    #     # raise an (asynchronous) TimeoutError exception and update the host node
    #     df.errback(TimeoutError(remoteContact.node_id))
    #
    # def _msgTimeoutInProgress(self, messageID, timeoutCanceller, remoteContact, df, method, args):
    #     # See if any progress has been made; if not, kill the message
    #     if self._hasProgressBeenMade(messageID):
    #         # Reset the RPC timeout timer
    #         timeoutCanceller()
    #         timeoutCall, cancelTimeout = self._node.reactor_callLater(
    #             constants.rpcTimeout, self._msgTimeout, messageID
    #         )
    #         self._sentMessages[messageID] = (
    #             remoteContact, df, timeoutCall, cancelTimeout, method, args
    #         )
    #     else:
    #         # No progress has been made
    #         if messageID in self._partialMessagesProgress:
    #             del self._partialMessagesProgress[messageID]
    #         if messageID in self._partialMessages:
    #             del self._partialMessages[messageID]
    #         df.errback(TimeoutError(remoteContact.node_id))
    #
    # def _hasProgressBeenMade(self, messageID):
    #     return (
    #         messageID in self._partialMessagesProgress and
    #         (
    #             len(self._partialMessagesProgress[messageID]) !=
    #             len(self._partialMessages[messageID])
    #         )
    #     )
    #
    # def stopProtocol(self):
    #     """ Called when the transport is disconnected.
    #
    #     Will only be called once, after all ports are disconnected.
    #     """
    #     log.info('Stopping DHT')
    #     self._ping_queue.stop()
    #     self._node.call_later_manager.stop()
    #     log.info('DHT stopped')
