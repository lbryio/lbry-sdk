import os
import asyncio
import typing
import logging
from lbrynet.stream.assembler import StreamAssembler
from lbrynet.dht.peer_finder import StreamPeerFinder
if typing.TYPE_CHECKING:
    from lbrynet.peer import Peer
    from lbrynet.dht.node import Node
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.blob.blob_file import BlobFile

log = logging.getLogger(__name__)


def cancel_task(task: typing.Optional[asyncio.Task]):
    if task and not (task.done() or task.cancelled()):
        task.cancel()


def cancel_tasks(tasks: typing.List[typing.Optional[asyncio.Task]]):
    for task in tasks:
        cancel_task(task)


def drain_tasks(tasks: typing.List[typing.Optional[asyncio.Task]]):
    while tasks:
        cancel_task(tasks.pop())


# class SinglePeerStreamDownloader(StreamAssembler):
#     def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: 'BlobFileManager', peer: 'Peer', sd_hash: str,
#                  peer_timeout: int, peer_connect_timeout: int, output_dir: typing.Optional[str] = None,
#                  output_file_name: typing.Optional[str] = None):
#         super().__init__(loop, blob_manager, sd_hash)
#         self.peer = peer
#         self.peer_timeout = peer_timeout
#         self.peer_connect_timeout = peer_connect_timeout
#         self.download_task: asyncio.Task = None
#         self.output_dir = output_dir or os.getcwd()
#         self.output_file_name = output_file_name
#
#     async def get_blob(self, blob_hash: str, length: typing.Optional[int] = None) -> 'BlobFile':
#         blob = self.blob_manager.get_blob(blob_hash, length)
#         if not blob.get_is_verified():
#             await self.peer.request_blobs([blob], self.peer_timeout, self.peer_connect_timeout)
#         return blob
#
#     async def _download(self, finished_callback: typing.Callable[[], None]):
#         try:
#             await self.assemble_decrypted_stream(self.output_dir, self.output_file_name)
#             log.info(
#                 "downloaded stream %s -> %s", self.sd_hash, self.output_path
#             )
#             finished_callback()
#         finally:
#             self.peer.disconnect_tcp()
#             self.stop()
#
#     def download(self, finished_callback: typing.Callable[[], None]):
#         self.download_task = self.loop.create_task(self._download(finished_callback))


