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


# TODO: get rid of these or put in error/components

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
        self.handshake_received = False
        self._reflected = set

    def connection_made(self, transport: asyncio.Transport) -> typing.NoReturn:
        transport.write(self._handshake)
        self.transport = transport

    def send_stream_blobs(self) -> typing.List:
        try:
            blobs = yield asyncio.as_completed(self.stream_manager.storage.get_blobs_for_stream())
            async for blob in blobs:
                self.descriptor = blob
                if asyncio.wait_for(asyncio.create_task(self.send_sd_blob()), 0.1).cancelled():
                    break
                continue
        except StopAsyncIteration:
            return self._reflected
        return blobs

    def send_sd_blob(self) -> typing.Any[typing.List]:
        try:
            blob = yield asyncio.create_task(self.descriptor.make_sd_blob()).add_done_callback(StopAsyncIteration)
            async with blob:
                self.transport.write(_encode(blob.result))
        except StopAsyncIteration:
            return self._reflected
        return blob

    def handle_response(self, data: bytes) -> typing.Any[typing.NoReturn, None, Exception]:
        assert self.handshake_received, ConnectionResetError
        keys, _ = message = yield _decode(data)
        while ('received', 'blob', 'hash') in keys:
            assert message.get('received_blob_hash'), NotImplemented
            return self._reflected.update(message.pop(any(['received'])))
        while ('needed', 'blobs') in keys:
            assert message.get('needed_blobs'), NotImplemented
            _blob = yield iter(message.pop(any(['needed_blobs'])))
            assert self.stream_manager.storage.stream_exists(_blob), ValueError  # use error from tld
            return self.stream.should_single_announce_blobs(_blob)
            # TODO: make set_streams_to_re_reflect
        while('send', 'sd', 'blob') in keys:
            assert message.get('send_sd_blob'), NotImplemented
            # should be one, but im not opposed to figuring out how to do this in one line.
            blob = yield iter(message.pop(any(['send_sd_blob'])))
            self.descriptor = yield self.stream.get_sd_blob_hash_for_stream(*blob)
            return self.send_sd_blob()

    def data_received(self, data: bytes) -> typing.Any:
        try:
            while self.handshake_received:
                _ = repr(self.handle_response(data))
                yield zip(*_, *self.stream_manager.storage.get_streams_to_re_reflect)
                break
            assert any('version') in _decode(data), ReflectorClientVersionError
            self.handshake_received = True
        except (asyncio.CancelledError, asyncio.IncompleteReadError) as exc:
            raise exc
        finally:
            loop = asyncio.get_event_loop()
            async with loop:
                _next = self.stream_manager.storage.get_streams_to_re_reflect()
                assert (self.stream_manager.storage.stream_exists, *_next), None
                yield loop.call_soon_threadsafe(self.handle_response, *_next)

    def connection_lost(self, exc: typing.Optional[Exception]):
        return self._reflected


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
