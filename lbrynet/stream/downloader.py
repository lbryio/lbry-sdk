import os
import asyncio
import typing
import logging
from lbrynet.utils import resolve_host
from lbrynet.stream.assembler import StreamAssembler
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.blob_exchange.downloader import BlobDownloader
from lbrynet.dht.peer import KademliaPeer
if typing.TYPE_CHECKING:
    from lbrynet.conf import Config
    from lbrynet.dht.node import Node
    from lbrynet.blob.blob_manager import BlobManager
    from lbrynet.blob.blob_file import BlobFile

log = logging.getLogger(__name__)


def drain_into(a: list, b: list):
    while a:
        b.append(a.pop())


class StreamDownloader(StreamAssembler):
    def __init__(self, loop: asyncio.BaseEventLoop, config: 'Config', blob_manager: 'BlobFileManager', sd_hash: str,
                 output_dir: typing.Optional[str] = None, output_file_name: typing.Optional[str] = None):
        super().__init__(loop, blob_manager, sd_hash, output_file_name)
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
        self.fixed_peers_delay: typing.Optional[float] = None
        self.added_fixed_peers = False

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
        self.blob_downloader.close()

    def stop(self):
        if self.accumulate_task:
            self.accumulate_task.cancel()
            self.accumulate_task = None
        if self.assemble_task:
            self.assemble_task.cancel()
            self.assemble_task = None
        if self.fixed_peers_handle:
            self.fixed_peers_handle.cancel()
            self.fixed_peers_handle = None
        self.blob_downloader = None
        if self.stream_handle:
            if not self.stream_handle.closed:
                self.stream_handle.close()
            self.stream_handle = None
        if not self.stream_finished_event.is_set() and self.wrote_bytes_event.is_set() and \
                self.output_path and os.path.isfile(self.output_path):
            os.remove(self.output_path)

    async def get_blob(self, blob_hash: str, length: typing.Optional[int] = None) -> 'BlobFile':
        return await self.blob_downloader.download_blob(blob_hash, length)

    def add_fixed_peers(self):
        async def _add_fixed_peers():
            addresses = [
                (await resolve_host(url, port + 1, proto='tcp'), port)
                for url, port in self.config.reflector_servers
            ]

            def _delayed_add_fixed_peers():
                self.added_fixed_peers = True
                self.peer_queue.put_nowait([
                    KademliaPeer(self.loop, address=address, tcp_port=port + 1)
                    for address, port in addresses
                ])

            self.fixed_peers_handle = self.loop.call_later(self.fixed_peers_delay, _delayed_add_fixed_peers)
        if not self.config.reflector_servers:
            return
        if 'dht' in self.config.components_to_skip or not self.node or not \
                len(self.node.protocol.routing_table.get_peers()):
            self.fixed_peers_delay = 0.0
        else:
            self.fixed_peers_delay = self.config.fixed_peer_delay
        self.loop.create_task(_add_fixed_peers())

    def download(self, node: typing.Optional['Node'] = None):
        self.node = node
        self.assemble_task = self.loop.create_task(self.assemble_decrypted_stream(self.config.download_dir))
        self.add_fixed_peers()
