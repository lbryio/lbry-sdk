import asyncio
import binascii
import typing
import random
import json

if typing.TYPE_CHECKING:
    from lbrynet.stream.stream_manager import SQLiteStorage
    from lbrynet.stream.descriptor import StreamDescriptor

__all__ = ('reflect', 'Reflector')


class _Reflector(typing.Type):
    """
    Reflector Module constants
    """
    V2 = 1
    VERSION = typing.Any[V2]
    SERVERS = 'reflector.lbry.io'
    HOST = random.choice(SERVERS)
    PORT = 5566


class ReflectorClientVersionError(Exception):
    """
    Raised by reflector server if client sends an incompatible or unknown version.
    """
    __cause__ = _Reflector.VERSION is not _Reflector.V2
    __context__ = ValueError


class ReflectorRequestError(Exception):
    """
    Raised by reflector server if client sends a message without the required fields.
    """
    __context__ = BlockingIOError


class ReflectorDecodeError(Exception):
    """
    Raised by reflector server if client sends an invalid json request.
    """
    __context__ = json.JSONDecodeError


class IncompleteResponse(Exception):
    """
    Raised by reflector server when client sends a portion of a json request,
    used buffering the incoming request.
    """
    __context__ = BufferError


class Reflector(asyncio.Protocol):
    """
    Reflector is a protocol to re-host lbry blobs and streams
    Client queries and server responses follow, all dicts are encoded as json
    ############# Handshake request and response #############
    Upon connecting, the client sends a version handshake:
    {
        'version': int,
    }
    The server replies with the same version
    {
        'version': int,
    }
    ############# Stream descriptor requests and responses #############
    (if sending blobs directly this is skipped)
    If the client is reflecting a whole stream, they send a stream descriptor request:
    {
        'sd_blob_hash': str,
        'sd_blob_size': int
    }
    The server indicates if it's aware of this stream already by requesting (or not requesting)
    the stream descriptor blob. If the server has a validated copy of the sd blob, it will
    include the needed_blobs field (a list of blob hashes missing from reflector) in the response.
    If the server does not have the sd blob the needed_blobs field will not be included, as the
    server does not know what blobs it is missing - so the client should send all of the blobs
    in the stream.
    {
        'send_sd_blob': bool
        'needed_blobs': list, conditional
    }
    The client may begin the file transfer of the sd blob if send_sd_blob was True.
    If the client sends the blob, after receiving it the server indicates if the
    transfer was successful:
    {
        'received_sd_blob': bool
    }
    If the transfer was not successful (False), the blob is added to the needed_blobs queue
    ############# Blob requests and responses #############
    A client with blobs to reflect (either populated by the client or by the stream descriptor
    response) queries if the server is ready to begin transferring a blob
    {
        'blob_hash': str,
        'blob_size': int
    }
    The server replies, send_blob will be False if the server has a validated copy of the blob:
    {
        'send_blob': bool
    }
    The client may begin the raw blob file transfer if the server replied True.
    If the client sends the blob, the server replies:
    {
        'received_blob': bool
    }
    If the transfer was not successful (False), the blob is re-added to the needed_blobs queue
    Blob requests continue for each of the blobs the client has queued to send, when completed
    the client disconnects.
    """
    __metaclass__ = typing.Protocol

    def __init__(self, storage, descriptor, reflector_server, reflector_port):
        self.storage: SQLiteStorage = storage
        self.descriptor: StreamDescriptor = descriptor
        self.reflector_server: _Reflector.HOST = reflector_server
        self.reflector_port: _Reflector.PORT = reflector_port
        self.transport: asyncio.Transport = None

    @classmethod
    async def _encode(cls, message: dict) -> bytes:
        return await binascii.hexlify(json.dumps(message).decode()).encode()

    @classmethod
    async def _decode(cls, message: bytes) -> typing.Dict:
        return await json.loads(binascii.unhexlify(message.decode()).encode())

    def connection_made(self, transport: asyncio.Transport) -> asyncio.Transport:
        self.transport = transport
        _handshake = self._encode({'version': _Reflector.V2})
        self.transport.write(await _handshake)
        return self.transport

    def data_received(self, data: bytes) -> typing.Any:
        message = await self._decode(data)
        m = message.keys()
        if 'version' in m:
            return
        _ = set  # TODO: handle retrieval of blobs
        if 'received' in m:
            await _.update(message.pop('received_sd_blob'))
        if 'send' in m:
            await _.update(message.pop('send_sd_blob'))
        elif 'need' in m:
            await _.update(message.pop('needed_blobs'))
        return _

    async def _send_sd_blob(self) -> typing.NoReturn:
        return await self._encode(await self.descriptor.make_sd_blob())

    async def _send_stream_blobs(self) -> typing.NoReturn:
        return await self.storage.get_blobs_for_stream(await self._send_sd_blob())


async def reflect(storage: SQLiteStorage, *,
                  descriptor: 'StreamDescriptor',
                  reflector_server: '_Reflector.HOST',
                  reflector_port: '_Reflector.PORT',
                  ) -> typing.Awaitable[typing.List]:
    """
    Reflect Blobs to Reflector
    Usage:
            reflect (SQLiteStorage)
                    [--descriptor=<StreamDescriptor>]
                    [--reflector_host=<host>][--reflector_port=<port>]
        Options:
            --descriptor=<StreamDescriptor>    : StreamDescriptor
            --reflector_host=<host>            : Reflector server IP Address location
            --reflector_port=<port>            : Reflector port number
                                                 by default choose a server and port from the config
        Returns:
            (list) list of blobs reflected
    """
    # TODO: reflect_streams in StreamManager
    # TODO: open connection to client package
    # TODO: open connection to server package
    # TODO: merge
    loop = asyncio.get_running_loop()
    protocol = Reflector(storage, descriptor, reflector_server, reflector_port)
    return await asyncio.wait_for(
        asyncio.create_task(
            loop.create_connection(lambda: protocol)
        ), 10.0).result()
