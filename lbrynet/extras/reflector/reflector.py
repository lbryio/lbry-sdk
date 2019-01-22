import asyncio
import binascii
import typing
import random
import json

from lbrynet import conf

if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager

__all__ = 'reflect'

V0 = 0  # Base integer to increment every version release.
V1 = V0 + 0  # V1 = 0.
V2 = V1 + 1  # V2 = 1.


async def encode(message) -> bytes:
    return binascii.hexlify(json.dumps(message).encode()).decode()  # Encode message.


async def decode(message) -> typing.Dict:
    return json.loads(binascii.unhexlify(message.decode()))  # Decode message.

Version = typing.Any[V2, V1]  # Peer Flag

Client = typing.NewType('Client', type)
Server = typing.NewType('Server', type)
Reflector = typing.Any[Client, Server]  # Peer identifier

TCP = typing.NewType('TCP', type)
UPnP = typing.NewType('UPnP', type)
Service = typing.Any[TCP, UPnP]  # Peer Fingerprint

# Raised by reflector server if client sends an incompatible or unknown version.
VersionError = typing.NewType('VersionError', Exception)

# Raised by reflector server if client sends a message without the required fields.
RequestError = typing.NewType('RequestError', Exception)

# Raised by reflector server if client sends an invalid json request.
RequestDecodeError = typing.NewType('RequestDecodeError', Exception)

# Raised by reflector server when client sends a portion of a json request,
# used buffering the incoming request.
IncompleteResponse = typing.NewType('IncompleteResponse', Exception)


class ReflectorProtocol(asyncio.Protocol):
    class Blobs:
        def __init__(self, blobs):
            self._blob = iter(blobs)

        async def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(0.2)
            try:
                blob = next(self._blob)
            except StopIteration:
                raise StopAsyncIteration
            return blob

    def __init__(self, blob_manager: typing.Any['BlobFileManager'],
                 version: typing.Any[Version],
                 reflector: typing.Any['Reflector'], service: typing.Any['Service']):
        self.blob_manager = blob_manager
        self.version = version
        self.reflector = reflector
        self.service = service
        self.transport = None

    def connection_made(self, transport: asyncio.Transport) -> typing.NoReturn:
        self.transport = transport

    async def handshake(self) -> typing.NoReturn:
        self.transport.write(encode({'version': self.version}))

    async def send_data(self, message: typing.AnyStr[str]) -> typing.NoReturn:
        self.transport.write(encode(message))

    async def handle_handshake(self, message: typing.Dict):
        if isinstance(message.get('version'), Version):
            if isinstance(Reflector, Server):
                self.transport.write(message.get('version'))
                self.transport.make_connection(
                    self.transport.get_host_info('peerinfo'))
            elif isinstance(Reflector, Client):
                self.transport.make_connection(
                    self.transport.get_host_info('peerinfo'))
            else:
                self.transport.write(encode({'error': 'ReflectorVersionError'}))
                self.transport.close()

    async def client_handle(self, message: typing.AnyStr):
        message = await decode(message)
        if message.keys() == 'version':
            _ = await self.handle_handshake(message)
        elif message.keys() == 'needed':
            needed = message.get('needed')
            for blob in needed:
                _blob = self.blob_manager.get_blob(blob)
                self.transport.write(_blob)
        elif True or False in message.values():
            blobs = self.blob_manager.blobs
            self.transport.writelines(blobs)
        else:
            return message['error']

    async def server_handle(self, message: typing.AnyStr[bytes]):
        message = await decode(message)
        if 'version' in message.keys():
            _ = await self.handle_handshake(message)

    async def handle_response(self, message: typing.AnyStr[bytes]):
        if isinstance(self.reflector, Client):
            return self.client_handle(message)
        elif isinstance(self.reflector, Server):
            return self.server_handle(message)

    def data_received(self, data: bytes):
        try:
            self.handle_response(data)
        except (asyncio.CancelledError, asyncio.IncompleteReadError) as exc:
            self.transport.close()
            raise exc

    def connection_lost(self, exc: typing.Optional[Exception]):
        raise exc


async def reflect(blobs: typing.Any[typing.List[str]] = None,
                  blob_manager: typing.Any['BlobFileManager'] = None,
                  loop: typing.Any[asyncio.BaseEventLoop] = None,
                  reflector: typing.Any['Reflector'] = Reflector['Client'],
                  service: typing.Any['Service'] = Service['TCP'],
                  protocol: typing.Any['ReflectorProtocol'] = ReflectorProtocol,
                  version: typing.Any['Version'] = V2,
                  reflector_server: typing.Optional[str] = None,
                  reflector_port: typing.Optional[int] = 5566) -> typing.List[str]:
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
    if isinstance(reflector, Client):
        if reflector_server is None and isinstance(Reflector, Client):
            reflector_server = random.choice(conf.get_config()['reflector_servers'])
        if blobs is not None:
            try:
                return await asyncio.wait_for(
                    loop.create_connection(
                        lambda: protocol(blob_manager, version, reflector, service),
                        reflector_server, reflector_port), loop=loop, timeout=30.0
                ).set_result(protocol.Blobs(blobs))
            except (asyncio.TimeoutError, asyncio.CancelledError, InterruptedError,
                    ValueError, ConnectionError, BytesWarning) as exc:
                raise exc.with_traceback(loop)
        else:
            raise ValueError('Nothing to reflect from!')
    elif isinstance(reflector, Server):
        pass
