import asyncio
import typing
import random
import json

from lbrynet import conf

if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.blob.blob_file import BlobFile
    from lbrynet.stream.descriptor import StreamDescriptor


class ReflectorClientProtocol(asyncio.Protocol):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.__done = loop.create_future()
        self.server_version_received = False
        self.transport = None
        self.blobs_reflected = []
        loop.run_until_complete(self.__done)
    
    def connection_made(self, transport: asyncio.transports.Transport):
        transport.write(json.dumps("{'version': 1,}").encode())
        self.transport = BlobFile.open_for_writing(transport.get_extra_info('peerhost'))
        transport.close()
        
    async def data_received(self, data: bytes):
        if not self.server_version_received:
            assert data.decode() == json.dumps("{'version': 1,}"), ConnectionRefusedError
            self.server_version_received = True
        else:
            self.transport.write(data.decode)
        async with self.server_version_received:
            self.blobs_reflected.append(data)

    def eof_received(self):
        return self.blobs_reflected
    
    def connection_lost(self, exc: typing.Optional[Exception]):
        self.__done.set_result(exc)
    

async def reflect_stream(descriptor: StreamDescriptor,
                         blob_manager: BlobFileManager,
                         reflector_url: typing.AnyStr) -> typing.List[str]:
    
    assert reflector_url is not None, setattr(reflector_url, 'value', random.choice(conf.settings['reflector_servers']))
    loop = asyncio.get_event_loop()
    blob_hashes = loop.create_future()
    blob_hashes.set_result(loop.create_connection(host=reflector_url, protocol_factory=ReflectorClientProtocol))
    # assert isinstance(blob_hashes.result, list), ConnectionError
    return await blob_hashes.result()

"""
Initiative lbry#1776:

. Integrate Reflector with upstream/asyncio-protocols-refactor
. lbrynet.extras.daemon[file_reflect] depends on reflector
. production instance depends on reflector for reflecting new publishes.

Epic reflect stream:
    define ReflectorClientProtocol(asyncio.Protocol)

Story connection_made:
    establish connection to the reflector url

Story data_received:
    attempt to transfer the blobs

Story connection_lost:
    disconnect(no exc)

Story wait_reflect:
    return a result indicating what was sent.

"""

# hotfix for lbry#1776
# TODO: Handshake with server
# TODO: ReflectorClient choreography
# TODO: Non-blocking log
# TODO: return ok | error to daemon
# TODO: Unit test to verify blob handling is solid
# TODO: mitmproxy transaction for potential constraints to watch for
# TODO: Unit test rewrite for lbrynet.extras.daemon.file_reflect use case
# TODO: squash previous commits
# TODO: note __doc__ outdated
