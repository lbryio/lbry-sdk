import logging
import time
import socket
import errno

from twisted.internet import protocol, defer, error, reactor, task

import constants
import encoding
import msgtypes
import msgformat
from contact import Contact
from error import BUILTIN_EXCEPTIONS, UnknownRemoteException, TimeoutError
from delay import Delay

log = logging.getLogger(__name__)


class KademliaProtocol(protocol.DatagramProtocol):
    """ Implements all low-level network-related functions of a Kademlia node """

    msgSizeLimit = constants.udpDatagramMaxSize - 26

    def __init__(self, node):
        self._node = node
        self._encoder = encoding.Bencode()
        self._translator = msgformat.DefaultFormat()
        self._sentMessages = {}
        self._partialMessages = {}
        self._partialMessagesProgress = {}
        self._delay = Delay()
        # keep track of outstanding writes so that they
        # can be cancelled on shutdown
        self._call_later_list = {}

        # keep track of bandwidth usage by peer
        self._history_rx = {}
        self._history_tx = {}
        self._bytes_rx = {}
        self._bytes_tx = {}
        self._unique_contacts = []
        self._queries_rx_per_second = 0
        self._queries_tx_per_second = 0
        self._kbps_tx = 0
        self._kbps_rx = 0
        self._recent_contact_count = 0
        self._total_bytes_tx = 0
        self._total_bytes_rx = 0
        self._bandwidth_stats_update_lc = task.LoopingCall(self._update_bandwidth_stats)

    def _update_bandwidth_stats(self):
        recent_rx_history = {}
        now = time.time()
        for address, history in self._history_rx.iteritems():
            recent_rx_history[address] = [(s, t) for (s, t) in history if now - t < 1.0]
        qps_rx = sum(len(v) for (k, v) in recent_rx_history.iteritems())
        bps_rx = sum(sum([x[0] for x in v]) for (k, v) in recent_rx_history.iteritems())
        kbps_rx = round(float(bps_rx) / 1024.0, 2)

        recent_tx_history = {}
        now = time.time()
        for address, history in self._history_tx.iteritems():
            recent_tx_history[address] = [(s, t) for (s, t) in history if now - t < 1.0]
        qps_tx = sum(len(v) for (k, v) in recent_tx_history.iteritems())
        bps_tx = sum(sum([x[0] for x in v]) for (k, v) in recent_tx_history.iteritems())
        kbps_tx = round(float(bps_tx) / 1024.0, 2)

        recent_contacts = []
        for k, v in recent_rx_history.iteritems():
            if v:
                recent_contacts.append(k)
        for k, v in recent_tx_history.iteritems():
            if v and k not in recent_contacts:
                recent_contacts.append(k)

        self._queries_rx_per_second = qps_rx
        self._queries_tx_per_second = qps_tx
        self._kbps_tx = kbps_tx
        self._kbps_rx = kbps_rx
        self._recent_contact_count = len(recent_contacts)
        self._total_bytes_tx = sum(v for (k, v) in self._bytes_tx.iteritems())
        self._total_bytes_rx = sum(v for (k, v) in self._bytes_rx.iteritems())

    @property
    def unique_contacts(self):
        return self._unique_contacts

    @property
    def queries_rx_per_second(self):
        return self._queries_rx_per_second

    @property
    def queries_tx_per_second(self):
        return self._queries_tx_per_second

    @property
    def kbps_tx(self):
        return self._kbps_tx

    @property
    def kbps_rx(self):
        return self._kbps_rx

    @property
    def recent_contact_count(self):
        return self._recent_contact_count

    @property
    def total_bytes_tx(self):
        return self._total_bytes_tx

    @property
    def total_bytes_rx(self):
        return self._total_bytes_rx

    @property
    def bandwidth_stats(self):
        response = {
            "kbps_received": self.kbps_rx,
            "kbps_sent": self.kbps_tx,
            "total_bytes_sent": self.total_bytes_tx,
            "total_bytes_received": self.total_bytes_rx,
            "queries_received": self.queries_rx_per_second,
            "queries_sent": self.queries_tx_per_second,
            "recent_contacts": self.recent_contact_count,
            "unique_contacts": len(self.unique_contacts)
        }
        return response

    def sendRPC(self, contact, method, args, rawResponse=False):
        """ Sends an RPC to the specified contact

        @param contact: The contact (remote node) to send the RPC to
        @type contact: kademlia.contacts.Contact
        @param method: The name of remote method to invoke
        @type method: str
        @param args: A list of (non-keyword) arguments to pass to the remote
                    method, in the correct order
        @type args: tuple
        @param rawResponse: If this is set to C{True}, the caller of this RPC
                            will receive a tuple containing the actual response
                            message object and the originating address tuple as
                            a result; in other words, it will not be
                            interpreted by this class. Unless something special
                            needs to be done with the metadata associated with
                            the message, this should remain C{False}.
        @type rawResponse: bool

        @return: This immediately returns a deferred object, which will return
                 the result of the RPC call, or raise the relevant exception
                 if the remote node raised one. If C{rawResponse} is set to
                 C{True}, however, it will always return the actual response
                 message (which may be a C{ResponseMessage} or an
                 C{ErrorMessage}).
        @rtype: twisted.internet.defer.Deferred
        """
        msg = msgtypes.RequestMessage(self._node.node_id, method, args)
        msgPrimitive = self._translator.toPrimitive(msg)
        encodedMsg = self._encoder.encode(msgPrimitive)

        if args:
            log.debug("DHT SEND CALL %s(%s)", method, args[0].encode('hex'))
        else:
            log.debug("DHT SEND CALL %s", method)

        df = defer.Deferred()
        if rawResponse:
            df._rpcRawResponse = True

        # Set the RPC timeout timer
        timeoutCall = reactor.callLater(constants.rpcTimeout, self._msgTimeout, msg.id)
        # Transmit the data
        self._send(encodedMsg, msg.id, (contact.address, contact.port))
        self._sentMessages[msg.id] = (contact.id, df, timeoutCall, method, args)
        return df

    def startProtocol(self):
        log.info("DHT listening on UDP %i", self._node.port)
        if not self._bandwidth_stats_update_lc.running:
            self._bandwidth_stats_update_lc.start(1)

    def datagramReceived(self, datagram, address):
        """ Handles and parses incoming RPC messages (and responses)

        @note: This is automatically called by Twisted when the protocol
               receives a UDP datagram
        """

        if datagram[0] == '\x00' and datagram[25] == '\x00':
            totalPackets = (ord(datagram[1]) << 8) | ord(datagram[2])
            msgID = datagram[5:25]
            seqNumber = (ord(datagram[3]) << 8) | ord(datagram[4])
            if msgID not in self._partialMessages:
                self._partialMessages[msgID] = {}
            self._partialMessages[msgID][seqNumber] = datagram[26:]
            if len(self._partialMessages[msgID]) == totalPackets:
                keys = self._partialMessages[msgID].keys()
                keys.sort()
                data = ''
                for key in keys:
                    data += self._partialMessages[msgID][key]
                    datagram = data
                del self._partialMessages[msgID]
            else:
                return
        try:
            msgPrimitive = self._encoder.decode(datagram)
            message = self._translator.fromPrimitive(msgPrimitive)
        except (encoding.DecodeError, ValueError):
            # We received some rubbish here
            return
        except IndexError:
            log.warning("Couldn't decode dht datagram from %s", address)
            return

        remoteContact = Contact(message.nodeID, address[0], address[1], self)

        now = time.time()
        contact_history = self._history_rx.get(address, [])
        if len(contact_history) > 1000:
            contact_history = [x for x in contact_history if now - x[1] < 1.0]
        contact_history.append((len(datagram), time.time()))
        self._history_rx[address] = contact_history
        bytes_rx = self._bytes_rx.get(address, 0)
        bytes_rx += len(datagram)
        self._bytes_rx[address] = bytes_rx
        if address not in self.unique_contacts:
            self._unique_contacts.append(address)

        # Refresh the remote node's details in the local node's k-buckets
        self._node.addContact(remoteContact)
        if isinstance(message, msgtypes.RequestMessage):
            # This is an RPC method request
            self._handleRPC(remoteContact, message.id, message.request, message.args)

        elif isinstance(message, msgtypes.ResponseMessage):
            # Find the message that triggered this response
            if message.id in self._sentMessages:
                # Cancel timeout timer for this RPC
                df, timeoutCall = self._sentMessages[message.id][1:3]
                timeoutCall.cancel()
                del self._sentMessages[message.id]

                if hasattr(df, '_rpcRawResponse'):
                    # The RPC requested that the raw response message
                    # and originating address be returned; do not
                    # interpret it
                    df.callback((message, address))
                elif isinstance(message, msgtypes.ErrorMessage):
                    # The RPC request raised a remote exception; raise it locally
                    if message.exceptionType in BUILTIN_EXCEPTIONS:
                        exception_type = BUILTIN_EXCEPTIONS[message.exceptionType]
                    else:
                        exception_type = UnknownRemoteException
                    remoteException = exception_type(message.response)
                    # this error is returned by nodes that can be contacted but have an old
                    # and broken version of the ping command, if they return it the node can
                    # be contacted, so we'll treat it as a successful ping
                    old_ping_error = "ping() got an unexpected keyword argument '_rpcNodeContact'"
                    if isinstance(remoteException, TypeError) and \
                                    remoteException.message == old_ping_error:
                        log.debug("old pong error")
                        df.callback('pong')
                    else:
                        log.error("DHT RECV REMOTE EXCEPTION FROM %s:%i: %s", address[0],
                                  address[1], remoteException)
                        df.errback(remoteException)
                else:
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

        now = time.time()
        contact_history = self._history_tx.get(address, [])
        if len(contact_history) > 1000:
            contact_history = [x for x in contact_history if now - x[1] < 1.0]
        contact_history.append((len(data), time.time()))
        self._history_tx[address] = contact_history
        bytes_tx = self._bytes_tx.get(address, 0)
        bytes_tx += len(data)
        self._bytes_tx[address] = bytes_tx
        if address not in self.unique_contacts:
            self._unique_contacts.append(address)

        if len(data) > self.msgSizeLimit:
            # We have to spread the data over multiple UDP datagrams,
            # and provide sequencing information
            #
            # 1st byte is transmission type id, bytes 2 & 3 are the
            # total number of packets in this transmission, bytes 4 &
            # 5 are the sequence number for this specific packet
            totalPackets = len(data) / self.msgSizeLimit
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
        delay = self._delay()
        key = object()
        delayed_call = reactor.callLater(delay, self._write_and_remove, key, txData, address)
        self._call_later_list[key] = delayed_call

    def _write_and_remove(self, key, txData, address):
        del self._call_later_list[key]
        if self.transport:
            try:
                self.transport.write(txData, address)
            except socket.error as err:
                if err.errno == errno.EWOULDBLOCK:
                    # i'm scared this may swallow important errors, but i get a million of these
                    # on Linux and it doesnt seem to affect anything  -grin
                    log.debug("Can't send data to dht: EWOULDBLOCK")
                elif err.errno == errno.ENETUNREACH:
                    # this should probably try to retransmit when the network connection is back
                    log.error("Network is unreachable")
                else:
                    log.error("DHT socket error: %s (%i)", err.message, err.errno)
                    raise err

    def _sendResponse(self, contact, rpcID, response):
        """ Send a RPC response to the specified contact
        """
        msg = msgtypes.ResponseMessage(rpcID, self._node.node_id, response)
        msgPrimitive = self._translator.toPrimitive(msg)
        encodedMsg = self._encoder.encode(msgPrimitive)
        self._send(encodedMsg, rpcID, (contact.address, contact.port))

    def _sendError(self, contact, rpcID, exceptionType, exceptionMessage):
        """ Send an RPC error message to the specified contact
        """
        msg = msgtypes.ErrorMessage(rpcID, self._node.node_id, exceptionType, exceptionMessage)
        msgPrimitive = self._translator.toPrimitive(msg)
        encodedMsg = self._encoder.encode(msgPrimitive)
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
        func = getattr(self._node, method, None)
        if callable(func) and hasattr(func, 'rpcmethod'):
            # Call the exposed Node method and return the result to the deferred callback chain
            if args:
                log.debug("DHT RECV CALL %s(%s) %s:%i", method, args[0].encode('hex'),
                          senderContact.address, senderContact.port)
            else:
                log.debug("DHT RECV CALL %s %s:%i", method, senderContact.address,
                          senderContact.port)
            try:
                if method != 'ping':
                    kwargs = {'_rpcNodeID': senderContact.id, '_rpcNodeContact': senderContact}
                    result = func(*args, **kwargs)
                else:
                    result = func()
            except Exception, e:
                log.exception("error handling request for %s: %s", senderContact.address, method)
                df.errback(e)
            else:
                df.callback(result)
        else:
            # No such exposed method
            df.errback(AttributeError('Invalid method: %s' % method))

    def _msgTimeout(self, messageID):
        """ Called when an RPC request message times out """
        # Find the message that timed out
        if messageID not in self._sentMessages:
            # This should never be reached
            log.error("deferred timed out, but is not present in sent messages list!")
            return
        remoteContactID, df, timeout_call, method, args = self._sentMessages[messageID]
        if self._partialMessages.has_key(messageID):
            # We are still receiving this message
            self._msgTimeoutInProgress(messageID, remoteContactID, df, method, args)
            return
        del self._sentMessages[messageID]
        # The message's destination node is now considered to be dead;
        # raise an (asynchronous) TimeoutError exception and update the host node
        self._node.removeContact(remoteContactID)
        df.errback(TimeoutError(remoteContactID))

    def _msgTimeoutInProgress(self, messageID, remoteContactID, df, method, args):
        # See if any progress has been made; if not, kill the message
        if self._hasProgressBeenMade(messageID):
            # Reset the RPC timeout timer
            timeoutCall = reactor.callLater(constants.rpcTimeout, self._msgTimeout, messageID)
            self._sentMessages[messageID] = (remoteContactID, df, timeoutCall, method, args)
        else:
            # No progress has been made
            if messageID in self._partialMessagesProgress:
                del self._partialMessagesProgress[messageID]
            if messageID in self._partialMessages:
                del self._partialMessages[messageID]
            df.errback(TimeoutError(remoteContactID))

    def _hasProgressBeenMade(self, messageID):
        return (
            self._partialMessagesProgress.has_key(messageID) and
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

        if self._bandwidth_stats_update_lc.running:
            self._bandwidth_stats_update_lc.stop()

        for delayed_call in self._call_later_list.values():
            try:
                delayed_call.cancel()
            except (error.AlreadyCalled, error.AlreadyCancelled):
                log.debug('Attempted to cancel a DelayedCall that was not active')
            except Exception:
                log.exception('Failed to cancel a DelayedCall')
                # not sure why this is needed, but taking this out sometimes causes
                # exceptions.AttributeError: 'Port' object has no attribute 'socket'
                # to happen on shutdown
                # reactor.iterate()
        log.info('DHT stopped')
