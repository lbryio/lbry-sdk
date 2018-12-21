import os
import asyncio
import typing
import logging
import binascii
from lbrynet.blob.blob_file import BlobFile, MAX_BLOB_SIZE
from lbrynet.blob.blob_manager import BlobFileManager
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.dht.node import Node
if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_info import BlobInfo
    from lbrynet.peer import Peer

log = logging.getLogger(__name__)


class AsyncGeneratorJunction:
    """
    A helper to interleave the results from multiple async generators into one
    async generator.
    """

    def __init__(self, loop: asyncio.BaseEventLoop, queue: typing.Optional[asyncio.Queue] = None):
        self.loop = loop
        self.queue = queue or asyncio.Queue(loop=loop)
        self.handles: typing.List[asyncio.TimerHandle] = []
        self.running_iterators: typing.Dict[typing.AsyncGenerator, bool] = {}

    @property
    def running(self):
        return any(self.running_iterators.values())

    def add_generator(self, async_gen: typing.AsyncGenerator):
        """
        Add an async generator. This can be called during an iteration of the generator junction.
        """

        async def iterate(iterator: typing.AsyncGenerator):
            async for item in iterator:
                self.queue.put_nowait(item)
            self.running_iterators[iterator] = False

        self.running_iterators[async_gen] = True
        self.handles.append(self.loop.call_soon(lambda : self.loop.create_task(iterate(async_gen))))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.running:
            return await self.queue.get()
        else:
            raise StopAsyncIteration()


class SinglePeerStreamDownloader:
    """
    Downloads a stream from a peer from the first unverified blob to the last
    """

    def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: BlobFileManager,
                 peer: 'Peer', sd_hash: str, got_head_blob_info: typing.Optional[asyncio.Future],
                 download_finished: asyncio.Event, position: typing.Optional[int] = 0,
                 peer_timeout: typing.Optional[int] = 30, peer_connect_timeout: typing.Optional[int] = 30):
        self.loop = loop
        self.blob_manager = blob_manager
        self.sd_blob = self.blob_manager.get_blob(sd_hash)
        self.descriptor: StreamDescriptor = None
        self.peer = peer
        self.position = position
        self.peer_timeout = peer_timeout
        self.peer_connect_timeout = peer_connect_timeout
        self.pending: asyncio.Future = None
        self.downloaded_blobs: typing.List['BlobFile'] = []
        self.got_head_blob_info = got_head_blob_info
        self.download_finished = download_finished

    async def _get_next_blob(self, write_decrypt_callback: typing.Callable[['BlobInfo'], typing.Awaitable[None]]) -> None:

        blob = self.blob_manager.get_blob(
                self.descriptor.blobs[self.position].blob_hash, self.descriptor.blobs[self.position].length
        )
        if not blob.get_is_verified():
            log.info("request next blob: %s from %s", blob.blob_hash[:8], self.peer)
            await self.peer.request_blobs([blob])
            await blob.finished_writing
            log.info("got blob from %s", self.peer)
        else:
            log.info("blob is verified")
        await write_decrypt_callback(self.descriptor.blobs[self.position])
        self.position += 1
        if self.position < len(self.descriptor.blobs) - 2:
            return await self._get_next_blob(write_decrypt_callback)

    async def get_next_blob(self, write_decrypt_callback: typing.Callable[['BlobInfo'], typing.Awaitable[None]]) -> None:
        try:
            if not self.descriptor:
                if not self.sd_blob.get_is_verified():
                    downloaded_blobs = await self.peer.request_blobs([self.sd_blob])
                    if downloaded_blobs:
                        await self.sd_blob.finished_writing
                        self.downloaded_blobs.append(self.sd_blob)
                        self.descriptor = await StreamDescriptor.from_stream_descriptor_blob(self.loop, self.sd_blob)
                        if self.got_head_blob_info and not (self.got_head_blob_info.done() or
                                                            self.got_head_blob_info.cancelled()):
                            self.got_head_blob_info.set_result(self.descriptor.blobs[0])
                        await self.descriptor.save_to_database(self.loop, self.blob_manager.storage)
                    else:
                        log.info("failed to download sd blob from %s", self.peer)
                        return
                else:
                    self.descriptor = await StreamDescriptor.from_stream_descriptor_blob(self.loop, self.sd_blob)

            if self.position < len(self.descriptor.blobs) - 2:
                return await self._get_next_blob(write_decrypt_callback)
            if not self.download_finished.is_set():
                self.download_finished.set()
            log.info("finished! %s", self.peer)
        finally:
            self.peer.disconnect_tcp()
            log.info("disconnected %s", self.peer)


