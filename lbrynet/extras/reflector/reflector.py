import asyncio
import binascii
import typing
import random
import json

from lbrynet import conf

if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.stream.stream_manager import StreamManager
    from asyncio import Protocol

__all__ = ('reflect', 'Reflector', 'ReflectorProtocol')

_V1 = 0
_V2 = 1

_VERSION = typing.Any[_V2, _V1]  # Peer Flag

_SERVERS = conf.get_config()['reflector_servers']
_HOST = random.choice(_SERVERS)


async def encode(message) -> bytes:
    return binascii.hexlify(json.dumps(message).encode()).decode()


async def decode(message) -> typing.Dict:
    return json.loads(binascii.unhexlify(message.decode()))

protocol: 'ReflectorProtocol'
Manager: typing.Any[BlobFileManager, StreamManager]
Reflector: typing.NewType('Reflector', type)

# Raised by reflector server if client sends an incompatible or unknown version.
VersionError: typing.NewType('VersionError', Exception)

# Raised by reflector server if client sends a message without the required fields.
RequestError: typing.NewType('RequestError', Exception)

# Raised by reflector server if client sends an invalid json request.
RequestDecodeError: typing.NewType('RequestDecodeError', Exception)

# Raised by reflector server when client sends a portion of a json request,
# used buffering the incoming request.
IncompleteResponse: typing.NewType('IncompleteResponse', Exception)


class Blobs(typing.AsyncIterator):
    needed = asyncio.Queue()
    send = asyncio.Queue()
    reflected = asyncio.Queue()

    def __init__(self, blobs, manager):
        self.manager = manager
        self.blob = iter(blobs)

    def __await__(self):
        blob = self.needed.get()
        _ = self.manager.get_blob(blob)
        self.send.put(_)
        return self

    async def __anext__(self):
        await asyncio.sleep(0.02)
        try:
            blob = next(self.blob)
        except StopIteration:
            raise StopAsyncIteration
        return blob


class ReflectorProtocol(asyncio.Protocol):
    def __init__(self, version: typing.Any[_VERSION] = _V2):
        self.version = version

    def connection_made(self, transport: asyncio.Transport) -> typing.NoReturn:
        payload = encode({'message': self.version})
        transport.write(payload)

    async def handle_response(self, data: typing.AnyStr[bytes]) -> typing.NoReturn:
        message = await decode(data)
        try:
            if 'version' in message.keys():
                if not message.get('version') == self.version:
                    raise VersionError
                await message.get('version')
            elif 'send_' in message.keys():
                await Blobs.send.put(message.get('send_'.endswith('blob')))
                await Blobs.needed.put(message.get('needed_blobs'))
            elif 'blob_hash' in message.keys():
                # TODO: have server look up blob hash
                pass
            return
        except (IncompleteResponse, RequestDecodeError) as exc:
            raise exc

    def data_received(self, data: bytes) -> typing.Coroutine:
        try:
            return self.handle_response(data)
        except (asyncio.CancelledError, asyncio.IncompleteReadError) as exc:
            raise exc


async def reflect(manager: typing.Any[Manager] = BlobFileManager,
                  loop: typing.Any[asyncio.BaseEventLoop] = asyncio.get_event_loop(),
                  blobs: typing.Optional[typing.Any] = None,
                  host: typing.Optional[_SERVERS, str] = _HOST,
                  port: typing.Optional[int] = 5566) -> typing.Coroutine[typing.Any[typing.List]]:
    """
    Reflect Blobs to a Reflector

    Usage:
            reflect (blob_manager)(blobs)(loop)
                    [--reflector_server=<hostname>][--reflector_port=<port>][--version=<version>]

        Options:
            blob_manager=(<BlobFileManager>...): BlobFileManager
            blobs=(<blobs>...)                 : Blobs[list] to reflect
            loop=(<asyncio.BaseEventLoop>...)  : Event Loop from BlobFileManager
            reflector=(<Reflector>)
            service=(<Service>)
            protocol=(<ReflectorProtocol>)
            --version=<version>                : Reflector protocol version number
                                                 by default use V2
            --reflector_server=<hostname>      : Reflector server hostname
            --reflector_port=<port>            : Reflector port number
                                                 by default choose a server and port from the config

        Returns:
            (list) list of blobs reflected
    """
    async def connect(_loop, _proto, _host, _port):
        return await asyncio.wait_for(
            _loop.create_connection(
                lambda: _proto, _host, _port),
            loop=_loop, timeout=3.0)

    if isinstance(manager, StreamManager):
        server = await connect(loop, protocol, host, port)
        async with server:
            reader, writer = server
            req = await decode(reader.readline())
            if 'blob_hash' in req:
                yield
            elif 'sd_blob_hash' in req:
                yield
            else:
                yield
            await server.serve_forever()

    fut = loop.create_future()
    client = await connect(loop, protocol, host, port)
    async with client:
        blob = Blobs(blobs, manager)
        errors = []
        try:
            reader, writer = client
            writer.write(encode(blob))
            resp = await reader.readline()
            message = await decode(resp)
            if not'received' in message.keys():
                await errors.append(blob.reflected.get())
            await blob.needed.put(message.get(''.startswith('needed')))
        finally:
            _ = []
            while not blob.reflected.empty():
                _.append(blob.reflected.get())
            fut.set_result(_)
            yield fut.result()
