import logging
import socket
import errno

from twisted.internet import protocol, defer
from lbrynet.core.call_later_manager import CallLaterManager

import constants
import encoding
import msgtypes
import msgformat
from contact import Contact
from error import BUILTIN_EXCEPTIONS, UnknownRemoteException, TimeoutError

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
        timeoutCall, cancelTimeout = self._node.reactor_callLater(constants.rpcTimeout, self._msgTimeout, msg.id)
        # Transmit the data
        self._send(encodedMsg, msg.id, (contact.address, contact.port))
        self._sentMessages[msg.id] = (contact.id, df, timeoutCall, method, args)
        df.addErrback(cancelTimeout)
        return df

    def startProtocol(self):
        log.info("DHT listening on UDP %i", self._node.port)

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
        except (encoding.DecodeError, ValueError) as err:
            # We received some rubbish here
            log.exception("Error decoding datagram from %s:%i - %s", address[0], address[1], err)
            return
        except (IndexError, KeyError):
            log.warning("Couldn't decode dht datagram from %s", address)
            return

        remoteContact = Contact(message.nodeID, address[0], address[1], self)

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
        delayed_call, _ = self._node.reactor_callLater(0, self._write, txData, address)

    def _write(self, txData, address):
        if self.transport:
            try:
                self.transport.write(txData, address)
            except socket.error as err:
                if err.errno == errno.EWOULDBLOCK:
                    # i'm scared this may swallow important errors, but i get a million of these
                    # on Linux and it doesnt seem to affect anything  -grin
                    log.warning("Can't send data to dht: EWOULDBLOCK")
                elif err.errno == errno.ENETUNREACH:
                    # this should probably try to retransmit when the network connection is back
                    log.error("Network is unreachable")
                else:
                    log.error("DHT socket error: %s (%i)", err.message, err.errno)
                    raise err
        else:
            log.warning("transport not connected!")

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
            timeoutCall, _ = self._node.reactor_callLater(constants.rpcTimeout, self._msgTimeout, messageID)
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
        CallLaterManager.stop()
        log.info('DHT stopped')
