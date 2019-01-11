import asyncio
import json
import logging
import functools

from asyncio import protocols, transports
from typing import Any, Iterable, NoReturn, Optional, Union, Text, Tuple
from urllib.parse import quote_from_bytes

from twisted.protocols.basic import FileSender
from twisted.internet.protocol import Protocol, ClientFactory
from twisted.internet import defer, error

import lbrynet.extras.reflector.exceptions as err
from lbrynet.extras.reflector import REFLECTOR_V2

log = logging.getLogger(__name__)


class BlobProtocol(protocols.DatagramProtocol):
    protocol_version = REFLECTOR_V2
    
    def __init__(self, blob_manager: Any[object], blobs: Any[Iterable]):
        self._handshake_sent = False
        self._handshake_recv = False
        self._transport = None
        self.blob_manager = blob_manager
        self.blob_hashes_to_send = blobs
        self.response_buff = None
        self.outgoing_buff = None
        self.next_blob_to_send = None
        self.blob_read_handle = None
        self.file_sender = None
        self.reflected_blobs = None
        self.producer = None
        self.streaming = None
        self.current_blob = None
    
    def send_handshake(self) -> NoReturn:
        log.debug('Sending handshake')
        payload = json.dumps({'version': self.protocol_version})
        peer = self._transport.get_extra_info('peerhost')
        self._transport.sendto(data=payload.encode(), addr=peer)
        self._handshake_sent = True

    def connection_made(self, transport: transports.DatagramTransport) -> NoReturn:
        log.info("Connection established with %s", transport.get_extra_info('peerhost'))
        self.response_buff = b''
        self.outgoing_buff = ''
        self.next_blob_to_send = None
        self.blob_read_handle = None
        self.file_sender = None
        self.reflected_blobs = list
        self._transport = transport
        if not self._handshake_sent:
            await self.send_handshake()
    
    def connection_lost(self, exc: Optional[Exception]) -> NoReturn:
        if self._transport is None:
            if exc is err.ReflectorRequestError:
                log.error("Error during handshake: %s", exc)
            elif exc is err.ReflectorRequestDecodeError:
                log.error("Error when decoding payload: %s", quote_from_bytes(
                    json.dumps({'version': self.protocol_version}).encode()))
            elif exc is err.ReflectorClientVersionError:
                log.error("Invalid reflector protocol version: %i", self.protocol_version)
            else:
                log.error("An error occurred immediately: %s", exc)
            raise exc
        if exc is None:
            if self.reflected_blobs:
                log.info('Finished sending data via reflector')
        log.info('Reflector finished: %s', exc)
        raise exc

    async def get_server_info(self, message: Union[bytes, dict]):
        if 'send_blob' not in message:
            raise ValueError("I don't know whether to send the blob or not!")
        if message['send_blob'] is True:
            # TODO: FileSender Factory/Protocol?
            self.file_sender = None  # FileSender()
        else:
            if self.next_blob_to_send is not None:
                self.next_blob_to_send = None
            self.file_sender = None
    
    async def get_blob_response(self, message: Union[bytes, dict]):
        if 'received_blob' not in message:
            raise ValueError("I don't know if the blob made it to the intended destination!")
        else:
            if message['received_blob']:
                self.reflected_blobs.append(self.next_blob_to_send.blob_hash)
            if self.next_blob_to_send is not None:
                self.next_blob_to_send = None
            self.file_sender = None
    
    def handle_handshake_response(self, message):
        if 'version' in message:
            if self.protocol_version in message:
                self._handshake_recv = True
    
    def datagram_received(self, data: Union[bytes, Text], addr: Tuple[str, int]) -> NoReturn:
        msg = data.decode()
        log.info("Data received: %s", msg)
        if self._handshake_sent and not self._handshake_recv:
            await self.handle_handshake_response(json.loads(msg))
        while self._handshake_recv:
            try:
                message = json.loads(msg)
                if self.file_sender is None:
                    # Expecting Server Info Response
                    await self.get_server_info(message)
                # Expecting Server Blob Response
                await self.get_blob_response(message)
            except IOError:
                raise err.IncompleteResponse(msg)
    
    def error_received(self, exc: Exception):
        if self._handshake_sent and not self._handshake_recv:
            self._handshake_recv = False
    
    def handle_next_blobhash(self, blob_hash: Any[str]):
        log.debug('No current blob, sending the next one: %s', *blob_hash)
        self.blob_hashes_to_send = self.blob_hashes_to_send[1:]
        # send the server the next blob hash + length
        blob = self.blob_manager.get_blob(blob_hash)
        try:
            await self.open_blob_for_reading(blob)
            await self.send_blob_info()
        except ConnectionError as exc:
            log.error('Error reflecting blob %s', *blob_hash)
            raise exc
        
    def resume_writing(self) -> NoReturn:
        # self.streaming = False
        # self.producer = True
        if self.file_sender is not None:
            # send the blob
            log.debug('Sending the blob')
            await self.start_transfer()
        elif self.blob_hashes_to_send:
            # open the next blob to send
            blob_hash = self.blob_hashes_to_send[0]
            await self.handle_next_blobhash(blob_hash)
        # close connection
        log.debug('No more blob hashes, closing connection')
        self._transport.close()
        
    def start_transfer(self) -> NoReturn:
        assert self._transport is not None, \
            "self.read_handle was None when trying to start the transfer"
        # TODO: FileTransferProtocol ?
        # d = self.file_sender.beginFileTransfer(self._transport, self)
        # d.addCallback(lambda _: self._transport.close())
        # return d
    
    def open_blob_for_reading(self, blob: Any[object]) -> NoReturn:
        if blob.get_is_verified():
            # TODO: add_reader()
            # self._transport = blob.open_for_reading()
            if self._transport is not None:
                log.debug('Getting ready to send %s', blob.blob_hash)
                self.next_blob_to_send = blob
        raise ValueError(
            f"Couldn't open that blob for some reason. blob_hash: {blob.blob_hash}")
    
    def send_blob_info(self) -> NoReturn:
        log.debug("Send blob info for %s", self.next_blob_to_send.blob_hash)
        assert self.next_blob_to_send is not None, "need to have a next blob to send at this point"
        # TODO: add_writer()
        # self._transport.write(json.dumps({
        #    'blob_hash': self.next_blob_to_send.blob_hash,
        #    'blob_size': self.next_blob_to_send.length
        # }).encode())
        log.debug('sending blob info')


