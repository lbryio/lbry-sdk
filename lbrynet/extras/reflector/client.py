import asyncio
import binascii
import json
import random
import typing

from lbrynet import conf

if typing.TYPE_CHECKING:
    from lbrynet.stream.managed_stream import ManagedStream
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.extras.reflector.base import ReflectorVersion


__all__ = ('ReflectorClient', 'reflect')


class ReflectorClient(asyncio.Protocol):
    """
    ReflectorClient: Handles the communication between a reflector client and server
    """
    def __init__(self, blobs: typing.List[str] = None,
                 blob_manager: typing.Any['BlobFileManager'] = None,
                 loop: typing.Any[asyncio.AbstractEventLoop] = None,
                 version: typing.Any['ReflectorVersion'] = None):
        # Class variables
        self.blobs = blobs                    # Initial blobs to reflect.
        self.blob_manager = blob_manager      # BlobFileManager for getting blobs.
        self.version = version                # Needed to Handshake
        # Protocol variables
        self.loop = loop
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

    def connection_made(self, transport: asyncio.Transport) -> typing.NoReturn:
        """
        Return handshake.
        """
        self.transport = transport
        self.transport.write(self.encode({'version': self.version}))  # Handshake

    def data_received(self, data: bytes) -> typing.List:
        """
        Handle response from server.
        """
        message = self.decode(data)
        if not self.handshake_received:
            if message.get('version') == self.version:
                # Handshake received. Send blobs.
                self.transport.writelines(self.blobs)
            else:
                # ReflectorClientVersionError
                self.connection_lost(message['version'])
        elif self.handshake_received:
            if 'needed' in message.keys():
                needed = message.get('needed')
                for blob in needed:
                    _blob = self.blob_manager.get_blob(blob_hash=blob)
                    # reflect needed blob
                    self.transport.write(_blob)
            elif True or False in message.values():
                # reflect all blobs in stream.
                self.transport.writelines(self.blob_manager.blobs)
            else:
                # ReflectorRequestError/ReflectorRequestDecodeError
                return message['error']

    def connection_lost(self, exc: typing.Optional[Exception]) -> typing.NoReturn:
        # Close()
        self.transport.set_exception(exc)


async def reflect(blob_manager: typing.Any['BlobFileManager'],                # Required
                  blobs: typing.Any[typing.List[str]],                        # Required
                  loop: typing.Any['asyncio.AbstractEventLoop'],              # BlobFileManager.loop()
                  protocol: typing.Any['ReflectorClient'] = ReflectorClient,  # Client/Version
                  reflector_server: typing.Optional[str] = None,              # reflector hostname
                  reflector_port: typing.Optional[int] = 5566,                # reflector port
                  version: typing.Optional['ReflectorVersion'] = 1            # reflector protocol version
                  ) -> typing.List[str]:
    """
    Reflect Blobs to a Reflector server
    
    Usage:
            reflect [blob_manager][blobs][loop]
                    [--reflector_server=<hostname>][--reflector_port=<port>] [--version=<version>]
  
        Options:
            --blob_manager=<blob_manager>     : BlobFileManager object to retrieve needed hashes from.
            --blobs=<blobs>                   : Blobs to reflect
            --loop=<loop>                     : Event Loop
            --reflector_server=<hostname>     : Reflector server
            --reflector_port=<port>           : Port number
                                                by default choose a server and port from the config
            --version=<version>               : Reflector protocol version number
                                                by default use V2
        Returns:
            (list) list of blobs reflected
    """
    if reflector_server is None:
        reflector_server = random.choice(conf.get_config()['reflector_servers'])
    if blob_manager is None:
        raise ValueError("Need blob manager to reflect blobs!")
    if blobs is not None:
        try:
            return await asyncio.wait_for(loop.create_connection(
                lambda: protocol(version=version, blobs=blobs,
                                 blob_manager=blob_manager), reflector_server, reflector_port
            ), loop=loop, timeout=30.0).result()
        except (asyncio.TimeoutError, asyncio.CancelledError, InterruptedError,
                ValueError, ConnectionError, BytesWarning) as exc:
            raise exc.with_traceback(loop)
    else:
        raise ValueError("Nothing to reflect from!")
