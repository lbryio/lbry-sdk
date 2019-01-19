import asyncio
import binascii
import json
import logging
import random
import typing

from lbrynet import conf

REFLECTOR_V1 = 0
REFLECTOR_V2 = 1

log = logging.getLogger(__name__)


class ReflectorClientVersionError(ConnectionRefusedError):
    """
    Raised by reflector server if client sends an incompatible or unknown version.
    """


class ReflectorRequestError(ConnectionRefusedError):
    """
    Raised by reflector server if client sends a message without the required fields.
    """


class ReflectorRequestDecodeError(ConnectionAbortedError):
    """
    Raised by reflector server if client sends an invalid json request.
    """


class IncompleteResponse(ConnectionResetError):
    """
    Raised by reflector server when client sends a portion of a json request,
    used buffering the incoming request.
    """


class ReflectorClientProtocol(asyncio.Protocol):
    
    def __init__(self, loop: asyncio.BaseEventLoop, descriptor):
        self.loop = loop
        self.transport = None
        self.descriptor = descriptor
        self._response_fut = loop.create_future()
        self.reflector_server = typing.Optional[str]
        self.reflector_port = typing.Optional[int]
        self.received_server_version = asyncio.Lock(loop=loop)
        self.wait_response = asyncio.Lock(loop=loop)
    
    async def encode_payload(self, request: typing.Dict):
        return binascii.hexlify(json.dumps(request).encode().decode())
    
    async def decode_response(self, response: typing.Optional[bytes]) -> typing.Dict:
        return json.loads(binascii.unhexlify(response.decode()))
    
    async def close(self):
        if self._response_fut and not self._response_fut.done():
            self._response_fut.cancel()
        self._response_fut = None
        if self.transport:
            self.transport.close()
        if self.received_server_version.locked():
            self.received_server_version.cancel()
        self.transport = None
    
    def connection_made(self, transport: asyncio.Transport):
        self.transport = transport
        self.reflector_server, self.reflector_port = self.transport.get_extra_info('peername')
    
    async def send_handshake(self, protocol_version: typing.Optional[int]) -> typing.NoReturn:
        _p = {'version': protocol_version}
        proto = await self.encode_payload(_p)
        data = await self.receive_handshake(proto)
        self.loop.call_soon_threadsafe(self.receive_handshake, data)
    
    async def receive_handshake(self, data: typing.Optional[bytes]) -> typing.NoReturn:
        response = await self.decode_response(data)
        if 'version' in response.keys():
            if REFLECTOR_V2 in response.values():
                self.received_server_version.release()
                return await self.received_server_version.set_result(response['version'])
            self._response_fut.set_exception(ReflectorRequestDecodeError)
            return await self.received_server_version.add_done_callback(self.close)
        self._response_fut.set_exception(ReflectorClientVersionError)
        await self.received_server_version.add_done_callback(self.close)
    
    async def reflect_stream_blobs(self):
        blobs = await self.descriptor.blobs
        await self.transport.writeall(blobs)
        self.wait_response.release()
    
    async def reflect_sd_blobs(self, sd_blobs: typing.List, blob_manager) -> typing.List:
        for blob in sd_blobs:
            _p = {'sd_blob': blob}
            payload = await self.encode_payload(_p)
            self.transport.write(payload)
            self.transport.write_eof()
            await blob_manager.completed_blob_hashes.add(blob)
        blob_hashes = blob_manager.completed_blob_hashes.copy()
        return blob_hashes
    
    async def handle_data_received(self, message: typing.Optional[bytes]) -> typing.NoReturn:
        msg = await self.decode_response(message)
        if 'version' in msg.keys():
            if msg['version'] == REFLECTOR_V2:
                return self.received_server_version.release()
            self.received_server_version.cancel()
            return self.connection_lost(exc=ConnectionRefusedError())
        elif 'needed' in msg.keys():
            if False in msg.values():
                return self.loop.call_soon_threadsafe(self.reflect_stream_blobs)
            # print(msg['needed_blobs'])
        elif True in msg.values():
            self.wait_response.release()
        else:
            self.wait_response.cancel()
        self.connection_lost(exc=ConnectionError())
    
    def data_received(self, data: typing.Optional[bytes]):
        try:
            return self.handle_data_received(data)
        except (asyncio.CancelledError, asyncio.TimeoutError) as err:
            if self._response_fut and not self._response_fut.done():
                self._response_fut.set_exception(err)
    
    def connection_lost(self, exc: typing.Optional[Exception]):
        self.transport = None
        self.loop.create_task(self.close())


async def reflect_stream(loop: asyncio.BaseEventLoop, descriptor,
                         blob_manager, protocol: 'ReflectorClientProtocol',
                         reflector_server: str, tcp_port: int) -> typing.List:
    """
    returns all completed blob_hashes in stream.
    :param loop:
    :param descriptor:
    :param blob_manager:
    :param protocol:
    :param reflector_server:
    :param tcp_port:
    :return:
    """
    
    if not reflector_server:
        reflector_server = random.choice(conf.settings['reflector_servers'])
    if not tcp_port:
        tcp_port = 5566
    try:
        await asyncio.wait_for(loop.create_connection(lambda: protocol, reflector_server, tcp_port),
                               loop=loop, timeout=30.0)
        sd_blobs = descriptor.blobs.copy()
        return await protocol.reflect_sd_blobs(sd_blobs, blob_manager)
    except (asyncio.TimeoutError, asyncio.CancelledError, ReflectorRequestDecodeError,
            ReflectorClientVersionError, ReflectorRequestError, IncompleteResponse):
        return [None]
