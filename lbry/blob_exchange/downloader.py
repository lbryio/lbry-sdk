import asyncio
import typing
import logging
from lbry.utils import cache_concurrent
from lbry.blob_exchange.client import request_blob
if typing.TYPE_CHECKING:
    from lbry.conf import Config
    from lbry.dht.node import Node
    from lbry.dht.peer import KademliaPeer
    from lbry.blob.blob_manager import BlobManager
    from lbry.blob.blob_file import AbstractBlob
    from lbry.blob_exchange.client import BlobExchangeClientProtocol

log = logging.getLogger(__name__)


class BlobDownloader:
    BAN_FACTOR = 2.0  # fixme: when connection manager gets implemented, move it out from here

    def __init__(self, loop: asyncio.AbstractEventLoop, config: 'Config', blob_manager: 'BlobManager',
                 peer_queue: asyncio.Queue):
        self.loop = loop
        self.config = config
        self.blob_manager = blob_manager
        self.peer_queue = peer_queue
        self.active_connections: typing.Dict['KademliaPeer', asyncio.Task] = {}  # active request_blob calls
        self.ignored: typing.Dict['KademliaPeer', int] = {}
        self.scores: typing.Dict['KademliaPeer', int] = {}
        self.failures: typing.Dict['KademliaPeer', int] = {}
        self.connection_failures: typing.Set['KademliaPeer'] = set()
        self.connections: typing.Dict['KademliaPeer', 'BlobExchangeClientProtocol'] = {}
        self.is_running = asyncio.Event(loop=self.loop)

    def should_race_continue(self, blob: 'AbstractBlob'):
        max_probes = self.config.max_connections_per_download * (1 if self.connections else 10)
        if len(self.active_connections) >= max_probes:
            return False
        return not (blob.get_is_verified() or not blob.is_writeable())

    async def request_blob_from_peer(self, blob: 'AbstractBlob', peer: 'KademliaPeer', connection_id: int = 0,
                                     just_probe: bool = False):
        if blob.get_is_verified():
            return
        start = self.loop.time()
        bytes_received, protocol = await request_blob(
            self.loop, blob if not just_probe else None, peer.address, peer.tcp_port, self.config.peer_connect_timeout,
            self.config.blob_download_timeout, connected_protocol=self.connections.get(peer),
            connection_id=connection_id, connection_manager=self.blob_manager.connection_manager
        )
        if not bytes_received and not protocol and peer not in self.connection_failures:
            self.connection_failures.add(peer)
        if not protocol and peer not in self.ignored:
            self.ignored[peer] = self.loop.time()
            log.debug("drop peer %s:%i", peer.address, peer.tcp_port)
            self.failures[peer] = self.failures.get(peer, 0) + 1
            if peer in self.connections:
                del self.connections[peer]
        elif protocol:
            log.debug("keep peer %s:%i", peer.address, peer.tcp_port)
            self.failures[peer] = 0
            self.connections[peer] = protocol
            elapsed = self.loop.time() - start
            self.scores[peer] = bytes_received / elapsed if bytes_received and elapsed else 1

    async def new_peer_or_finished(self):
        active_tasks = list(self.active_connections.values()) + [asyncio.sleep(1)]
        await asyncio.wait(active_tasks, loop=self.loop, return_when='FIRST_COMPLETED')

    def cleanup_active(self):
        if not self.active_connections and not self.connections:
            self.clearbanned()
        to_remove = [peer for (peer, task) in self.active_connections.items() if task.done()]
        for peer in to_remove:
            del self.active_connections[peer]

    def clearbanned(self):
        now = self.loop.time()
        self.ignored = {
            peer: when for (peer, when) in self.ignored.items()
            if (now - when) < min(30.0, (self.failures.get(peer, 0) ** self.BAN_FACTOR))
        }

    @cache_concurrent
    async def download_blob(self, blob_hash: str, length: typing.Optional[int] = None,
                            connection_id: int = 0) -> 'AbstractBlob':
        blob = self.blob_manager.get_blob(blob_hash, length)
        if blob.get_is_verified():
            return blob
        self.is_running.set()
        try:
            while not blob.get_is_verified() and self.is_running.is_set():
                batch: typing.Set['KademliaPeer'] = set(self.connections.keys())
                while not self.peer_queue.empty():
                    batch.update(self.peer_queue.get_nowait())
                log.debug(
                    "%s running, %d peers, %d ignored, %d active, %s connections", blob_hash[:6],
                    len(batch), len(self.ignored), len(self.active_connections), len(self.connections)
                )
                re_add: typing.Set['KademliaPeer'] = set()
                for peer in sorted(batch, key=lambda peer: self.scores.get(peer, 0), reverse=True):
                    if peer in self.ignored:
                        continue
                    if peer in self.active_connections:
                        if peer not in re_add:
                            re_add.add(peer)
                        continue
                    if not self.should_race_continue(blob):
                        break
                    log.debug("request %s from %s:%i", blob_hash[:8], peer.address, peer.tcp_port)
                    t = self.loop.create_task(self.request_blob_from_peer(blob, peer, connection_id))
                    self.active_connections[peer] = t
                if not re_add:
                    self.peer_queue.put_nowait(list(batch))
                await self.new_peer_or_finished()
                self.cleanup_active()
            log.debug("downloaded %s", blob_hash[:8])
            return blob
        finally:
            blob.close()
            if self.loop.is_running():
                self.loop.call_soon(self.cleanup_active)

    def close(self):
        self.connection_failures.clear()
        self.scores.clear()
        self.ignored.clear()
        self.is_running.clear()
        for protocol in self.connections.values():
            protocol.close()


async def download_blob(loop, config: 'Config', blob_manager: 'BlobManager', node: 'Node',
                        blob_hash: str) -> 'AbstractBlob':
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
