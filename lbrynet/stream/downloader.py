import asyncio
import typing
import logging
import binascii
from lbrynet.error import DownloadSDTimeout
from lbrynet.utils import resolve_host
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.blob_exchange.downloader import BlobDownloader
from lbrynet.dht.peer import KademliaPeer
if typing.TYPE_CHECKING:
    from lbrynet.conf import Config
    from lbrynet.dht.node import Node
    from lbrynet.blob.blob_manager import BlobManager
    from lbrynet.blob.blob_file import AbstractBlob
    from lbrynet.blob.blob_info import BlobInfo

log = logging.getLogger(__name__)


class StreamDownloader:
    def __init__(self, loop: asyncio.BaseEventLoop, config: 'Config', blob_manager: 'BlobManager', sd_hash: str,
                 descriptor: typing.Optional[StreamDescriptor] = None):
        self.loop = loop
        self.config = config
        self.blob_manager = blob_manager
        self.sd_hash = sd_hash
        self.search_queue = asyncio.Queue(loop=loop)     # blob hashes to feed into the iterative finder
        self.peer_queue = asyncio.Queue(loop=loop)       # new peers to try
        self.blob_downloader = BlobDownloader(self.loop, self.config, self.blob_manager, self.peer_queue)
        self.descriptor: typing.Optional[StreamDescriptor] = descriptor
        self.node: typing.Optional['Node'] = None
        self.accumulate_task: typing.Optional[asyncio.Task] = None
        self.fixed_peers_handle: typing.Optional[asyncio.Handle] = None
        self.fixed_peers_delay: typing.Optional[float] = None
        self.added_fixed_peers = False
        self.time_to_descriptor: typing.Optional[float] = None
        self.time_to_first_bytes: typing.Optional[float] = None

    async def add_fixed_peers(self):
        def _delayed_add_fixed_peers():
            self.added_fixed_peers = True
            self.peer_queue.put_nowait([
                KademliaPeer(self.loop, address=address, tcp_port=port + 1)
                for address, port in addresses
            ])

        if not self.config.reflector_servers:
            return
        addresses = [
            (await resolve_host(url, port + 1, proto='tcp'), port)
            for url, port in self.config.reflector_servers
        ]
        if 'dht' in self.config.components_to_skip or not self.node or not \
                len(self.node.protocol.routing_table.get_peers()):
            self.fixed_peers_delay = 0.0
        else:
            self.fixed_peers_delay = self.config.fixed_peer_delay

        self.fixed_peers_handle = self.loop.call_later(self.fixed_peers_delay, _delayed_add_fixed_peers)

    async def load_descriptor(self):
        # download or get the sd blob
        sd_blob = self.blob_manager.get_blob(self.sd_hash)
        if not sd_blob.get_is_verified():
            try:
                now = self.loop.time()
                sd_blob = await asyncio.wait_for(
                    self.blob_downloader.download_blob(self.sd_hash),
                    self.config.blob_download_timeout, loop=self.loop
                )
                log.info("downloaded sd blob %s", self.sd_hash)
                self.time_to_descriptor = self.loop.time() - now
            except asyncio.TimeoutError:
                raise DownloadSDTimeout(self.sd_hash)

        # parse the descriptor
        self.descriptor = await StreamDescriptor.from_stream_descriptor_blob(
            self.loop, self.blob_manager.blob_dir, sd_blob
        )
        log.info("loaded stream manifest %s", self.sd_hash)

    async def start(self, node: typing.Optional['Node'] = None):
        # set up peer accumulation
        if node:
            self.node = node
            _, self.accumulate_task = self.node.accumulate_peers(self.search_queue, self.peer_queue)
        await self.add_fixed_peers()
        # start searching for peers for the sd hash
        self.search_queue.put_nowait(self.sd_hash)
        log.info("searching for peers for stream %s", self.sd_hash)

        if not self.descriptor:
            await self.load_descriptor()

        # add the head blob to the peer search
        self.search_queue.put_nowait(self.descriptor.blobs[0].blob_hash)
        log.info("added head blob to peer search for stream %s", self.sd_hash)

        if not await self.blob_manager.storage.stream_exists(self.sd_hash):
            await self.blob_manager.storage.store_stream(
                self.blob_manager.get_blob(self.sd_hash, length=self.descriptor.length), self.descriptor
            )

    async def download_stream_blob(self, blob_info: 'BlobInfo') -> 'AbstractBlob':
        if not filter(lambda blob: blob.blob_hash == blob_info.blob_hash, self.descriptor.blobs[:-1]):
            raise ValueError(f"blob {blob_info.blob_hash} is not part of stream with sd hash {self.sd_hash}")
        blob = await self.blob_downloader.download_blob(blob_info.blob_hash, blob_info.length)
        return blob

    def _decrypt_blob(self, blob_info: 'BlobInfo', blob: 'AbstractBlob'):
        return blob.decrypt(
            binascii.unhexlify(self.descriptor.key.encode()), binascii.unhexlify(blob_info.iv.encode())
        )

    async def decrypt_blob(self, blob_info: 'BlobInfo', blob: 'AbstractBlob') -> bytes:
        return await self.loop.run_in_executor(None, self._decrypt_blob, blob_info, blob)

    async def read_blob(self, blob_info: 'BlobInfo') -> bytes:
        start = None
        if self.time_to_first_bytes is None:
            start = self.loop.time()
        blob = await self.download_stream_blob(blob_info)
        decrypted = await self.decrypt_blob(blob_info, blob)
        if start:
            self.time_to_first_bytes = self.loop.time() - start
        return decrypted

    def stop(self):
        if self.accumulate_task:
            self.accumulate_task.cancel()
            self.accumulate_task = None
        if self.fixed_peers_handle:
            self.fixed_peers_handle.cancel()
            self.fixed_peers_handle = None
        self.blob_downloader.close()
