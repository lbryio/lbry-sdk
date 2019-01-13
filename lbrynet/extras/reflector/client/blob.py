import json
import logging

from asyncio import Protocol
from contextvars import ContextVar, Context

from lbrynet.extras.reflector import REFLECTOR_V2
from lbrynet.extras.reflector import exceptions as err

log = logging.getLogger(__name__)


class BlobProtocol(Protocol):
    protocol_version = REFLECTOR_V2
    payload = ContextVar('payload')
    # TODO: thread pool "Provider"
    blob_manager = ContextVar('blob_manager')
    blob_hashes = ContextVar('blobs')    # blob_hashes_to_send
    next_blob = ContextVar('next_blob')  # next_blob_to_send
    # TODO: create_unix_connection
    file_sender = Context()
    reflected_blobs = ContextVar('reflected_blobs', default=list)
    current_blob = ContextVar('current_blob')
    read_handle = ContextVar('read_handle')
    blob_read_handle = ContextVar('blob_read_handle')
    
    def __init__(self, loop):
        self.__done = loop.create_future()
        self.started = False
        self.data = bytearray()
    
    def wait_closed(self):
        await self.__done
    
    async def get_server_info(self):
        msg = json.dumps(self.data.decode())
        if 'send_blob' not in msg:
            raise BrokenPipeError(f'Expecting: "send_blob" in data; Received: {msg}')
        if msg['send_blob'] is True:
            self.file_sender.set(None)  # FileSender()
    
    async def get_blob_response(self):
        msg = json.dumps(self.data.decode())
        if 'received_blob' not in msg:
            # TODO: move blocking IO to different execution
            raise BrokenPipeError(f'Expecting: "received_blob"; Received: {msg}')
        if msg['received_blob']:
            self.reflected_blobs.append(self.next_blob.blob_hash)
    
    async def data_received(self, data):
        # log.info('Data received: %s', data)
        try:
            await self.data.extend(data)
        except BlockingIOError:
            raise err.IncompleteResponse(data.decode())
        finally:
            while self.started:
                if self.file_sender.get():
                    await self.get_blob_response()
                else:
                    await self.get_server_info()
    
    def handle_next_blob_hash(self):
        # log.debug('No current blob, sending the next one: %s', self.next_blob)
        # self.blob_hashes_to_send = self.blob_hashes_to_send[1:]
        # send the server the next blob hash + length
        await self.current_blob.set(
            self.blob_manager.get_blob(self.next_blob.get()))
        try:
            await self.open_blob_for_reading()
            await self.send_blob_info()
        except ConnectionError as exc:
            # log.error('Error reflecting blob %s', self.next_blob)
            raise exc
        
    def resume_writing(self):
        if self.file_sender.get() is not None:
            # send the blob
            # log.debug('Sending the blob')
            await self.start_transfer()
        elif self.blob_hashes.get():
            # open the next blob to send
            self.next_blob.set(self.blob_hashes.get()[0])
            await self.handle_next_blob_hash()
        # close connection
        # log.debug('No more blob hashes, closing connection')
        self.__done.set_result(True)  # TODO: finish instance
        
    def start_transfer(self):
        assert self.read_handle.get() is not None, \
            'self.read_handle was None when trying to start the transfer'
        # loop = get_running_loop()
        # self.file_sender = loop.run_until_complete(loop.create_unix_connection())  # TODO: listener on server
        # d = self.file_sender.beginFileTransfer(self._transport, self)
        # d.addCallback(lambda _: self._transport.close())
        # return d
    
    def open_blob_for_reading(self):
        if self.current_blob.get().get_is_verified():
            # TODO: add_reader()
            # self._transport = blob.open_for_reading()
            if self.blob_read_handle is not None:
                # log.debug('Getting ready to send %s', blob.blob_hash)
                self.next_blob.set(self.current_blob.get())
        # raise BlockingIOError(f'Error: could not read blob data. blob_hash: {blob.blob_hash}')
    
    def send_blob_info(self):
        # log.debug('Send blob info for %s', self.next_blob_to_send.blob_hash)
        assert self.next_blob.get() is not None, 'need to have a next blob to send at this point'
        # TODO: add_writer()
        # self._transport.write(json.dumps({
        #    'blob_hash': self.next_blob_to_send.blob_hash,
        #    'blob_size': self.next_blob_to_send.length
        # }).encode())
        # log.debug('sending blob info')