class StreamDownloader:
    """
    Downloads a stream from multiple peers and writes the decrypted assembled output
    """
    def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: BlobFileManager, node: Node, sd_hash: str,
                 peer_timeout: typing.Optional[int] = 30, peer_connect_timeout: typing.Optional[int] = 30,
                 file_name: typing.Optional[str] = None, download_dir: typing.Optional[str] = None):
        self.loop = loop
        self.blob_manager = blob_manager
        self.node = node
        self.sd_hash = sd_hash
        self.peer_timeout = peer_timeout
        self.peer_connect_timeout = peer_connect_timeout
        self.descriptor: StreamDescriptor = None
        self.file_name = file_name
        self.download_dir = download_dir or os.getcwd()
        self._bytes_written = 0
        self._running = False
        self.attempted: typing.Set['Peer'] = set()

        self.lock = asyncio.Lock(loop=self.loop)
        self.first_bytes_written = asyncio.Event(loop=self.loop)
        self.download_finished = asyncio.Event(loop=self.loop)
        self.got_head_blob_info = None
        self.download_task: asyncio.Task = None
        self.stop_task = asyncio.Task = None
        self.downloader_tasks: typing.List[asyncio.Task] = []

    def stop(self):
        if not (self.download_task.done() or self.download_task.cancelled()):
            self.download_task.cancel()
        while self.downloader_tasks:
            task = self.downloader_tasks.pop()
            if not (task.done() or task.cancelled()):
                task.cancel()
        if not (self.stop_task.done() or self.stop_task.cancelled()):
            self.stop_task.cancel()

    async def _stop_after_finished(self):
        await self.download_finished.wait()
        self.stop()

    @property
    def bytes_written(self) -> int:
        return self._bytes_written

    @property
    def running(self) -> bool:
        return self._running

    @property
    def output_path(self) -> str:
        return os.path.join(self.download_dir, self.file_name or self.descriptor.suggested_file_name)

    async def write_stream_out(self, blob_info: 'BlobInfo') -> None:
        if not self.descriptor:
            self.descriptor = await StreamDescriptor.from_stream_descriptor_blob(self.loop, self.blob_manager.get_blob(self.sd_hash))
        offset = blob_info.blob_num * (MAX_BLOB_SIZE - 1)
        blob = self.blob_manager.get_blob(blob_info.blob_hash, blob_info.length)

        def _decrypt_and_write():
            with open(self.output_path, 'wb+') as stream_handle:
                stream_handle.seek(offset)
                decrypted = blob.decrypt(binascii.unhexlify(self.descriptor.key.encode()),
                                         binascii.unhexlify(blob_info.iv.encode()))
                stream_handle.write(decrypted)
                stream_handle.flush()
            if not self.first_bytes_written.is_set():
                self.first_bytes_written.set()

        log.info("decrypt lock")
        await self.lock.acquire()
        log.info("acquired")
        try:
            await self.loop.run_in_executor(None, _decrypt_and_write)
        finally:
            self.lock.release()
        log.info("decrypted %s", blob.blob_hash)
        return

    async def _add_peer(self, peer: 'Peer') -> None:
        self.attempted.add(peer)
        downloader = SinglePeerStreamDownloader(
            self.loop, self.blob_manager, peer, self.sd_hash, self.got_head_blob_info, self.download_finished,
            0, self.peer_timeout, self.peer_connect_timeout
        )
        connected = await peer.connect_tcp(self.peer_timeout, self.peer_connect_timeout)
        if not connected:
            log.info('failed to connect to %s', peer)
        else:
            try:
                log.info('connected to %s', peer)
                return await downloader.get_next_blob(self.write_stream_out)
            except asyncio.TimeoutError:
                pass

    def add_peer(self, peer: 'Peer') -> None:
        if peer not in self.attempted:
            self.downloader_tasks.append(self.loop.create_task(self._add_peer(peer)))
        return

    async def _download(self):
        sd_blob = self.blob_manager.get_blob(self.sd_hash)
        if sd_blob.get_is_verified():
            self.descriptor = await StreamDescriptor.from_stream_descriptor_blob(self.loop, sd_blob)
            blobs = [self.blob_manager.get_blob(info.blob_hash, info.length) for info in self.descriptor.blobs[:-1]]
            verified = [blob.get_is_verified() for blob in blobs]
            if any(verified):
                self.first_bytes_written.set()
            if all(verified):
                self._running = False
                log.error("set finished")
                self.download_finished.set()
                return

        peer_generator = AsyncGeneratorJunction(self.loop)
        peer_generator.add_generator(
            self.node.get_iterative_value_finder(binascii.unhexlify(self.sd_hash.encode()), bottom_out_limit=5,
                                                 max_results=-1)
        )

        async def got_head_blob_info(fut: asyncio.Future):
            head_blob_info: 'BlobInfo' = fut.result()
            peer_generator.add_generator(
                self.node.get_iterative_value_finder(binascii.unhexlify(head_blob_info.blob_hash.encode()),
                                                     bottom_out_limit=5, max_results=-1)
            )

        if sd_blob.get_is_verified():
            peer_generator.add_generator(
                self.node.get_iterative_value_finder(binascii.unhexlify(self.descriptor.blobs[0].blob_hash.encode()),
                                                     bottom_out_limit=5, max_results=-1)
            )
        elif self.got_head_blob_info is not None:
            self.got_head_blob_info.add_done_callback(got_head_blob_info)

        async for peers in peer_generator:
            assert isinstance(peers, list)
            for peer in peers:
                if peer not in self.attempted:
                    if not peer.tcp_last_down or (peer.tcp_last_down + 300) < self.loop.time():
                        self.add_peer(peer)

    def download(self):
        self._running = True
        with open(self.output_path, 'wb'):
            pass
        self.download_task = self.loop.create_task(self._download())
        self.stop_task = self.loop.create_task(self._stop_after_finished())
