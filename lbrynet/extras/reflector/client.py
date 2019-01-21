import asyncio
import binascii
import json
import random
import typing

from lbrynet import conf

if typing.TYPE_CHECKING:
    from lbrynet.stream.descriptor import StreamDescriptor
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.extras.reflector.base import ReflectorVersion
    from asyncio.events import AbstractEventLoop
    from asyncio.protocols import Protocol


__all__ = ('ReflectorClient', 'reflect')


class ReflectorClient(Protocol):
    """
    ReflectorClient: Handles the communication between a reflector client and server
    """

    def __init__(self, blobs: typing.Any[typing.List] = None,
                 blob_manager: typing.Any['BlobFileManager'] = None,
                 descriptor: typing.Optional['StreamDescriptor'] = None,
                 version: typing.Any['ReflectorVersion'] = None):

        self.blobs = blobs
        self.blob_manager = blob_manager
        self.descriptor = descriptor
        self.version = version

        self.loop = asyncio.get_running_loop()
        self.transport = None
        self.handshake_received = False

    @staticmethod
    def encode(message: typing.Dict) -> bytes:
        return binascii.hexlify(json.dumps(message).encode()).decode()

    @staticmethod
    def decode(message: typing.AnyStr) -> typing.Dict:
        return json.loads(binascii.unhexlify(message.decode()))

    def connection_made(self, transport: asyncio.Transport) -> bytes:
        self.transport = transport
        return self.encode({'version': self.version})

    def data_received(self, data: bytes) -> typing.List:
        message = self.decode(data)
        if not self.handshake_received:
            if 'version' in message.keys():
                if message.get('version') == self.version:
                    self.handshake_received = True
                else:
                    self.connection_lost(exc=message['version'])
            else:
                self.connection_lost(exc=ConnectionRefusedError())
        elif self.handshake_received:
            if 'needed' in message.keys():
                needed = message.get('needed')
                _need = []
                # TODO: stress test this
                for blob in needed:
                    _blob = self.blob_manager.get_blob(blob_hash=blob)
                    _need.append(_blob)
                return _need
            else:
                return self.blobs

    def connection_lost(self, exc: typing.Optional[Exception]) -> typing.NoReturn:
        self.transport.set_exception(exc)


async def reflect(loop: typing.Any['AbstractEventLoop'] = asyncio.AbstractEventLoop(),
                  protocol: typing.Any['ReflectorClient'] = ReflectorClient,
                  descriptor: typing.Optional['StreamDescriptor'] = None,
                  blob_manager: typing.Any['BlobFileManager'] = BlobFileManager,
                  blobs: typing.Any[typing.List[str]] = None,
                  reflector_server: typing.Optional[str] = None,
                  tcp_port: typing.Optional[int] = 5566,
                  version: typing.Optional['ReflectorVersion'] = 1) -> typing.List:
    """
    Usage:
            reflect [blob_file] [stream_descriptor] [blob_manager] <protocol> <host> <port>
    """
    if reflector_server is None:
        reflector_server = random.choice(conf.get_config()['reflector_servers'])
    if descriptor is None:
        if blob_manager is None:
            raise ValueError("Need blob manager to reflect blobs!")
    if descriptor is not None:
        if blob_manager is None:
            raise ValueError("Need blob manager to reflect sd blobs!")
    if blobs is not None:
        try:
            result = await asyncio.wait_for(loop.create_connection(
                lambda: protocol(version=version, blobs=blobs,
                                 blob_manager=blob_manager,
                                 descriptor=descriptor), reflector_server, tcp_port
            ), loop=loop, timeout=30.0)
            return await result.result()
        except (asyncio.TimeoutError, asyncio.CancelledError, InterruptedError,
                ValueError, ConnectionError, BytesWarning) as exc:
            raise exc.with_traceback(loop)
    else:
        raise ValueError("Nothing to reflect from!")
