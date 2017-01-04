#!/usr/bin/env python
#
# This library is free software, distributed under the terms of
# the GNU Lesser General Public License Version 3, or any later version.
# See the COPYING file included in this archive
#
# The docstrings in this module contain epytext markup; API documentation
# may be created by processing this file with epydoc: http://epydoc.sf.net

import logging
import binascii
import time
import socket
import errno

from twisted.internet import protocol, defer
from twisted.python import failure
from twisted.internet import error
import twisted.internet.reactor

import constants
import encoding
import msgtypes
import msgformat
from contact import Contact


reactor = twisted.internet.reactor
log = logging.getLogger(__name__)


class TimeoutError(Exception):
    """ Raised when a RPC times out """
    def __init__(self, remote_contact_id):
        # remote_contact_id is a binary blob so we need to convert it
        # into something more readable
        msg = 'Timeout connecting to {}'.format(binascii.hexlify(remote_contact_id))
        Exception.__init__(self, msg)
        self.remote_contact_id = remote_contact_id


class Delay(object):
    maxToSendDelay = 10**-3 #0.05
    minToSendDelay = 10**-5 #0.01

    def __init__(self, start=0):
        self._next = start

    # TODO: explain why this logic is like it is. And add tests that
    #       show that it actually does what it needs to do.
    def __call__(self):
        ts = time.time()
        delay = 0
        if ts >= self._next:
            delay = self.minToSendDelay
            self._next = ts + self.minToSendDelay
        else:
            delay = (self._next - ts) + self.maxToSendDelay
            self._next += self.maxToSendDelay
        return delay


class KademliaProtocol(protocol.DatagramProtocol):
    """ Implements all low-level network-related functions of a Kademlia node """
    msgSizeLimit = constants.udpDatagramMaxSize-26


    def __init__(self, node, msgEncoder=encoding.Bencode(),
                 msgTranslator=msgformat.DefaultFormat()):
        self._node = node
        self._encoder = msgEncoder
        self._translator = msgTranslator
        self._sentMessages = {}
        self._partialMessages = {}
        self._partialMessagesProgress = {}
        self._delay = Delay()
        # keep track of outstanding writes so that they
        # can be cancelled on shutdown
        self._call_later_list = {}

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
        msg = msgtypes.RequestMessage(self._node.id, method, args)
        msgPrimitive = self._translator.toPrimitive(msg)
        encodedMsg = self._encoder.encode(msgPrimitive)

        df = defer.Deferred()
        if rawResponse:
            df._rpcRawResponse = True

        # Set the RPC timeout timer
        timeoutCall = reactor.callLater(
            constants.rpcTimeout, self._msgTimeout, msg.id) #IGNORE:E1101
        # Transmit the data
        self._send(encodedMsg, msg.id, (contact.address, contact.port))
        self._sentMessages[msg.id] = (contact.id, df, timeoutCall)
        return df

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
        except encoding.DecodeError:
            # We received some rubbish here
            return
        except IndexError:
            log.warning("Couldn't decode dht datagram from %s", address)
            return

        message = self._translator.fromPrimitive(msgPrimitive)
        remoteContact = Contact(message.nodeID, address[0], address[1], self)

        # Refresh the remote node's details in the local node's k-buckets
        self._node.addContact(remoteContact)

        if isinstance(message, msgtypes.RequestMessage):
            # This is an RPC method request
            self._handleRPC(remoteContact, message.id, message.request, message.args)
        elif isinstance(message, msgtypes.ResponseMessage):
            # Find the message that triggered this response
            if self._sentMessages.has_key(message.id):
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
                    if message.exceptionType.startswith('exceptions.'):
                        exceptionClassName = message.exceptionType[11:]
                    else:
                        localModuleHierarchy = self.__module__.split('.')
                        remoteHierarchy = message.exceptionType.split('.')
                        #strip the remote hierarchy
                        while remoteHierarchy[0] == localModuleHierarchy[0]:
                            remoteHierarchy.pop(0)
                            localModuleHierarchy.pop(0)
                        exceptionClassName = '.'.join(remoteHierarchy)
                    remoteException = None
                    try:
                        exec 'remoteException = %s("%s")' % (exceptionClassName, message.response)
                    except Exception:
                        # We could not recreate the exception; create a generic one
                        remoteException = Exception(message.response)
                    df.errback(remoteException)
                else:
                    # We got a result from the RPC
                    df.callback(message.response)
            else:
                # If the original message isn't found, it must have timed out
                #TODO: we should probably do something with this...
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
                packetData = data[startPos:startPos+self.msgSizeLimit]
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
                # i'm scared this may swallow important errors, but i get a million of these
                # on Linux and it doesnt seem to affect anything  -grin
                self.transport.write(txData, address)
            except socket.error as err:
                if err.errno != errno.EWOULDBLOCK:
                    raise err

    def _sendResponse(self, contact, rpcID, response):
        """ Send a RPC response to the specified contact
        """
        msg = msgtypes.ResponseMessage(rpcID, self._node.id, response)
        msgPrimitive = self._translator.toPrimitive(msg)
        encodedMsg = self._encoder.encode(msgPrimitive)
        self._send(encodedMsg, rpcID, (contact.address, contact.port))

    def _sendError(self, contact, rpcID, exceptionType, exceptionMessage):
        """ Send an RPC error message to the specified contact
        """
        msg = msgtypes.ErrorMessage(rpcID, self._node.id, exceptionType, exceptionMessage)
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
            try:
                kwargs = {'_rpcNodeID': senderContact.id, '_rpcNodeContact': senderContact}
                result = func(*args, **kwargs)
            except Exception, e:
                df.errback(failure.Failure(e))
            else:
                df.callback(result)
        else:
            # No such exposed method
            df.errback(failure.Failure(AttributeError('Invalid method: %s' % method)))

    def _msgTimeout(self, messageID):
        """ Called when an RPC request message times out """
        # Find the message that timed out
        if not self._sentMessages.has_key(messageID):
            # This should never be reached
            log.error("deferred timed out, but is not present in sent messages list!")
            return
        remoteContactID, df = self._sentMessages[messageID][0:2]
        if self._partialMessages.has_key(messageID):
            # We are still receiving this message
            self._msgTimeoutInProgress(messageID, remoteContactID, df)
            return
        del self._sentMessages[messageID]
        # The message's destination node is now considered to be dead;
        # raise an (asynchronous) TimeoutError exception and update the host node
        self._node.removeContact(remoteContactID)
        df.errback(failure.Failure(TimeoutError(remoteContactID)))

    def _msgTimeoutInProgress(self, messageID, remoteContactID, df):
        # See if any progress has been made; if not, kill the message
        if self._hasProgressBeenMade(messageID):
            # Reset the RPC timeout timer
            timeoutCall = reactor.callLater(constants.rpcTimeout, self._msgTimeout, messageID)
            self._sentMessages[messageID] = (remoteContactID, df, timeoutCall)
        else:
            # No progress has been made
            del self._partialMessagesProgress[messageID]
            del self._partialMessages[messageID]
            df.errback(failure.Failure(TimeoutError(remoteContactID)))

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
        log.info('Stopping dht')
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
