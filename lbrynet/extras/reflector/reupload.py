import asyncio
import binascii
import json
import random
import typing

from lbrynet import conf

if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.stream.descriptor import StreamDescriptor


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


class ReflectorClient(asyncio.Protocol):
    
    REFLECTOR_V1 = 0
    REFLECTOR_V2 = 1
    PROD_SERVER = random.choice(conf.settings['reflector_servers'])
    
    def __init__(self, version: int, server_url: str):
        self.version = version
        self.server = server_url
        self.server_version = self.handle_handshake()
        self.descriptor = asyncio.Event()
        self.blob_file_manager = asyncio.Event()
        
    async def handle_handshake(self) -> typing.Any[int, Exception]:
        """
        Handshake sequence.
        """
        reader, writer = await asyncio.open_connection(host=self.server)
        handshake = {'version': self.version}
        payload = binascii.hexlify(json.dumps(handshake).encode()).decode()
        await writer.write(payload)
        await writer.write_eof()
        data = await reader.readline()
        response = await json.loads(binascii.unhexlify(data))
        await writer.drain()
        return await response.result()['version']

    """
    ############# Stream descriptor requests and responses #############
    (if sending blobs directly this is skipped)
    If the client is reflecting a whole stream, they send a stream descriptor request:
    {
        'sd_blob_hash': str,
        'sd_blob_size': int
    }

    The server indicates if it's aware of this stream already by requesting (or not requesting)
    the stream descriptor blob. If the server has a validated copy of the sd blob, it will
    include the needed_blobs field (a list of blob hashes missing from reflector) in the response.
    If the server does not have the sd blob the needed_blobs field will not be included, as the
    server does not know what blobs it is missing - so the client should send all of the blobs
    in the stream.
    {
        'send_sd_blob': bool
        'needed_blobs': list, conditional
    }

    The client may begin the file transfer of the sd blob if send_sd_blob was True.
    If the client sends the blob, after receiving it the server indicates if the
    transfer was successful:
    {
        'received_sd_blob': bool
    }
    If the transfer was not successful (False), the blob is added to the needed_blobs queue
    """

    # Expecting:
    # {
    #     'sd_blob_hash': str,
    #     'sd_blob_size': int
    # }
    async def reflect_stream(self, descriptor: typing.Optional[StreamDescriptor],
                 blob_manager: typing.Optional[BlobFileManager]) -> typing.List[str]:
        ...
    
    """
    ############# Blob requests and responses #############
    A client with blobs to reflect (either populated by the client or by the stream descriptor
    response) queries if the server is ready to begin transferring a blob
    {
        'blob_hash': str,
        'blob_size': int
    }

    The server replies, send_blob will be False if the server has a validated copy of the blob:
    {
        'send_blob': bool
    }

    The client may begin the raw blob file transfer if the server replied True.
    If the client sends the blob, the server replies:
    {
        'received_blob': bool
    }
    If the transfer was not successful (False), the blob is re-added to the needed_blobs queue

    Blob requests continue for each of the blobs the client has queued to send, when completed
    the client disconnects.
    """

    # hotfix for lbry#1776
    # TODO: ReflectorClient choreography
    # TODO: return ok | error to daemon
    # TODO: Unit test to verify blob handling is solid
    # TODO: mitmproxy transaction for potential constraints to watch for
    # TODO: Unit test rewrite for lbrynet.extras.daemon.file_reflect use case
    # TODO: squash previous commits
