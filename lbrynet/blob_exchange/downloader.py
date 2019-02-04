import asyncio
import typing
import logging
from lbrynet.utils import drain_tasks
from lbrynet.blob_exchange.client import request_blob
if typing.TYPE_CHECKING:
    from lbrynet.conf import Config
    from lbrynet.dht.node import Node
    from lbrynet.dht.peer import KademliaPeer
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.blob.blob_file import BlobFile

log = logging.getLogger(__name__)


def drain_into(a: list, b: list):
    while a:
        b.append(a.pop())


class BlobDownloader:
    def __init__(self, loop: asyncio.BaseEventLoop, config: 'Config', blob_manager: 'BlobFileManager',
                 peer_queue: asyncio.Queue):
        self.loop = loop
        self.config = config
        self.blob_manager = blob_manager
        self.peer_queue = peer_queue
        self.active_connections: typing.Dict['KademliaPeer', asyncio.Task] = {}  # active request_blob calls
        self.ignored: typing.Set['KademliaPeer'] = set()
        self.scores: typing.Dict['KademliaPeer', int] = {}

    async def request_blob_from_peer(self, blob: 'BlobFile', peer: 'KademliaPeer'):
        if blob.get_is_verified():
            return
        success, keep_connection = await request_blob(
            self.loop, blob, peer.address, peer.tcp_port, self.config.peer_connect_timeout,
            self.config.blob_download_timeout
        )
        if not keep_connection and peer not in self.ignored:
            self.ignored.add(peer)
            log.debug("drop peer %s:%i", peer.address, peer.tcp_port)
        elif keep_connection:
            log.debug("keep peer %s:%i", peer.address, peer.tcp_port)
        if success:
            self.scores[peer] = self.scores.get(peer, 0) + 2
        else:
            self.scores[peer] = self.scores.get(peer, 0) - 1

    async def new_peer_or_finished(self, blob: 'BlobFile'):
        async def get_and_re_add_peers():
            new_peers = await self.peer_queue.get()
            self.peer_queue.put_nowait(new_peers)
        tasks = [self.loop.create_task(get_and_re_add_peers()), self.loop.create_task(blob.verified.wait())]
        try:
            await asyncio.wait(tasks, loop=self.loop, return_when='FIRST_COMPLETED')
        except asyncio.CancelledError:
            drain_tasks(tasks)
            raise

    async def download_blob(self, blob_hash: str, length: typing.Optional[int] = None) -> 'BlobFile':
        blob = self.blob_manager.get_blob(blob_hash, length)
        if blob.get_is_verified():
            return blob
        try:
            while not blob.get_is_verified():
                batch: typing.List['KademliaPeer'] = []
                while not self.peer_queue.empty():
                    batch.extend(await self.peer_queue.get())
                for peer in batch:
                    if len(self.active_connections) >= self.config.max_connections_per_download:
                        break
                    if peer not in self.active_connections and peer not in self.ignored:
                        log.debug("request %s from %s:%i", blob_hash[:8], peer.address, peer.tcp_port)
                        t = self.loop.create_task(self.request_blob_from_peer(blob, peer))
                        self.active_connections[peer] = t
                        t.add_done_callback(
                            lambda _:
                            None if peer not in self.active_connections else self.active_connections.pop(peer)
                        )
                await self.new_peer_or_finished(blob)
                to_re_add = list(set(filter(lambda peer: peer not in self.ignored, batch)))
                to_re_add.sort(key=lambda peer: self.scores.get(peer, 0), reverse=True)
                if to_re_add:
                    self.peer_queue.put_nowait(to_re_add)
            while self.active_connections:
                peer, task = self.active_connections.popitem()
                if task and not task.done():
                    task.cancel()
            await blob.close()
            log.debug("downloaded %s", blob_hash[:8])
            return blob
        except asyncio.CancelledError:
            while self.active_connections:
                peer, task = self.active_connections.popitem()
                if task and not task.done():
                    task.cancel()
            raise


async def download_blob(loop, config: 'Config', blob_manager: 'BlobFileManager', node: 'Node',
                        blob_hash: str) -> 'BlobFile':
    search_queue = asyncio.Queue(loop=loop, maxsize=config.max_connections_per_download)
    search_queue.put_nowait(blob_hash)
    peer_queue, accumulate_task = node.accumulate_peers(search_queue)
    downloader = BlobDownloader(loop, config, blob_manager, peer_queue)
    try:
        return await downloader.download_blob(blob_hash)
    finally:
        if accumulate_task and not accumulate_task.done():
            accumulate_task.cancel()