class BlobReflectorClient(Protocol):
    #  Protocol stuff
    def connectionMade(self):
        self.blob_manager = self.factory.blob_manager
        self.response_buff = b''
        self.outgoing_buff = ''
        self.blob_hashes_to_send = self.factory.blobs
        self.next_blob_to_send = None
        self.blob_read_handle = None
        self.received_handshake_response = False
        self.protocol_version = self.factory.protocol_version
        self.file_sender = None
        self.producer = None
        self.streaming = False
        self.reflected_blobs = []
        d = self.send_handshake()
        d.addErrback(
            lambda err: log.warning("An error occurred immediately: %s", err.getTraceback()))
    
    def dataReceived(self, data):
        log.debug('Received %s', data)
        self.response_buff += data
        try:
            msg = self.parse_response(self.response_buff)
        except err.IncompleteResponse:
            pass
        else:
            self.response_buff = b''
            d = self.handle_response(msg)
            d.addCallback(lambda _: self.send_next_request())
            d.addErrback(self.response_failure_handler)
    
    def connectionLost(self, reason):
        if reason.check(error.ConnectionDone):
            if self.reflected_blobs:
                log.info('Finished sending data via reflector')
            self.factory.finished_deferred.callback(self.reflected_blobs)
        else:
            log.info('Reflector finished: %s', reason)
            self.factory.finished_deferred.callback(reason)
    
    # IConsumer stuff

    def registerProducer(self, producer, streaming):
        self.producer = producer
        self.streaming = streaming
        if self.streaming is False:
            from twisted.internet import reactor
            reactor.callLater(0, self.producer.resumeProducing)

    def unregisterProducer(self):
        self.producer = None

    def write(self, data):
        self.transport.write(data)
        if self.producer is not None and self.streaming is False:
            from twisted.internet import reactor
            reactor.callLater(0, self.producer.resumeProducing)

    def send_handshake(self):
        log.debug('Sending handshake')
        self.write(json.dumps({'version': self.protocol_version}).encode())
        return defer.succeed(None)

    def parse_response(self, buff):
        try:
            return json.loads(buff)
        except ValueError:
            raise err.IncompleteResponse()

    def response_failure_handler(self, err):
        log.warning("An error occurred handling the response: %s", err.getTraceback())

    def handle_response(self, response_dict):
        if self.received_handshake_response is False:
            return self.handle_handshake_response(response_dict)
        else:
            return self.handle_normal_response(response_dict)

    def set_not_uploading(self):
        if self.next_blob_to_send is not None:
            self.read_handle.close()
            self.read_handle = None
            self.next_blob_to_send = None
        self.file_sender = None
        return defer.succeed(None)

    def start_transfer(self):
        assert self.read_handle is not None, \
            "self.read_handle was None when trying to start the transfer"
        d = self.file_sender.beginFileTransfer(self.read_handle, self)
        d.addCallback(lambda _: self.read_handle.close())
        return d

    def handle_handshake_response(self, response_dict):
        if 'version' not in response_dict:
            raise ValueError("Need protocol version number!")
        server_version = int(response_dict['version'])
        if self.protocol_version != server_version:
            raise ValueError(f"I can't handle protocol version {self.protocol_version}!")
        self.received_handshake_response = True
        return defer.succeed(True)

    def handle_normal_response(self, response_dict):
        if self.file_sender is None:  # Expecting Server Info Response
            if 'send_blob' not in response_dict:
                raise ValueError("I don't know whether to send the blob or not!")
            if response_dict['send_blob'] is True:
                self.file_sender = FileSender()
                return defer.succeed(True)
            else:
                return self.set_not_uploading()
        else:  # Expecting Server Blob Response
            if 'received_blob' not in response_dict:
                raise ValueError("I don't know if the blob made it to the intended destination!")
            else:
                if response_dict['received_blob']:
                    self.reflected_blobs.append(self.next_blob_to_send.blob_hash)
                return self.set_not_uploading()

    def open_blob_for_reading(self, blob):
        if blob.get_is_verified():
            read_handle = blob.open_for_reading()
            if read_handle is not None:
                log.debug('Getting ready to send %s', blob.blob_hash)
                self.next_blob_to_send = blob
                self.read_handle = read_handle
                return None
        raise ValueError(
            f"Couldn't open that blob for some reason. blob_hash: {blob.blob_hash}")

    def send_blob_info(self):
        log.debug("Send blob info for %s", self.next_blob_to_send.blob_hash)
        assert self.next_blob_to_send is not None, "need to have a next blob to send at this point"
        log.debug('sending blob info')
        self.write(json.dumps({
            'blob_hash': self.next_blob_to_send.blob_hash,
            'blob_size': self.next_blob_to_send.length
        }).encode())

    def disconnect(self, err):
        self.transport.loseConnection()

    def send_next_request(self):
        if self.file_sender is not None:
            # send the blob
            log.debug('Sending the blob')
            return self.start_transfer()
        elif self.blob_hashes_to_send:
            # open the next blob to send
            blob_hash = self.blob_hashes_to_send[0]
            log.debug('No current blob, sending the next one: %s', blob_hash)
            self.blob_hashes_to_send = self.blob_hashes_to_send[1:]
            d = self.blob_manager.get_blob(blob_hash)
            d.addCallback(self.open_blob_for_reading)
            # send the server the next blob hash + length
            d.addCallbacks(
                lambda _: self.send_blob_info(),
                errback=log.fatal(self.disconnect),
                errbackArgs=("Error reflecting blob %s", blob_hash)
            )
            return d
        else:
            # close connection
            log.debug('No more blob hashes, closing connection')
            self.transport.loseConnection()


