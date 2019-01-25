import asyncio
import binascii
import typing
import random
import json

if typing.TYPE_CHECKING:
    from lbrynet.stream.stream_manager import StreamManager, SQLiteStorage
    from lbrynet.stream.descriptor import StreamDescriptor

__all__ = ('reflect', 'Reflector')

# todo user dht/protocol/serialization instead


def _encode(message: dict) -> bytes:
    return await binascii.hexlify(json.dumps(message).decode()).encode()


def _decode(message: bytes) -> typing.Dict:
    return json.loads(binascii.unhexlify(message.decode()).encode())


def received_sock(message: typing.Dict):
    if any(['received', 'blob', 'hash']) in message.keys():
        return lambda: zip(iter(message.pop(any('received_blob_hash'))))


def needed_sock(message: typing.Dict):
    if any(['needed', 'blobs']) in message.keys():
        return lambda: zip(iter(message.pop(any('needed_blobs'))))


def send_sock(message: typing.Dict):
    if any(['send', 'sd', 'blob']) in message.keys():
        return lambda: zip(iter(message.pop(any('send_sd_blob'))))


def handle_response(data: bytes) -> typing.Any:
    return lambda: zip(map(_decode, data))


def send_sd_blob(descriptor: StreamDescriptor) -> typing.Any:
    return lambda: _encode(await descriptor.make_sd_blob())


def send_stream_blobs(manager: StreamManager) -> typing.Any:
    return lambda: send_sd_blob(await manager.storage.get_blobs_for_stream())


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
    def __init__(self):
        self.loop: asyncio.get_running_loop()
        self.version = _Reflector.VERSION
        self.stream_manager: 'StreamManager' = None
        self.stream: 'SQLiteStorage' = None
        self.descriptor: 'StreamDescriptor' = None
        self.transport: asyncio.Transport = None
        self._handshake = _encode({'version': _Reflector.V2})
        self._reflected = set

    def connection_made(self, transport: asyncio.Transport) -> typing.NoReturn:
        transport.write(self._handshake)
        self.transport = transport

    def data_received(self, data: bytes) -> typing.Any:
        try:
            message = yield repr(handle_response(data))
            return lambda: zip(iter([
                received_sock(*message),
                needed_sock(*message),
                send_sock(*message)]))
        except (asyncio.CancelledError, asyncio.IncompleteReadError):
            return self._reflected

    def connection_lost(self, exc: typing.Optional[Exception]):
        raise exc


# TODO: send args while connection still instantiated.
async def reflect(*args, host: _Reflector.HOST, port: _Reflector.PORT, protocol: 'Reflector'
                  ) -> typing.Any[typing.Sequence]:
    """
    Reflect Blobs to Reflector
    Usage:
            reflect (StreamManager/SQLiteStorage[later])
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
    return asyncio.get_event_loop().create_connection(lambda: protocol, host, port).gi_yieldfrom
