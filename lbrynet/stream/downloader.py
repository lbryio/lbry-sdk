import os
import asyncio
import typing
import logging
from lbrynet.stream.assembler import StreamAssembler
from lbrynet.stream.peer_finder import StreamPeerFinder
if typing.TYPE_CHECKING:
    from lbrynet.peer import Peer
    from lbrynet.dht.node import Node
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.blob.blob_file import BlobFile

log = logging.getLogger(__name__)


class SinglePeerStreamDownloader(StreamAssembler):
    def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: 'BlobFileManager', peer: 'Peer', sd_hash: str,
                 peer_timeout: int, peer_connect_timeout: int, output_dir: typing.Optional[str] = None,
                 output_file_name: typing.Optional[str] = None):
        super().__init__(loop, blob_manager, sd_hash)
        self.peer = peer
        self.peer_timeout = peer_timeout
        self.peer_connect_timeout = peer_connect_timeout
        self.download_task: asyncio.Task = None
        self.output_dir = output_dir or os.getcwd()
        self.output_file_name = output_file_name

    async def get_blob(self, blob_hash: str, length: typing.Optional[int] = None) -> 'BlobFile':
        blob = self.blob_manager.get_blob(blob_hash, length)
        if not blob.get_is_verified():
            await self.peer.request_blobs([blob], self.peer_timeout, self.peer_connect_timeout)
        return blob

    async def _download(self, finished_callback: typing.Callable[[], None]):
        try:
            await self.assemble_decrypted_stream(self.output_dir, self.output_file_name)
            log.info(
                "downloaded stream %s -> %s", self.sd_hash, self.output_path
            )
            finished_callback()
        finally:
            self.peer.disconnect_tcp()
            self.stop()

    def download(self, finished_callback: typing.Callable[[], None]):
        self.download_task = self.loop.create_task(self._download(finished_callback))


class StreamDownloader(StreamAssembler):
    def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: 'BlobFileManager', sd_hash: str,
                 peer_timeout: int, peer_connect_timeout: int, output_dir: typing.Optional[str] = None,
                 output_file_name: typing.Optional[str] = None):
        super().__init__(loop, blob_manager, sd_hash)
        self.peer_timeout = peer_timeout
        self.peer_connect_timeout = peer_connect_timeout
        self.download_task: asyncio.Task = None
        self.accumulator_task: asyncio.Task = None
        self.peer_finder: StreamPeerFinder = None
        self.blobs: typing.Dict[str, 'BlobFile'] = {}
        self.lock = asyncio.Lock(loop=self.loop)
        self.current_blob: 'BlobFile' = None
        self.connections: typing.Set['Peer'] = set()
        self.pending_requests: typing.Dict['Peer', asyncio.Future] = {}
        self.has_peers = asyncio.Event(loop=self.loop)
        self.tasks: typing.List[asyncio.Task] = []
        self.requests: typing.Dict[str, typing.List['Peer']] = {}

        self.output_dir = output_dir or os.getcwd()
        self.output_file_name = output_file_name

    async def _request_blob(self, peer: 'Peer'):
        log.debug("request from %s:%i", peer.address, peer.tcp_port)
        try:
            await peer.request_blobs([self.current_blob], self.peer_timeout, self.peer_connect_timeout)
        except asyncio.TimeoutError:
            self.connections.remove(peer)
            if not self.connections:
                self.has_peers.clear()

    def _update_requests(self):
        if self.current_blob.blob_hash not in self.requests:
            self.requests[self.current_blob.blob_hash] = []
        for peer in self.connections:
            if peer not in self.requests[self.current_blob.blob_hash]:
                self.requests[self.current_blob.blob_hash].append(peer)
                self.tasks.append(self.loop.create_task(self._request_blob(peer)))
        self.has_peers.clear()

    async def get_blob(self, blob_hash: str, length: typing.Optional[int] = None) -> 'BlobFile':
        async with self.lock:
            self.current_blob = self.blob_manager.get_blob(blob_hash, length)
            if self.current_blob.get_is_verified():
                return self.current_blob

        while not self.current_blob.get_is_verified():
            if self.current_blob.get_is_verified():
                return self.current_blob
            async with self.lock:
                self._update_requests()
            if not self.tasks:
                await self.has_peers.wait()
            async with self.lock:
                self._update_requests()
                tasks = []
                if self.tasks:
                    while self.tasks:
                        tasks.append(self.tasks.pop())
            f1 = asyncio.ensure_future(self.has_peers.wait(), loop=self.loop)
            f2 = asyncio.shield(asyncio.ensure_future(asyncio.wait(tasks, loop=self.loop), loop=self.loop))
            log.info("%i blob download requests pending", len(tasks))
            await asyncio.wait([f1, f2], return_when='FIRST_COMPLETED', loop=self.loop)
            if f1 and not f1.done():
                f1.cancel()
            if self.current_blob.get_is_verified():
                log.info('downloaded blob')
                return self.current_blob
            async with self.lock:
                for task in tasks:
                    if task and not (task.done() or task.cancelled()):
                        self.tasks.append(task)
            log.info("still downloading, %i pending requests", len(self.tasks))
        log.info('downloaded blob')
        return self.current_blob

    async def _accumulate_connections(self):
        async def connect(peer: 'Peer'):
            # log.info("connect to %s:%i", peer.address, peer.tcp_port)
            connected = await peer.connect_tcp(self.peer_timeout, self.peer_connect_timeout)
            if connected:
                async with self.lock:
                    self.connections.add(peer)
                    log.info("download stream from %s:%i", peer.address, peer.tcp_port)
                    if not self.has_peers.is_set():
                        self.has_peers.set()
            else:
                log.info("failed to connect to %s:%i", peer.address, peer.tcp_port)

        async for _peer in self.peer_finder:
            self.loop.create_task(connect(_peer))

    def stop(self):
        if self.accumulator_task and not (self.accumulator_task.done() or self.accumulator_task.cancelled()):
            self.accumulator_task.cancel()
        if self.download_task and not (self.download_task.done() or self.download_task.cancelled()):
            self.download_task.cancel()
        if self.peer_finder:
            self.peer_finder.stop()
        while self.connections:
            self.connections.pop().disconnect_tcp()

    async def _download(self, finished_callback: typing.Callable[[], None]):
        self.accumulator_task = self.loop.create_task(self._accumulate_connections())
        try:
            await self.assemble_decrypted_stream(self.output_dir, self.output_file_name)
            log.info(
                "downloaded stream %s -> %s", self.sd_hash, self.output_path
            )
            await self.blob_manager.storage.change_file_status(
                self.descriptor.stream_hash, 'finished'
            ).asFuture(self.loop)
            finished_callback()
        finally:
            self.stop()

    def download(self, node: 'Node', finished_callback: typing.Callable[[], None]):
        self.peer_finder = StreamPeerFinder(
            self.loop, self.blob_manager, node, self.sd_hash, self.peer_timeout, self.peer_connect_timeout
        )
        self.download_task = self.loop.create_task(self._download(finished_callback))
