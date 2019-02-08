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
        self.connections: typing.Dict['KademliaPeer', asyncio.Transport] = {}
        self.rounds_won: typing.Dict['KademliaPeer', int] = {}

    def should_race_continue(self):
        if len(self.active_connections) >= self.config.max_connections_per_download:
            return False
        # if a peer won 3 or more blob races and is active as a downloader, stop the race so bandwidth improves
        # the safe net side is that any failure will reset the peer score, triggering the race back
        for peer, task in self.active_connections.items():
            if self.scores.get(peer, 0) >= 0 and self.rounds_won.get(peer, 0) >= 3 and not task.done():
                return False
        return True

    async def request_blob_from_peer(self, blob: 'BlobFile', peer: 'KademliaPeer'):
        if blob.get_is_verified():
            return
        self.scores[peer] = self.scores.get(peer, 0) - 1  # starts losing score, to account for cancelled ones
        transport = self.connections.get(peer)
        start = self.loop.time()
        bytes_received, transport = await request_blob(
            self.loop, blob, peer.address, peer.tcp_port, self.config.peer_connect_timeout,
            self.config.blob_download_timeout, connected_transport=transport
        )
        if bytes_received == blob.get_length():
            self.rounds_won[peer] = self.rounds_won.get(peer, 0) + 1
        if not transport and peer not in self.ignored:
            self.ignored.add(peer)
            log.debug("drop peer %s:%i", peer.address, peer.tcp_port)
            if peer in self.connections:
                del self.connections[peer]
        elif transport:
            log.debug("keep peer %s:%i", peer.address, peer.tcp_port)
            self.connections[peer] = transport
        rough_speed = (bytes_received / (self.loop.time() - start)) if bytes_received else 0
        self.scores[peer] = rough_speed

    async def new_peer_or_finished(self, blob: 'BlobFile'):
        async def get_and_re_add_peers():
            new_peers = await self.peer_queue.get()
            self.peer_queue.put_nowait(new_peers)
        tasks = [self.loop.create_task(get_and_re_add_peers()), self.loop.create_task(blob.verified.wait())]
        active_tasks = list(self.active_connections.values())
        try:
            await asyncio.wait(tasks + active_tasks, loop=self.loop, return_when='FIRST_COMPLETED')
        finally:
            drain_tasks(tasks)

    def cleanup_active(self):
        to_remove = [peer for (peer, task) in self.active_connections.items() if task.done()]
        for peer in to_remove:
            del self.active_connections[peer]

    async def download_blob(self, blob_hash: str, length: typing.Optional[int] = None) -> 'BlobFile':
        blob = self.blob_manager.get_blob(blob_hash, length)
        if blob.get_is_verified():
            return blob
        try:
            while not blob.get_is_verified():
                batch: typing.List['KademliaPeer'] = []
                while not self.peer_queue.empty():
                    batch.extend(self.peer_queue.get_nowait())
                batch.sort(key=lambda peer: self.scores.get(peer, 0), reverse=True)
                log.debug(
                    "running, %d peers, %d ignored, %d active",
                    len(batch), len(self.ignored), len(self.active_connections)
                )
                for peer in batch:
                    if not self.should_race_continue():
                        break
                    if peer not in self.active_connections and peer not in self.ignored:
                        log.debug("request %s from %s:%i", blob_hash[:8], peer.address, peer.tcp_port)
                        t = self.loop.create_task(self.request_blob_from_peer(blob, peer))
                        self.active_connections[peer] = t
                await self.new_peer_or_finished(blob)
                self.cleanup_active()
                if batch:
                    self.peer_queue.put_nowait(set(batch).difference(self.ignored))
            while self.active_connections:
                peer, task = self.active_connections.popitem()
                if task and not task.done():
                    task.cancel()
            blob.close()
            log.debug("downloaded %s", blob_hash[:8])
            return blob
        except asyncio.CancelledError:
            while self.active_connections:
                peer, task = self.active_connections.popitem()
                if task and not task.done():
                    task.cancel()
            raise
        except (OSError, Exception) as e:
            log.exception(e)
            raise e

    def close(self):
        for transport in self.connections.values():
            transport.close()


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
        downloader.close()
