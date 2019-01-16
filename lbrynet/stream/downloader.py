import os
import asyncio
import typing
import logging
from lbrynet import conf
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
                 peer_timeout: float, peer_connect_timeout: float, output_dir: typing.Optional[str] = None,
                 output_file_name: typing.Optional[str] = None,
                 fixed_peers: typing.Optional[typing.List['Peer']] = None):
        super().__init__(loop, blob_manager, sd_hash)
        self.peer_timeout = peer_timeout
        self.peer_connect_timeout = peer_connect_timeout
        self.current_blob: 'BlobFile' = None

        self.download_task: asyncio.Task = None
        self.accumulate_connections_task: asyncio.Task = None
        self.new_peer_event = asyncio.Event(loop=self.loop)
        self.active_connections: typing.Dict['Peer', BlobExchangeClientProtocol] = {}
        self.running_download_requests: typing.List[asyncio.Task] = []
        self.requested_from: typing.Dict[str, typing.Dict['Peer', asyncio.Task]] = {}
        self.output_dir = output_dir or os.getcwd()
        self.output_file_name = output_file_name
        self._lock = asyncio.Lock(loop=self.loop)
        self.max_connections_per_stream = conf.settings['max_connections_per_stream']
        self.fixed_peers = fixed_peers or []

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
        if peer not in self.active_connections:
            log.warning("not active, adding: %s", str(peer))
            self.active_connections[peer] = BlobExchangeClientProtocol(peer, self.loop, self.peer_timeout)
        log.info("request %s from %s:%i", self.current_blob.blob_hash[:8], peer.address, peer.tcp_port)
        success = await peer.request_blob(self.current_blob, self.active_connections[peer],
                                          self.peer_connect_timeout)
        if not success:
            log.warning("failed to download %s from %s:%i", self.current_blob.blob_hash[:8], peer.address,
                        peer.tcp_port)
            if peer.tcp_last_down is not None:
                async with self._lock:
                    proto = self.active_connections.pop(peer, None)
                    if proto and proto.transport:
                        proto.transport.close()

    def _update_requests(self):
        log.info("clear peer event")
        self.new_peer_event.clear()
        if self.current_blob.blob_hash not in self.requested_from:
            self.requested_from[self.current_blob.blob_hash] = {}
        to_add = []
        for peer in self.active_connections.keys():
            if peer not in self.requested_from[self.current_blob.blob_hash] and peer not in to_add:
                to_add.append(peer)
        log.info("adding requests for %i peers (%i active)", min(len(to_add), 8 - len(self.running_download_requests)),
                 len(self.running_download_requests))
        for peer in to_add:
            if len(self.running_download_requests) >= 8:
                break
            task = self.loop.create_task(self._request_blob(peer))
            self.requested_from[self.current_blob.blob_hash][peer] = task
            self.running_download_requests.append(task)

    async def wait_for_download_or_new_peer(self) -> typing.Optional['BlobFile']:
        async with self._lock:
            if len(self.running_download_requests) < self.max_connections_per_stream:
                # update the running download requests
                self._update_requests()

            # drain the tasks into a temporary list
            download_tasks = []
            drain_into(self.running_download_requests, download_tasks)

        got_new_peer = self.loop.create_task(self.new_peer_event.wait())

        # wait for a new peer to be added or for a download attempt to finish
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
            return blob
        except asyncio.CancelledError:
            drain_tasks(self.running_download_requests)
            raise

    def _add_peer_protocols(self, peers: typing.List['Peer']):
        added = 0
        for peer in peers:
            if peer not in self.active_connections:
                self.active_connections[peer] = BlobExchangeClientProtocol(peer, self.loop, self.peer_timeout)
                added += 1
        if added:
            log.info("added %i new peers", len(peers))
            if not self.new_peer_event.is_set():
                log.info("set new peer event")
                self.new_peer_event.set()

    async def _accumulate_connections(self, node: 'Node'):
        blob_queue = asyncio.Queue(loop=self.loop)
        blob_queue.put_nowait(self.sd_hash)
        task = asyncio.create_task(self.got_descriptor.wait())
        added_peers = asyncio.Event(loop=self.loop)
        add_fixed_peers_timer: typing.Optional[asyncio.Handle] = None

        if self.fixed_peers:
            def check_added_peers():
                if not added_peers.is_set():
                    self._add_peer_protocols(self.fixed_peers)
                    log.info("no dht peers for download yet, adding fixed peer")
                    added_peers.set()

            add_fixed_peers_timer = self.loop.call_later(2, check_added_peers)

        def got_descriptor(f):
            try:
                f.result()
            except asyncio.CancelledError:
                return
            log.info("add head blob hash to peer search")
            blob_queue.put_nowait(self.descriptor.blobs[0].blob_hash)

        task.add_done_callback(got_descriptor)
        try:
            async with node.stream_peer_search_junction(blob_queue) as search_junction:
                log.info("got search junction")
                async for peers in search_junction:
                    if not isinstance(peers, list):  # TODO: what's up with this?
                        log.error("not a list: %s", peers)
                    else:
                        # log.info("add %i peers to download of stream %s", len(peers), self.sd_hash[:8])
                        self._add_peer_protocols(peers)
                        if not added_peers.is_set():
                            added_peers.set()
            return
        finally:
            if task and not task.done():
                task.cancel()
                log.info("cancelled head blob task")
            if add_fixed_peers_timer and not add_fixed_peers_timer.cancelled():
                add_fixed_peers_timer.cancel()

    async def stop(self):
        log.info("stop downloader")
        cancel_task(self.accumulate_connections_task)
        cancel_task(self.download_task)
        drain_tasks(self.running_download_requests)

        while self.requested_from:
            _, peer_task_dict = self.requested_from.popitem()
            while peer_task_dict:
                peer, task = peer_task_dict.popitem()
                try:
                    cancel_task(task)
                except asyncio.CancelledError:
                    pass

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
            await self.stop()
            raise

    def download(self, node: 'Node'):
        log.info("make download task")
        self.accumulate_connections_task = self.loop.create_task(self._accumulate_connections(node))
        self.download_task = self.loop.create_task(self._download())
