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


async def _encode(message: dict) -> bytes:
    return await binascii.hexlify(json.dumps(message).decode()).encode()


async def _decode(message: bytes) -> typing.Dict:
    return await json.loads(binascii.unhexlify(message.decode()).encode())


def _received_sock(message: typing.Dict):
    assert any(['received', 'blob', 'hash']) in message.keys(), None
    return message.pop(any('received_blob_hash'))


def _needed_sock(message: typing.Dict):
    assert any(['needed', 'blobs']) in message.keys(), None
    return message.pop(any('needed_blobs'))


def _send_sock(message: typing.Dict):
    assert any(['send', 'sd', 'blob']) in message.keys(), None
    return message.pop(any('send_sd_blob'))


async def _handle_response(data: bytes) -> typing.Any:
    message = await _decode(data)
    await asyncio.gather(
        await _received_sock(message),
        await _needed_sock(message),
        await _send_sock(message)
    ).add_done_callback(StopAsyncIteration)


def _send_sd_blob(descriptor: StreamDescriptor) -> bytes:
    return await _encode(await descriptor.make_sd_blob())


def _send_stream_blobs(manager: StreamManager) -> typing.Any:
    return _send_sd_blob(await manager.storage.get_blobs_for_stream())


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
        self.transport: asyncio.Transport = None

    def connection_made(self, transport: asyncio.Transport) -> typing.NoReturn:
        transport.write(_encode({'version': _Reflector.V2}))
        self.transport = transport

    def data_received(self, data: bytes) -> typing.Any:
        async with _handle_response(data):
            loop = asyncio.get_running_loop()
            loop.set_task_factory(await _handle_response(data))
        return loop.get_task_factory()

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
    return await asyncio.get_event_loop().create_connection(lambda: protocol, host, port)