class BlobReflectorClientFactory(ClientFactory):
    protocol = BlobReflectorClient

    def __init__(self, blob_manager, blobs):
        self.protocol_version = REFLECTOR_V2
        self.blob_manager = blob_manager
        self.blobs = blobs
        self.p = None
        self.finished_deferred = defer.Deferred()

    def buildProtocol(self, addr):
        p = self.protocol()
        p.factory = self
        self.p = p
        return p

    def startFactory(self):
        log.debug('Starting reflector factory')
        ClientFactory.startFactory(self)

    def startedConnecting(self, connector):
        log.debug('Started connecting')

    def clientConnectionLost(self, connector, reason):
        """If we get disconnected, reconnect to server."""
        log.debug("connection lost: %s", reason.getErrorMessage())

    def clientConnectionFailed(self, connector, reason):
        log.debug("connection failed: %s", reason.getErrorMessage())


def blob_reflector_client_factory(blob_manager, blobs, *addr):
    loop = asyncio.get_running_loop()
    __done = loop.create_future()
    blob_factory = functools.partial(BlobProtocol, blob_manager, blobs)
    blob_coro = loop.create_connection(blob_factory, *addr)
    log.debug('waiting for client to complete')
    try:
        loop.run_until_complete(blob_coro)
        loop.run_until_complete(__done)
    finally:
        log.debug('closing event loop')
        loop.close()
