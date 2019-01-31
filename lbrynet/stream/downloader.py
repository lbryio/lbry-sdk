import asyncio
import typing
import socket
import logging
from lbrynet.stream.assembler import StreamAssembler
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.blob_exchange.downloader import BlobDownloader
from lbrynet.dht.peer import KademliaPeer
if typing.TYPE_CHECKING:
    from lbrynet.conf import Config
    from lbrynet.dht.node import Node
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.blob.blob_file import BlobFile

log = logging.getLogger(__name__)


def drain_into(a: list, b: list):
    while a:
        b.append(a.pop())


async def resolve_host(loop: asyncio.BaseEventLoop, url: str):
    info = await loop.getaddrinfo(
        url, 'https',
        proto=socket.IPPROTO_TCP,
    )
    return info[0][4][0]


class StreamDownloader(StreamAssembler):
    def __init__(self, loop: asyncio.BaseEventLoop, config: 'Config', blob_manager: 'BlobFileManager', sd_hash: str,
                 output_dir: typing.Optional[str] = None, output_file_name: typing.Optional[str] = None):
        super().__init__(loop, blob_manager, sd_hash)
        self.config = config
        self.output_dir = output_dir or self.config.download_dir
        self.output_file_name = output_file_name
        self.blob_downloader: typing.Optional[BlobDownloader] = None
        self.search_queue = asyncio.Queue(loop=loop)
        self.peer_queue = asyncio.Queue(loop=loop)
        self.accumulate_task: typing.Optional[asyncio.Task] = None
        self.descriptor: typing.Optional[StreamDescriptor]
        self.node: typing.Optional['Node'] = None
        self.assemble_task: typing.Optional[asyncio.Task] = None
        self.fixed_peers_handle: typing.Optional[asyncio.Handle] = None

    async def setup(self):  # start the peer accumulator and initialize the downloader
        if self.blob_downloader:
            raise Exception("downloader is already set up")
        if self.node:
            _, self.accumulate_task = self.node.accumulate_peers(self.search_queue, self.peer_queue)
        self.blob_downloader = BlobDownloader(self.loop, self.config, self.blob_manager, self.peer_queue)
        self.search_queue.put_nowait(self.sd_hash)

    async def after_got_descriptor(self):
        self.search_queue.put_nowait(self.descriptor.blobs[0].blob_hash)
        log.info("added head blob to search")

    async def after_finished(self):
        log.info("downloaded stream %s -> %s", self.sd_hash, self.output_path)
        await self.blob_manager.storage.change_file_status(self.descriptor.stream_hash, 'finished')

    async def stop(self):
        if self.accumulate_task and not self.accumulate_task.done():
            self.accumulate_task.cancel()
            self.accumulate_task = None
        if self.assemble_task and not self.assemble_task.done():
            self.assemble_task.cancel()
            self.assemble_task = None
        if self.fixed_peers_handle:
            self.fixed_peers_handle.cancel()
            self.fixed_peers_handle = None
        self.blob_downloader = None

    async def get_blob(self, blob_hash: str, length: typing.Optional[int] = None) -> 'BlobFile':
        return await self.blob_downloader.download_blob(blob_hash, length)

    def add_fixed_peers(self):
        async def _add_fixed_peers():
            self.peer_queue.put_nowait([
                KademliaPeer(self.loop, address=(await resolve_host(self.loop, url)), tcp_port=port + 1)
                for url, port in self.config.reflector_servers
            ])
        if self.config.reflector_servers:
            self.fixed_peers_handle = self.loop.call_later(
                self.config.fixed_peer_delay if 'dht' not in self.config.components_to_skip else 0.0,
                self.loop.create_task, _add_fixed_peers()
            )

    def download(self, node: typing.Optional['Node'] = None):
        self.node = node
        self.assemble_task = self.loop.create_task(self.assemble_decrypted_stream(self.config.download_dir))
        self.add_fixed_peers()
