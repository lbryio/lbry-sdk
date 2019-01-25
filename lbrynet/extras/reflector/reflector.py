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
    __doc__ = 'Reflector Module constants'
    V2 = 1
    VERSION = typing.Any[V2]
    SERVERS = 'reflector.lbry.io'  # conf.get_config()['reflector_servers']
    HOST = random.choice(SERVERS)
    PORT = 5566


class ReflectorClientVersionError(Exception):
    __doc__ = 'Raised by reflector server if client sends an incompatible or unknown version.'
    __cause__ = _Reflector.VERSION is not _Reflector.V2
    __context__ = ValueError


class ReflectorRequestError(Exception):
    __doc__ = 'Raised by reflector server if client sends a message without the required fields.'
    __context__ = BlockingIOError


class ReflectorDecodeError(Exception):
    __doc__ = 'Raised by reflector server if client sends an invalid json request.'
    __context__ = json.JSONDecodeError


class IncompleteResponse(Exception):
    __doc__ = 'Raised by reflector server when client sends a portion of a json request, ' \
              'used buffering the incoming request.'
    __context__ = BufferError


class Reflector(asyncio.Protocol):
    __doc__ = 'Reflector Protocol: re-uploads a stream to a reflector server'
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

    def connection_made(self, transport: asyncio.Transport):
        self.transport = transport
        # print(f'connected to {writer.get_extra_info("peerhost")}')
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
        return await self.storage.get_blobs_for_stream(self._send_sd_blob())


async def reflect(storage: SQLiteStorage, *,
                  descriptor: StreamDescriptor = None,
                  reflector_server: typing.AnyStr = 'reflector.lbry.io',
                  reflector_port: int = 5566) -> typing.Any[typing.List]:
    """
    Reflect Blobs to Reflector
    Usage:
            reflect (SQLiteStorage)
                    [--descriptor=<StreamDescriptor>]
                    [--reflector_host=<host>][--reflector_port=<port>]
        Options:
            --descriptor=<StreamDescriptor>     : StreamDescriptor
            --reflector_host=<host>            : Reflector server hostname
            --reflector_port=<port>            : Reflector port number
                                                 by default choose a server and port from the config
        Returns:
            (list) list of blobs reflected
    """
    loop = asyncio.get_running_loop()
    protocol = Reflector(storage, descriptor, reflector_server, reflector_port)
    return await loop.create_connection(lambda: protocol)
