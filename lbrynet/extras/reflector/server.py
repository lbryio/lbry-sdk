import asyncio
import binascii
import json
import typing

if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.extras.reflector.base import ReflectorVersion


class ReflectorClientVersionError(Exception):
    """
    Raised by reflector server if client sends an incompatible or unknown version.
    """


class ReflectorRequestError(Exception):
    """
    Raised by reflector server if client sends a message without the required fields.
    """


class ReflectorRequestDecodeError(Exception):
    """
    Raised by reflector server if client sends an invalid json request.
    """


class IncompleteResponse(Exception):
    """
    Raised by reflector server when client sends a portion of a json request,
    used buffering the incoming request.
    """


class ReflectorServer(asyncio.Protocol):
    def __init__(self, blob_manager: typing.Any['BlobFileManager'] = BlobFileManager):
        self.blob_manager = blob_manager
        
        self.handshake = False
        self.transport = None
        self.version = typing.Any[ReflectorVersion]

    @staticmethod
    def encode(message: typing.Dict) -> bytes:
        return binascii.hexlify(json.dumps(message).encode()).decode()

    @staticmethod
    def decode(message: typing.AnyStr) -> typing.Dict:
        return json.loads(binascii.unhexlify(message.decode()))
    
    def connection_made(self, transport: asyncio.Transport):
        self.transport = transport
        return self.encode({'version': self.version})
    
    def handle_blob(self, blob: typing.Dict):
        if 'sd_blob' in blob.keys():
            _blob = await self.blob_manager.get_stream_descriptor(sd_hash=blob.get('sd_blob_hash'))
        elif 'blob' in blob.keys():
            _blob = await self.blob_manager.get_blob(blob.get('blob_hash'), blob.get('blob_hash_size'))
        # manager = await self.blob_manager.get_blob(blob[])
    
    def data_received(self, data: bytes):
        message = self.decode(data)
        if not self.handshake:
            if 'version' not in message.keys():
                return {'error': ReflectorRequestError}
            else:
                if isinstance(ReflectorVersion, message.get('version')):
                    return self.encode({'version': self.version})
                else:
                    return {'error': ReflectorClientVersionError}
        if self.handshake:
            if 'sd_blob' in message.keys():
                blob = message.get('sd_blob_hash')
                ...
            elif 'blob' in message.keys():
                ...
    
    def connection_lost(self, exc: typing.Optional[Exception]):
        return exc
