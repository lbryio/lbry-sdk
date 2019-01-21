import asyncio
import binascii
import json
import random
import typing

from lbrynet import conf

if typing.TYPE_CHECKING:
    from lbrynet.stream.descriptor import StreamDescriptor
    from lbrynet.blob.blob_file import BlobFile
    from lbrynet.blob.blob_manager import BlobFileManager
    from asyncio.events import AbstractEventLoop
    from asyncio.streams import StreamReader
    from asyncio.futures import Future

REFLECTOR_V0 = 0
REFLECTOR_V1 = REFLECTOR_V0 + 0
REFLECTOR_V2 = REFLECTOR_V1 + 1


class ReflectorClientVersionError(Exception):
    """
    Raised by reflector server if client sends an incompatible or unknown version.
    """


class ReflectorRequestError(Exception):
    """
    Raised by reflector server if client sends a message without the required fields.
    """


class ReflectorRequestDecodeError(Exception):
    """
    Raised by reflector server if client sends an invalid json request.
    """


class IncompleteResponse(Exception):
    """
    Raised by reflector server when client sends a portion of a json request,
    used buffering the incoming request.
    """


class ReflectorClient(asyncio.StreamReaderProtocol):
    """
    ReflectorClient: Handles the communication between a reflector client and server
    """

    def __init__(self, stream_reader: typing.Any['StreamReader'] = asyncio.streams.StreamReader(),
                 loop: typing.Any['AbstractEventLoop'] = asyncio.events.AbstractEventLoop(),
                 blobs: typing.Any[typing.List] = None,
                 version: typing.Any[REFLECTOR_V2, REFLECTOR_V1] = None):
        self.loop = loop
        self.version = version
        self.transport = None
        self.handshake_received = asyncio.BoundedSemaphore()
        _ = await self.handshake_received.acquire()
        self.blobs = blobs
        for blob in self.blobs:
            _blob = self.encode(blob)
            self.loop.create_task(self.write_blob(_blob))
        super().__init__(stream_reader=stream_reader, client_connected_cb=self.connection_made)

    @staticmethod
    def encode(message: typing.Dict) -> bytes:
        return binascii.hexlify(json.dumps(message).encode()).decode()

    @staticmethod
    def decode(message: typing.AnyStr) -> typing.Dict:
        return json.loads(binascii.unhexlify(message.decode()))

    def connection_made(self, transport: asyncio.StreamReader) -> typing.NoReturn:
        self.transport = transport
        payload = self.encode({'version': self.version})
        self.transport.feed_data(data=payload)
        self.transport.feed_eof()
        response = await self.transport.readline()
        resp = self.decode(response)
        if resp.get('version') == REFLECTOR_V2:
            self.version = resp.get('version')
            self.handshake_received.release()
        else:
            exc = ReflectorClientVersionError()
            self.transport.set_exception(exc)

    async def write_blob(self, blob) -> typing.NoReturn:
        self.transport.feed_data(blob)
        self.transport.feed_eof()
        return await self.transport.readline()

    async def reflect_blobs(self) -> Future:
        return await self.loop.get_task_factory()

    def connection_lost(self, exc: typing.Optional[Exception]) -> typing.NoReturn:
        self.transport.set_exception(exc)


async def reflect(loop: typing.Any['AbstractEventLoop'] = asyncio.AbstractEventLoop(),
                  protocol: typing.Any['ReflectorClient'] = ReflectorClient,
                  descriptor: typing.Optional['StreamDescriptor'] = None,
                  blob_file: typing.Optional['BlobFile'] = None,
                  blob_manager: typing.Optional['BlobFileManager'] = None,
                  blobs: typing.Optional[typing.List] = None,
                  reflector_server: typing.Optional[str] = None,
                  tcp_port: typing.Optional[int] = 5566,
                  version: typing.Optional[int] = REFLECTOR_V2) -> typing.List:
    """
    Usage:
            reflect [blob_file] [stream_descriptor] [blob_manager] <protocol> <host> <port>
    """
    if reflector_server is None:
        reflector_server = random.choice(conf.get_config()['reflector_servers'])
    if descriptor is not None:
        blobs = descriptor.blobs.copy()
    elif blob_file is not None:
        blobs = blob_file.get_is_verified()
    elif blob_manager is not None:
        blobs = blob_manager.get_all_verified_blobs()
    if blobs is not None:
        try:
            result = await asyncio.wait_for(loop.create_connection(
                lambda: protocol(version=version, blobs=blobs), reflector_server, tcp_port
            ), loop=loop, timeout=30.0).set_result(protocol.reflect_blobs)
            return await result.result()
        except (asyncio.TimeoutError, asyncio.CancelledError, ReflectorRequestDecodeError,
                ReflectorClientVersionError, ReflectorRequestError, IncompleteResponse) as exc:
            raise exc.with_traceback(loop)
    else:
        raise ValueError("Nothing to reflect from!")
