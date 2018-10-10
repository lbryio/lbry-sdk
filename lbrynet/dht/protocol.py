import logging
import errno
from binascii import hexlify

from twisted.internet import protocol, defer
from .error import BUILTIN_EXCEPTIONS, UnknownRemoteException, TimeoutError, TransportNotConnected

from . import constants
from . import encoding
from . import msgtypes
from . import msgformat

log = logging.getLogger(__name__)


class PingQueue:
    """
    Schedules a 15 minute delayed ping after a new node sends us a query. This is so the new node gets added to the
    routing table after having been given enough time for a pinhole to expire.
    """

    def __init__(self, node):
        self._node = node
        self._enqueued_contacts = {}
        self._pending_contacts = {}
        self._process_lc = node.get_looping_call(self._process)

    def enqueue_maybe_ping(self, *contacts, **kwargs):
        delay = kwargs.get('delay', constants.checkRefreshInterval)
        no_op = (defer.succeed(None), lambda: None)
        for contact in contacts:
            if delay and contact not in self._enqueued_contacts:
                self._pending_contacts.setdefault(contact, self._node.clock.seconds() + delay)
            else:
                self._enqueued_contacts.setdefault(contact, no_op)

    @defer.inlineCallbacks
    def _ping(self, contact):
        if contact.contact_is_good:
            return
        try:
            yield contact.ping()
        except TimeoutError:
            pass
        except Exception as err:
            log.warning("unexpected error: %s", err)
        finally:
            if contact in self._enqueued_contacts:
                del self._enqueued_contacts[contact]

    def _process(self):
        # move contacts that are scheduled to join the queue
        if self._pending_contacts:
            now = self._node.clock.seconds()
            for contact in [contact for contact, schedule in self._pending_contacts.items() if schedule <= now]:
                del self._pending_contacts[contact]
                self._enqueued_contacts.setdefault(contact, (defer.succeed(None), lambda: None))
        # spread pings across 60 seconds to avoid flood and/or false negatives
        step = 60.0/float(len(self._enqueued_contacts)) if self._enqueued_contacts else 0
        for index, (contact, (call, _)) in enumerate(self._enqueued_contacts.items()):
            if call.called and not contact.contact_is_good:
                self._enqueued_contacts[contact] = self._node.reactor_callLater(index*step, self._ping, contact)

    def start(self):
        return self._node.safe_start_looping_call(self._process_lc, 60)

    def stop(self):
        map(None, (cancel() for _, (call, cancel) in self._enqueued_contacts.items() if not call.called))
        return self._node.safe_stop_looping_call(self._process_lc)


