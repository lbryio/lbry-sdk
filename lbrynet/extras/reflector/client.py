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


__all__ = ('ReflectorClient', 'reflect')


class ReflectorClient(asyncio.Protocol):
    """
    ReflectorClient: Handles the communication between a reflector client and server
    """
    def __init__(self, blobs: typing.Any[typing.List] = None,
                 blob_manager: typing.Any['BlobFileManager'] = None,
                 version: typing.Any['ReflectorVersion'] = None,
                 descriptor: typing.Optional['StreamDescriptor'] = None):
        # Class variables
        self.blobs = blobs
        self.blob_manager = blob_manager
        self.descriptor = descriptor
        self.version = version
        # Protocol variables
        self.loop = asyncio.get_running_loop()
        self.transport = None
        self.handshake_received = False

    @staticmethod
    def encode(message: typing.Dict) -> bytes:
        """
        Return a encoded payload from dict.
        """
        return binascii.hexlify(json.dumps(message).encode()).decode()

    @staticmethod
    def decode(message: typing.AnyStr) -> typing.Dict:
        """
        Return a dict from encoded() message.
        """
        return json.loads(binascii.unhexlify(message.decode()))

    def connection_made(self, transport: asyncio.Transport) -> bytes:
        """
        Return handshake.
        """
        self.transport = transport
        return self.encode({'version': self.version})

    def data_received(self, data: bytes) -> typing.List:
        """
        Handle response from server.
        """
        message = self.decode(data)
        if not self.handshake_received:
            if message.get('version') == self.version:
                self.handshake_received = True
            else:
                self.connection_lost(message['version'])
        elif self.handshake_received:
            if 'needed' in message.keys():
                needed = message.get('needed')
                _need = []
                # TODO: stress test this
                for blob in needed:
                    _blob = self.blob_manager.get_blob(blob_hash=blob)
                    _need.append(_blob)
                return _need
            elif True or False in message.values():
                return self.blobs
            else:
                return message['error']

    def connection_lost(self, exc: typing.Optional[Exception]) -> typing.NoReturn:
        self.transport.set_exception(exc)


async def reflect(loop: typing.Any[asyncio.AbstractEventLoop] = asyncio.AbstractEventLoop(),
                  protocol: typing.Any['ReflectorClient'] = ReflectorClient,
                  blob_manager: typing.Any['BlobFileManager'] = BlobFileManager,
                  blobs: typing.Any[typing.List[str]] = None,
                  descriptor: typing.Optional['StreamDescriptor'] = None,
                  reflector_server: typing.Optional[str] = None,
                  reflector_port: typing.Optional[int] = 5566,
                  version: typing.Optional['ReflectorVersion'] = 1) -> typing.List[str]:
    """
    Reflect Blobs to a Reflector server
    
    Usage:
            reflect [blob_manager][stream_descriptor]
                    [--blobs=<blobs>] [--reflector_server=<hostname>]
                    [--reflector_port=<port>] [--version=<version>]
  
        Options:
            --blob_manager=<blob_manager> : BlobFileManager object to retrieve needed hashes from.
            --descriptor=<descriptor>     : StreamDescriptor object to retrieve needed sd_hashes from.
            --blobs=<blobs>               : Blobs to reflect
            --reflector_server=<hostname> : Reflector server
            --reflector_port=<port>       : Port number
                                            by default choose a server and port from the config
            --version=<version>           : Reflector protocol version number
                                            by default use V2
        Returns:
            (list) list of blobs reflected
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
                                 descriptor=descriptor), reflector_server, reflector_port
            ), loop=loop, timeout=30.0)
            return await result.result()
        except (asyncio.TimeoutError, asyncio.CancelledError, InterruptedError,
                ValueError, ConnectionError, BytesWarning) as exc:
            raise exc.with_traceback(loop)
    else:
        raise ValueError("Nothing to reflect from!")
