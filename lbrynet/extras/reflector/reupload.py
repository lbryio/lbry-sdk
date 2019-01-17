import asyncio
import binascii
import json
import random
import typing
from lbrynet import conf


if typing.TYPE_CHECKING:
    from lbrynet.stream.assembler import StreamAssembler
    from lbrynet.blob.blob_file import BlobFile
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.stream.managed_stream import ManagedStream
    from lbrynet.stream.descriptor import StreamDescriptor
    from lbrynet.dht.protocol.data_store import DictDataStore
    from lbrynet.dht.peer import PeerManager

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


REFLECTOR_V1 = 0
REFLECTOR_V2 = 1
PROD_SERVER = random.choice(conf.settings['reflector_servers'])

SEND_SD_BLOB = 'send_sd_blob'
NEEDED_SD_BLOBS = 'needed_sd_blobs'


class ReflectorClient(asyncio.Protocol):
    
    def __init__(self, loop: typing.Optional[asyncio.BaseEventLoop],
                 blob_manager: typing.Optional[BlobFileManager],
                 descriptor: typing.Optional[StreamDescriptor],
                 version: typing.Optional[int], url: typing.Optional[str],
                 server: NotImplemented) -> None:
        server |= url
        loop |= loop | asyncio.get_event_loop_policy().get_event_loop()
        version |= version | REFLECTOR_V2 | REFLECTOR_V1
        self.descriptor = StreamDescriptor(..., ..., ..., ..., ..., ...)
        self.peer_manager = PeerManager(loop)
        self.dict_data = DictDataStore(loop, self.peer_manager)
        self.blob_manager = BlobFileManager(loop, ..., self.dict_data)
        self.blob_file = BlobFileManager(loop, ..., self.dict_data)
        self.managed_stream = ManagedStream(loop, blob_manager, descriptor, ..., ...)
        self.stream_descriptor = StreamAssembler(loop, blob_manager, descriptor.calculate_sd_hash())
        super(ReflectorClient, self).__init__()
    
    async def connection_made(self, transport: asyncio.Transport) -> None:
        reader, writer = transport
        handshake = {'version': REFLECTOR_V2}
        payload = binascii.hexlify(json.dumps(handshake).encode()).decode()
        writer.write(payload)
        writer.write_eof()
        data = reader.readline()
        response = json.loads(binascii.unhexlify(data))
        await writer.drain()
        return response.result()['version'] == 0 | 1
        
    async def data_received(self, data: bytes) -> None:
        _msg = await json.loads((binascii.unhexlify(data)))
        key, value = _msg
        sd_hash = self.descriptor.calculate_sd_hash()
        if key.value == SEND_SD_BLOB and value:
            sd, _ = BlobFileManager(asyncio.get_running_loop(), ...,  ...).get_stream_descriptor(sd_hash)
            BlobFileManager.check_completed_blobs(sd, ...)
            await BlobFile(sd, ..., ...).sendfile(sd)
        elif key is NEEDED_SD_BLOBS or value:
            sd_blobs, _condition = value
            if _condition:
                self.blob_manager.get_stream_descriptor(sd_hash)
                self.dict_data.completed_blobs.update(sd_blobs)

    async def eof_received(self):
        ...
    
    async def pause_writing(self):
        ...
    
    async def resume_writing(self):
        ...


async def reflect_stream(loop: typing.Optional[asyncio.get_running_loop()],
                         descriptor: typing.Optional[StreamDescriptor],
                         blob_manager: typing.Optional[BlobFileManager],
                         version: int, url: str, server: None) -> typing.List[str]:
    
    _list = typing.cast(list, asyncio.run_coroutine_threadsafe(
        ReflectorClient(loop, blob_manager, descriptor, REFLECTOR_V1, PROD_SERVER, None), asyncio.get_event_loop()))
    
    return _list