class KademliaProtocol(protocol.DatagramProtocol):
    """ Implements all low-level network-related functions of a Kademlia node """

    msgSizeLimit = constants.udpDatagramMaxSize - 26

    def __init__(self, node):
        self._node = node
        self._translator = msgformat.DefaultFormat()
        self._sentMessages = {}
        self._partialMessages = {}
        self._partialMessagesProgress = {}
        self._listening = defer.Deferred(None)
        self._ping_queue = PingQueue(self._node)
        self._protocolVersion = constants.protocolVersion
        self.started_listening_time = 0

    def _migrate_incoming_rpc_args(self, contact, method, *args):
        if method == b'store' and contact.protocolVersion == 0:
            if isinstance(args[1], dict):
                blob_hash = args[0]
                token = args[1].pop(b'token', None)
                port = args[1].pop(b'port', -1)
                originalPublisherID = args[1].pop(b'lbryid', None)
                age = 0
                return (blob_hash, token, port, originalPublisherID, age), {}
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
            args[-1][b'protocolVersion'] = self._protocolVersion
            return args
        return args + ({b'protocolVersion': self._protocolVersion},)

    def sendRPC(self, contact, method, args):
        """
        Sends an RPC to the specified contact

        @param contact: The contact (remote node) to send the RPC to
        @type contact: kademlia.contacts.Contact
        @param method: The name of remote method to invoke
        @type method: str
        @param args: A list of (non-keyword) arguments to pass to the remote
                    method, in the correct order
        @type args: tuple

        @return: This immediately returns a deferred object, which will return
                 the result of the RPC call, or raise the relevant exception
                 if the remote node raised one. If C{rawResponse} is set to
                 C{True}, however, it will always return the actual response
                 message (which may be a C{ResponseMessage} or an
                 C{ErrorMessage}).
        @rtype: twisted.internet.defer.Deferred
        """
        msg = msgtypes.RequestMessage(self._node.node_id, method, self._migrate_outgoing_rpc_args(contact, method,
                                                                                                  *args))
        msgPrimitive = self._translator.toPrimitive(msg)
        encodedMsg = encoding.bencode(msgPrimitive)

        if args:
            log.debug("%s:%i SEND CALL %s(%s) TO %s:%i", self._node.externalIP, self._node.port, method,
                      hexlify(args[0]), contact.address, contact.port)
        else:
            log.debug("%s:%i SEND CALL %s TO %s:%i", self._node.externalIP, self._node.port, method,
                      contact.address, contact.port)

        df = defer.Deferred()

        def _remove_contact(failure):  # remove the contact from the routing table and track the failure
            try:
                self._node.removeContact(contact)
            except (ValueError, IndexError):
                pass
            contact.update_last_failed()
            return failure

        def _update_contact(result):  # refresh the contact in the routing table
            contact.update_last_replied()
            if method == b'findValue':
                if b'token' in result:
                    contact.update_token(result[b'token'])
                if b'protocolVersion' not in result:
                    contact.update_protocol_version(0)
                else:
                    contact.update_protocol_version(result.pop(b'protocolVersion'))
            d = self._node.addContact(contact)
            d.addCallback(lambda _: result)
            return d

        df.addCallbacks(_update_contact, _remove_contact)

        # Set the RPC timeout timer
        timeoutCall, cancelTimeout = self._node.reactor_callLater(constants.rpcTimeout, self._msgTimeout, msg.id)

        # Transmit the data
        self._send(encodedMsg, msg.id, (contact.address, contact.port))
        self._sentMessages[msg.id] = (contact, df, timeoutCall, cancelTimeout, method, args)

        df.addErrback(cancelTimeout)
        return df

    def startProtocol(self):
        log.info("DHT listening on UDP %i (ext port %i)", self._node.port, self._node.externalUDPPort)
        if self._listening.called:
            self._listening = defer.Deferred()
        self._listening.callback(True)
        self.started_listening_time = self._node.clock.seconds()
        return self._ping_queue.start()

    def datagramReceived(self, datagram, address):
        """ Handles and parses incoming RPC messages (and responses)

        @note: This is automatically called by Twisted when the protocol
               receives a UDP datagram
        """
        if chr(datagram[0]) == '\x00' and chr(datagram[25]) == '\x00':
            totalPackets = (datagram[1] << 8) | datagram[2]
            msgID = datagram[5:25]
            seqNumber = (datagram[3] << 8) | datagram[4]
            if msgID not in self._partialMessages:
                self._partialMessages[msgID] = {}
            self._partialMessages[msgID][seqNumber] = datagram[26:]
            if len(self._partialMessages[msgID]) == totalPackets:
                keys = self._partialMessages[msgID].keys()
                keys.sort()
                data = b''
                for key in keys:
                    data += self._partialMessages[msgID][key]
                    datagram = data
                del self._partialMessages[msgID]
            else:
                return
        try:
            msgPrimitive = encoding.bdecode(datagram)
            message = self._translator.fromPrimitive(msgPrimitive)
        except (encoding.DecodeError, ValueError) as err:
            # We received some rubbish here
            log.warning("Error decoding datagram %s from %s:%i - %s", datagram.encode('hex'),
                        address[0], address[1], err)
            return
        except (IndexError, KeyError):
            log.warning("Couldn't decode dht datagram from %s", address)
            return

        if isinstance(message, msgtypes.RequestMessage):
            # This is an RPC method request
            remoteContact = self._node.contact_manager.make_contact(message.nodeID, address[0], address[1], self)
            remoteContact.update_last_requested()
            # only add a requesting contact to the routing table if it has replied to one of our requests
            if remoteContact.contact_is_good is True:
                df = self._node.addContact(remoteContact)
            else:
                df = defer.succeed(None)
            df.addCallback(lambda _: self._handleRPC(remoteContact, message.id, message.request, message.args))
            # if the contact is not known to be bad (yet) and we haven't yet queried it, send it a ping so that it
            # will be added to our routing table if successful
            if remoteContact.contact_is_good is None and remoteContact.lastReplied is None:
                df.addCallback(lambda _: self._ping_queue.enqueue_maybe_ping(remoteContact))
        elif isinstance(message, msgtypes.ErrorMessage):
            # The RPC request raised a remote exception; raise it locally
            if message.exceptionType in BUILTIN_EXCEPTIONS:
                exception_type = BUILTIN_EXCEPTIONS[message.exceptionType]
            else:
                exception_type = UnknownRemoteException
            remoteException = exception_type(message.response)
            log.error("DHT RECV REMOTE EXCEPTION FROM %s:%i: %s", address[0],
                      address[1], remoteException)
            if message.id in self._sentMessages:
                # Cancel timeout timer for this RPC
                remoteContact, df, timeoutCall, timeoutCanceller, method = self._sentMessages[message.id][0:5]
                timeoutCanceller()
                del self._sentMessages[message.id]

                # reject replies coming from a different address than what we sent our request to
                if (remoteContact.address, remoteContact.port) != address:
                    log.warning("Sent request to node %s at %s:%i, got reply from %s:%i",
                                remoteContact.log_id(), remoteContact.address,
                                remoteContact.port, address[0], address[1])
                    df.errback(TimeoutError(remoteContact.id))
                    return

                # this error is returned by nodes that can be contacted but have an old
                # and broken version of the ping command, if they return it the node can
                # be contacted, so we'll treat it as a successful ping
                old_ping_error = "ping() got an unexpected keyword argument '_rpcNodeContact'"
                if isinstance(remoteException, TypeError) and \
                        remoteException.message == old_ping_error:
                    log.debug("old pong error")
                    df.callback('pong')
                else:
                    df.errback(remoteException)
        elif isinstance(message, msgtypes.ResponseMessage):
            # Find the message that triggered this response
            if message.id in self._sentMessages:
                # Cancel timeout timer for this RPC
                remoteContact, df, timeoutCall, timeoutCanceller, method = self._sentMessages[message.id][0:5]
                timeoutCanceller()
                del self._sentMessages[message.id]
                log.debug("%s:%i RECV response to %s from %s:%i", self._node.externalIP, self._node.port,
                          method, remoteContact.address, remoteContact.port)

                # When joining the network we made Contact objects for the seed nodes with node ids set to None
                # Thus, the sent_to_id will also be None, and the contact objects need the ids to be manually set.
                # These replies have be distinguished from those where the node id in the datagram does not match
                # the node id of the node we sent a message to (these messages are treated as an error)
                if remoteContact.id and remoteContact.id != message.nodeID:  # sent_to_id will be None for bootstrap
                    log.debug("mismatch: (%s) %s:%i (%s vs %s)", method, remoteContact.address, remoteContact.port,
                              remoteContact.log_id(False), hexlify(message.nodeID))
                    df.errback(TimeoutError(remoteContact.id))
                    return
                elif not remoteContact.id:
                    remoteContact.set_id(message.nodeID)

                # We got a result from the RPC
                df.callback(message.response)
            else:
                # If the original message isn't found, it must have timed out
                # TODO: we should probably do something with this...
                pass

    def _send(self, data, rpcID, address):
        """ Transmit the specified data over UDP, breaking it up into several
        packets if necessary

        If the data is spread over multiple UDP datagrams, the packets have the
        following structure::
            |           |     |      |      |        ||||||||||||   0x00   |
            |Transmision|Total number|Sequence number| RPC ID   |Header end|
            | type ID   | of packets |of this packet |          | indicator|
            | (1 byte)  | (2 bytes)  |  (2 bytes)    |(20 bytes)| (1 byte) |
            |           |     |      |      |        ||||||||||||          |

        @note: The header used for breaking up large data segments will
               possibly be moved out of the KademliaProtocol class in the
               future, into something similar to a message translator/encoder
               class (see C{kademlia.msgformat} and C{kademlia.encoding}).
        """

        if len(data) > self.msgSizeLimit:
            # We have to spread the data over multiple UDP datagrams,
            # and provide sequencing information
            #
            # 1st byte is transmission type id, bytes 2 & 3 are the
            # total number of packets in this transmission, bytes 4 &
            # 5 are the sequence number for this specific packet
            totalPackets = len(data) // self.msgSizeLimit
            if len(data) % self.msgSizeLimit > 0:
                totalPackets += 1
            encTotalPackets = chr(totalPackets >> 8) + chr(totalPackets & 0xff)
            seqNumber = 0
            startPos = 0
            while seqNumber < totalPackets:
                packetData = data[startPos:startPos + self.msgSizeLimit]
                encSeqNumber = chr(seqNumber >> 8) + chr(seqNumber & 0xff)
                txData = '\x00%s%s%s\x00%s' % (encTotalPackets, encSeqNumber, rpcID, packetData)
                self._scheduleSendNext(txData, address)

                startPos += self.msgSizeLimit
                seqNumber += 1
        else:
            self._scheduleSendNext(data, address)

    def _scheduleSendNext(self, txData, address):
        """Schedule the sending of the next UDP packet """
        delayed_call, _ = self._node.reactor_callSoon(self._write, txData, address)

    def _write(self, txData, address):
        if self.transport:
            try:
                self.transport.write(txData, address)
            except OSError as err:
                if err.errno == errno.EWOULDBLOCK:
                    # i'm scared this may swallow important errors, but i get a million of these
                    # on Linux and it doesnt seem to affect anything  -grin
                    log.warning("Can't send data to dht: EWOULDBLOCK")
                elif err.errno == errno.ENETUNREACH:
                    # this should probably try to retransmit when the network connection is back
                    log.error("Network is unreachable")
                else:
                    log.error("DHT socket error sending %i bytes to %s:%i - %s (code %i)",
                              len(txData), address[0], address[1], err.message, err.errno)
                    raise err
        else:
            raise TransportNotConnected()

    def _sendResponse(self, contact, rpcID, response):
        """ Send a RPC response to the specified contact
        """
        msg = msgtypes.ResponseMessage(rpcID, self._node.node_id, response)
        msgPrimitive = self._translator.toPrimitive(msg)
        encodedMsg = encoding.bencode(msgPrimitive)
        self._send(encodedMsg, rpcID, (contact.address, contact.port))

    def _sendError(self, contact, rpcID, exceptionType, exceptionMessage):
        """ Send an RPC error message to the specified contact
        """
        exceptionMessage = exceptionMessage.encode()
        msg = msgtypes.ErrorMessage(rpcID, self._node.node_id, exceptionType, exceptionMessage)
        msgPrimitive = self._translator.toPrimitive(msg)
        encodedMsg = encoding.bencode(msgPrimitive)
        self._send(encodedMsg, rpcID, (contact.address, contact.port))

    def _handleRPC(self, senderContact, rpcID, method, args):
        """ Executes a local function in response to an RPC request """

        # Set up the deferred callchain
        def handleError(f):
            self._sendError(senderContact, rpcID, f.type, f.getErrorMessage())

        def handleResult(result):
            self._sendResponse(senderContact, rpcID, result)

        df = defer.Deferred()
        df.addCallback(handleResult)
        df.addErrback(handleError)

        # Execute the RPC
        func = getattr(self._node, method.decode(), None)
        if callable(func) and hasattr(func, "rpcmethod"):
            # Call the exposed Node method and return the result to the deferred callback chain
            # if args:
            #     log.debug("%s:%i RECV CALL %s(%s) %s:%i", self._node.externalIP, self._node.port, method,
            #               args[0].encode('hex'), senderContact.address, senderContact.port)
            # else:
            log.debug("%s:%i RECV CALL %s %s:%i", self._node.externalIP, self._node.port, method,
                          senderContact.address, senderContact.port)
            if args and isinstance(args[-1], dict) and b'protocolVersion' in args[-1]:  # args don't need reformatting
                senderContact.update_protocol_version(int(args[-1].pop(b'protocolVersion')))
                a, kw = tuple(args[:-1]), args[-1]
            else:
                senderContact.update_protocol_version(0)
                a, kw = self._migrate_incoming_rpc_args(senderContact, method, *args)
            try:
                if method != b'ping':
                    result = func(senderContact, *a)
                else:
                    result = func()
            except Exception as e:
                log.exception("error handling request for %s:%i %s", senderContact.address, senderContact.port, method)
                df.errback(e)
            else:
                df.callback(result)
        else:
            # No such exposed method
            df.errback(AttributeError('Invalid method: %s' % method))
        return df

    def _msgTimeout(self, messageID):
        """ Called when an RPC request message times out """
        # Find the message that timed out
        if messageID not in self._sentMessages:
            # This should never be reached
            log.error("deferred timed out, but is not present in sent messages list!")
            return
        remoteContact, df, timeout_call, timeout_canceller, method, args = self._sentMessages[messageID]
        if messageID in self._partialMessages:
            # We are still receiving this message
            self._msgTimeoutInProgress(messageID, timeout_canceller, remoteContact, df, method, args)
            return
        del self._sentMessages[messageID]
        # The message's destination node is now considered to be dead;
        # raise an (asynchronous) TimeoutError exception and update the host node
        df.errback(TimeoutError(remoteContact.id))

    def _msgTimeoutInProgress(self, messageID, timeoutCanceller, remoteContact, df, method, args):
        # See if any progress has been made; if not, kill the message
        if self._hasProgressBeenMade(messageID):
            # Reset the RPC timeout timer
            timeoutCanceller()
            timeoutCall, cancelTimeout = self._node.reactor_callLater(constants.rpcTimeout, self._msgTimeout, messageID)
            self._sentMessages[messageID] = (remoteContact, df, timeoutCall, cancelTimeout, method, args)
        else:
            # No progress has been made
            if messageID in self._partialMessagesProgress:
                del self._partialMessagesProgress[messageID]
            if messageID in self._partialMessages:
                del self._partialMessages[messageID]
            df.errback(TimeoutError(remoteContact.id))

    def _hasProgressBeenMade(self, messageID):
        return (
            messageID in self._partialMessagesProgress and
            (
                len(self._partialMessagesProgress[messageID]) !=
                len(self._partialMessages[messageID])
            )
        )

    def stopProtocol(self):
        """ Called when the transport is disconnected.

        Will only be called once, after all ports are disconnected.
        """
        log.info('Stopping DHT')
        self._ping_queue.stop()
        self._node.call_later_manager.stop()
        log.info('DHT stopped')
