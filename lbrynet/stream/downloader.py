import os
import asyncio
import typing
import logging
from lbrynet.stream.assembler import StreamAssembler
from lbrynet.blob_exchange.client import BlobExchangeClientProtocol
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


def drain_into(a: list, b: list):
    while a:
        b.append(a.pop())

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
        self.current_blob: 'BlobFile' = None

        self.download_task: asyncio.Task = None
        self.accumulate_connections_task: asyncio.Task = None

        self.new_peer_event = asyncio.Event(loop=self.loop)

        self.active_connections: typing.Dict['Peer', BlobExchangeClientProtocol] = {}

        self.running_download_requests: typing.List[asyncio.Task] = []

        self.requested_from: typing.Dict[str, typing.List['Peer']] = {}

        self.output_dir = output_dir or os.getcwd()
        self.output_file_name = output_file_name

        self._lock = asyncio.Lock(loop=self.loop)

    async def _update_current_blob(self, blob: 'BlobFile'):
        async with self._lock:
            drain_tasks(self.running_download_requests)
            self.current_blob = blob
            if not blob.get_is_verified():
                self._update_requests()

    async def _request_blob(self, peer: 'Peer'):
        if self.current_blob.get_is_verified():
            log.info("already verified")
            return
        log.info("request %s from %s:%i", self.current_blob.blob_hash[:8], peer.address, peer.tcp_port)
        try:
            success = await peer.request_blob(self.current_blob, self.active_connections[peer],
                                              self.peer_connect_timeout)
            if not success:  # drop connection to peer who didn't have a blob
                async with self._lock:
                    proto = self.active_connections.pop(peer, None)
                    if proto and proto.transport:
                        proto.transport.close()

        except asyncio.TimeoutError:
            async with self._lock:
                proto = self.active_connections.pop(peer, None)
                if proto and proto.transport:
                    proto.transport.close()

    def _update_requests(self):
        self.new_peer_event.clear()
        if self.current_blob.blob_hash not in self.requested_from:
            self.requested_from[self.current_blob.blob_hash] = []
        for peer in self.active_connections:
            if peer not in self.requested_from[self.current_blob.blob_hash]:
                self.requested_from[self.current_blob.blob_hash].append(peer)
                self.running_download_requests.append(self.loop.create_task(self._request_blob(peer)))

    async def wait_for_download_or_new_peer(self) -> typing.Optional['BlobFile']:
        async with self._lock:
            # update the running download requests
            self._update_requests()

            # drain the tasks into a temporary list
            download_tasks = []
            drain_into(self.running_download_requests, download_tasks)

        # if not download_tasks:
        #     log.info("wait for new connection, active: %i", len(self.active_connections))
        #     await self.new_peer_event.wait()
        #     return False

        got_new_peer = self.loop.create_task(self.new_peer_event.wait())

        await asyncio.wait([got_new_peer] + download_tasks, return_when='FIRST_COMPLETED',
                           loop=self.loop)
        async with self._lock:
            if self.current_blob.get_is_verified():
                if got_new_peer and not (got_new_peer.cancelled() or got_new_peer.done()):
                    got_new_peer.cancel()
                drain_tasks(download_tasks)
                return self.current_blob
            else:
                for task in download_tasks:
                    if task and not (task.done() or task.cancelled()):
                        self.running_download_requests.append(task)
                return

    async def get_blob(self, blob_hash: str, length: typing.Optional[int] = None) -> 'BlobFile':
        blob = self.blob_manager.get_blob(blob_hash, length)
        await self._update_current_blob(blob)
        if blob.get_is_verified():
            return blob

        # the blob must be downloaded
        try:
            while not self.current_blob.get_is_verified():
                if not self.active_connections:  # wait for a new connection
                    await self.new_peer_event.wait()
                    continue
                blob = await self.wait_for_download_or_new_peer()
                if blob:
                    drain_tasks(self.running_download_requests)
                    return blob
        except asyncio.CancelledError:
            drain_tasks(self.running_download_requests)

    def _add_peer_protocols(self, peers: typing.List['Peer']):
        for peer in peers:
            if peer not in self.active_connections:
                self.active_connections[peer] = BlobExchangeClientProtocol(peer, self.loop, self.peer_timeout)
                if not self.new_peer_event.is_set():
                    self.new_peer_event.set()

    async def _accumulate_connections(self, node: 'Node'):
        blob_queue = asyncio.Queue(loop=self.loop)
        blob_queue.put_nowait(self.sd_hash)
        fut = asyncio.create_task(self.got_descriptor.wait())

        def got_descriptor(f):
            try:
                f.result()
            except asyncio.CancelledError:
                return
            blob_queue.put_nowait(self.descriptor.blobs[0].blob_hash)

        fut.add_done_callback(got_descriptor)

        async with node.stream_peer_search_junction(blob_queue) as search_junction:
            async for peers in search_junction:
                self._add_peer_protocols(peers)

    def stop(self):
        log.info("stop downloader")
        cancel_task(self.accumulate_connections_task)
        cancel_task(self.download_task)
        drain_tasks(self.running_download_requests)
        while self.active_connections:
            _, protocol = self.active_connections.popitem()
            if protocol and protocol.transport:
                protocol.transport.close()
        log.info("stopped downloader")

    async def _download(self):
        log.info("accumulate connections")
        try:

            log.info("download and decrypt stream")
            await self.assemble_decrypted_stream(self.output_dir, self.output_file_name)
            log.info(
                "downloaded stream %s -> %s", self.sd_hash, self.output_path
            )
            await self.blob_manager.storage.change_file_status(
                self.descriptor.stream_hash, 'finished'
            )
        except asyncio.CancelledError:
            log.info("cancelled")
            try:
                self.stop()
            except asyncio.CancelledError:
                pass

    def download(self, node: 'Node'):
        log.info("make download task")
        self.accumulate_connections_task = self.loop.create_task(self._accumulate_connections(node))
        self.download_task = self.loop.create_task(self._download())
