import json
import logging

from asyncio import protocols, transports
from typing import Any, Iterable, NoReturn, Optional, Union, Text, Tuple
from urllib.parse import quote_from_bytes

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
        self.current_blob = None
    
    def send_handshake(self) -> NoReturn:
        log.debug('Sending handshake')
        payload = json.dumps({'version': self.protocol_version})
        peer = self._transport.get_extra_info('peerhost')
        self._transport.sendto(data=payload.encode(), addr=peer)
        self._handshake_sent = True

    def connection_made(self, transport: transports.DatagramTransport) -> NoReturn:
        log.info('Connection established with %s', transport.get_extra_info('peerhost'))
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
                log.error('Error during handshake: %s', exc)
            elif exc is err.ReflectorRequestDecodeError:
                log.error('Error when decoding payload: %s', quote_from_bytes(
                    json.dumps({'version': self.protocol_version}).encode()))
            elif exc is err.ReflectorClientVersionError:
                log.error('Invalid reflector protocol version: %i', self.protocol_version)
            else:
                log.error('An error occurred immediately: %s', exc)
            raise exc
        if exc is None:
            if self.reflected_blobs:
                log.info('Finished sending data via reflector')
        log.info('Reflector finished: %s', exc)
        raise exc

    async def get_server_info(self, message: Union[bytes, dict]) -> NoReturn:
        if 'send_blob' not in message:
            raise RecursionError(f'Expecting: "send_blob" in data; Received: {message}')
        if message['send_blob'] is True:
            # TODO: FileSender Factory/Protocol?
            self.file_sender = None  # FileSender()
        else:
            if self.next_blob_to_send is not None:
                self.next_blob_to_send = None
            self.file_sender = None
    
    async def get_blob_response(self, message: Union[bytes, dict]) -> NoReturn:
        if 'received_blob' not in message:
            raise RecursionError(f'Expecting: "received_blob"; Received: {message}')
        else:
            if message['received_blob']:
                self.reflected_blobs.append(self.next_blob_to_send.blob_hash)
            if self.next_blob_to_send is not None:
                self.next_blob_to_send = None
            self.file_sender = None
    
    def handle_handshake_response(self, message: Union[bytes, dict]) -> NoReturn:
        if 'version' in message:
            if self.protocol_version in message:
                self._handshake_recv = True
    
    def datagram_received(self, data: Union[bytes, Text], addr: Tuple[str, int]) -> NoReturn:
        msg = data.decode()
        log.info('Data received: %s', msg)
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
            except BlockingIOError:
                raise err.IncompleteResponse(msg)
    
    def error_received(self, exc: Exception) -> NoReturn:
        if self._handshake_sent and not self._handshake_recv:
            self._handshake_recv = False
    
    def handle_next_blobhash(self, blob_hash: Any[str]) -> NoReturn:
        log.debug('No current blob, sending the next one: %s', blob_hash)
        self.blob_hashes_to_send = self.blob_hashes_to_send[1:]
        # send the server the next blob hash + length
        blob = self.blob_manager.get_blob(blob_hash)
        try:
            await self.open_blob_for_reading(blob)
            await self.send_blob_info()
        except ConnectionError as exc:
            log.error('Error reflecting blob %s', blob_hash)
            raise exc
        
    def resume_writing(self) -> NoReturn:
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
            'self.read_handle was None when trying to start the transfer'
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
        raise BlockingIOError(f'Error: could not read blob data. blob_hash: {blob.blob_hash}')
    
    def send_blob_info(self) -> NoReturn:
        log.debug('Send blob info for %s', self.next_blob_to_send.blob_hash)
        assert self.next_blob_to_send is not None, 'need to have a next blob to send at this point'
        # TODO: add_writer()
        # self._transport.write(json.dumps({
        #    'blob_hash': self.next_blob_to_send.blob_hash,
        #    'blob_size': self.next_blob_to_send.length
        # }).encode())
        log.debug('sending blob info')
