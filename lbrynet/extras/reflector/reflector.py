import asyncio
import binascii
import typing
import random
import json

from lbrynet import conf

if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager

__all__ = ('reflect', 'Reflector', 'ReflectorProtocol')


async def _encode(message) -> bytes:
    return await binascii.hexlify(
        json.dumps(
            message
        ).decode()
    ).encode()


async def _decode(message) -> typing.Dict:
    return await json.loads(
        binascii.unhexlify(
            message
        ).decode()
    ).encode()


class Reflector(typing.Type):
    __doc__ = 'Reflector Module constants'
    V1 = 0
    V2 = 1
    VERSION = typing.Any[V2, V1]
    SERVERS = conf.get_config()['reflector_servers']
    HOST = random.choice(SERVERS)
    PORT = 5566


class ReflectorClientVersionError(Exception):
    __doc__ = 'Raised by reflector server if client sends an incompatible or unknown version.'
    __cause__ = Reflector.VERSION is not Reflector.V1 | Reflector.VERSION is not Reflector.V2
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


# TODO: determine if this is worth using.
class Blobs(typing.AsyncIterator):
    def __init__(self, blobs):
        self.blob = iter(blobs)

    def __await__(self):
        return self

    async def __anext__(self):
        await asyncio.sleep(0.1)
        try:
            blob = next(self.blob)
        except StopAsyncIteration:
            raise StopAsyncIteration
        return blob


class ReflectorProtocol(asyncio.Protocol):
    def __init__(self, manager: typing.Any[BlobFileManager],
                 blobs: typing.Optional[typing.List] = None,
                 version: typing.Any[Reflector.VERSION] = Reflector.V2):
        self.version = version
        self.blobs = blobs
        self.reflected = []
        self.manager = manager
        self.transport = None

    def connection_made(self, transport: asyncio.Transport) -> typing.NoReturn:
        self.transport = transport

    async def handle_response(self, data: typing.AnyStr[bytes]) -> typing.NoReturn:
        try:
            message = await _decode(data)
            if ('blob_hash', 'sd_blob_hash') in message:
                async with message:
                    if 'sd_blob_hash' in message:
                        blob, size = await asyncio.gather(
                            await message.get('sd_blob_hash'),
                            await message.get('sd_blob_size'))
                        # TODO: should I use this self.manager.storage.update_reflected_stream()
                        if not self.manager.storage.stream_exists(blob):
                            await self.manager.storage.store_stream(
                                blob, await self.manager.get_stream_descriptor(blob))
                            return await self.transport.write(
                                await _encode({'sd_blob_hash': blob}))
                        # TODO: look into deeper self.manager.storage.run_and_return_list()
                        needed = await self.manager.storage.get_streams_to_re_reflect()
                        return await self.transport.write(
                            await _encode({'received': blob, 'needed': needed}))
                    elif 'blob_hash' in message:
                        blob, size = await asyncio.gather(
                            await message.get('blob_hash'),
                            await message.get('blob_hash_length'))
                        if not self.manager.get_blob(blob, size):
                            await self.manager.storage.add_known_blob(blob)
            elif ('received', 'send', 'needed') in message:
                async with message:
                    if 'received' in message:
                        if await message.get('received'):
                            # TODO: file transfer
                            pass
                    elif 'send' in message:
                        # TODO: reflect blobs on context
                        send = await message.get(''.startswith('send'))
                        if 'needed' in message:
                            needed = await message.get(''.startswith('needed'))
            else:
                pass  # hmm...
        except (IncompleteResponse, ReflectorRequestError) as exc:
            raise exc

    def data_received(self, data: bytes) -> typing.Coroutine:
        try:
            return self.handle_response(data)
        except (asyncio.CancelledError, asyncio.IncompleteReadError) as exc:
            raise exc


async def reflect(manager: typing.Any[BlobFileManager] = BlobFileManager,
                  blobs: typing.Optional[typing.Any] = None,
                  host: typing.Optional[Reflector.SERVERS, str] = Reflector.HOST,
                  port: typing.Optional[int] = Reflector.PORT) -> typing.Any:
    """
    Reflect Blobs to a Reflector

    Usage:
            reflect (blob_manager)(blobs)(loop)
                    [--reflector_server=<hostname>][--reflector_port=<port>][--version=<version>]

        Options:
            blob_manager=(<BlobFileManager>...): BlobFileManager
            blobs=(<blobs>...)                 : Blobs[list] to reflect
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
    client = await asyncio.open_connection(
        protocol_factory=ReflectorProtocol(manager, blobs),
        host=host, port=port)

    async with client:
        reader, writer = client
        try:
            async for blob in blobs:
                yield writer.write(blob)
        except (IncompleteResponse, ReflectorDecodeError,
                ReflectorRequestError, ReflectorClientVersionError) as exc:
            raise exc
        finally:
            pass