class StreamDownloader(StreamAssembler):
    def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: 'BlobFileManager', sd_hash: str,
                 peer_timeout: int, peer_connect_timeout: int, output_dir: typing.Optional[str] = None,
                 output_file_name: typing.Optional[str] = None):
        super().__init__(loop, blob_manager, sd_hash)
        self.peer_timeout = peer_timeout
        self.peer_connect_timeout = peer_connect_timeout
        self.peer_finder: StreamPeerFinder = None
        self.lock = asyncio.Lock(loop=self.loop)
        self.current_blob: 'BlobFile' = None

        self.download_task: asyncio.Task = None
        self.accumulate_connections_task: asyncio.Task = None

        self.new_connection_event = asyncio.Event(loop=self.loop)
        self.active_connections: typing.Set['Peer'] = set()
        self.running_download_requests: typing.List[asyncio.Task] = []
        self.pending_connections: typing.List[asyncio.Task] = []
        self.requested_from: typing.Dict[str, typing.List['Peer']] = {}

        self.output_dir = output_dir or os.getcwd()
        self.output_file_name = output_file_name

    async def _request_blob(self, peer: 'Peer'):
        if self.current_blob.get_is_verified():
            log.info("already verified")
            return
        log.info("request %s from %s:%i", self.current_blob.blob_hash[:8], peer.address, peer.tcp_port)
        try:
            await peer.request_blobs([self.current_blob], self.peer_timeout, self.peer_connect_timeout)
        except (asyncio.TimeoutError):
            self.active_connections.remove(peer)

    def _update_requests(self):
        self.new_connection_event.clear()
        if self.current_blob.blob_hash not in self.requested_from:
            self.requested_from[self.current_blob.blob_hash] = []
        for peer in self.active_connections:
            if peer not in self.requested_from[self.current_blob.blob_hash]:
                self.requested_from[self.current_blob.blob_hash].append(peer)
                self.running_download_requests.append(self.loop.create_task(self._request_blob(peer)))

    async def get_blob(self, blob_hash: str, length: typing.Optional[int] = None) -> 'BlobFile':
        async with self.lock:
            log.info("drain requests")
            drain_tasks(self.running_download_requests)
            self.current_blob = self.blob_manager.get_blob(blob_hash, length)
            if self.current_blob.get_is_verified():  # the blob is already completed
                return self.current_blob
            self._update_requests()  # send blob requests to all connected peers

        # the blob must be downloaded
        while not self.current_blob.get_is_verified():
            if not self.active_connections:  # wait for a new connection
                await self.new_connection_event.wait()
            err = None
            async with self.lock:  # wait for a successful download or another new connection
                try:
                    self._update_requests()
                    tasks = []
                    while self.running_download_requests:
                        tasks.append(self.running_download_requests.pop())
                    if tasks:
                        await_new_connection = asyncio.ensure_future(self.new_connection_event.wait(), loop=self.loop)
                        running_blob_downloads = asyncio.shield(asyncio.wait(tasks, loop=self.loop), loop=self.loop)
                        await asyncio.wait([await_new_connection, running_blob_downloads], return_when='FIRST_COMPLETED',
                                           loop=self.loop)
                        if await_new_connection and not await_new_connection.done():
                            await_new_connection.cancel()
                        if self.current_blob.get_is_verified():
                            log.info("drain requests")
                            drain_tasks(tasks)
                            return self.current_blob
                        else:
                            for task in tasks:
                                if task and not (task.done() or task.cancelled()):
                                    self.running_download_requests.append(task)
                    else:
                        log.info("wait for new connection, active: %i", len(self.active_connections))
                        await self.new_connection_event.wait()
                except asyncio.CancelledError as error:
                    err = error
            if err:
                raise err
            log.info("still downloading %s, %i pending requests", self.current_blob.blob_hash[:8], len(self.running_download_requests))
        log.info("drain requests")
        drain_tasks(self.running_download_requests)
        return self.current_blob

    async def _accumulate_connections(self):
        async def connect(peer: 'Peer'):
            # log.info("connect to %s:%i", peer.address, peer.tcp_port)
            connected = await peer.connect_tcp(self.peer_timeout, self.peer_connect_timeout)
            if connected:
                self.active_connections.add(peer)
                log.info("download stream from %s:%i", peer.address, peer.tcp_port)
                if not self.new_connection_event.is_set():
                    self.new_connection_event.set()
            else:
                log.info("failed to connect to %s:%i", peer.address, peer.tcp_port)

        try:
            async for _peer in self.peer_finder:
                self.pending_connections.append(self.loop.create_task(connect(_peer)))
        finally:
            await self.peer_finder.aclose()

    def stop(self):
        log.info("stop downloader")
        # cancel_task(self.download_task)
        cancel_task(self.accumulate_connections_task)
        drain_tasks(self.running_download_requests)
        drain_tasks(self.pending_connections)
        if self.peer_finder:
            self.peer_finder.aclose()
        while self.active_connections:
            self.active_connections.pop().disconnect_tcp()
        log.info("stopped downloader")

    async def _download(self):
        log.info("accumulate connections")
        self.accumulate_connections_task = self.loop.create_task(self._accumulate_connections())
        try:

            log.info("download and decrypt stream")
            await self.assemble_decrypted_stream(self.output_dir, self.output_file_name)
            log.info(
                "downloaded stream %s -> %s", self.sd_hash, self.output_path
            )
        except asyncio.CancelledError:
            log.info("cancelled")
        else:
            log.info("set file status to finished")
            await self.blob_manager.storage.change_file_status(
                self.descriptor.stream_hash, 'finished'
            )
        finally:
            self.stop()

    def download(self, node: 'Node'):
        log.info("make download task")
        self.peer_finder = StreamPeerFinder(
            self.loop, self.blob_manager, node, self.sd_hash, self.peer_timeout, self.peer_connect_timeout
        )
        self.download_task = self.loop.create_task(self._download())
