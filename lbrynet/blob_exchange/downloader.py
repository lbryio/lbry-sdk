import asyncio
import typing
import logging
from lbrynet import conf
from lbrynet.utils import drain_tasks
from lbrynet.blob_exchange.client import BlobExchangeClientProtocol, request_blob
if typing.TYPE_CHECKING:
    from lbrynet.dht.node import Node
    from lbrynet.dht.peer import KademliaPeer
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.blob.blob_file import BlobFile

log = logging.getLogger(__name__)


def drain_into(a: list, b: list):
    while a:
        b.append(a.pop())


class BlobDownloader:  # TODO: refactor to be the base class used by StreamDownloader
    """A single blob downloader"""
    def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: 'BlobFileManager', config: conf.Config):
        self.loop = loop
        self.blob_manager = blob_manager
        self.new_peer_event = asyncio.Event(loop=self.loop)
        self.active_connections: typing.Dict['KademliaPeer', BlobExchangeClientProtocol] = {}
        self.running_download_requests: typing.List[asyncio.Task] = []
        self.requested_from: typing.Dict[str, typing.Dict['KademliaPeer', asyncio.Task]] = {}
        self.lock = asyncio.Lock(loop=self.loop)
        self.blob: 'BlobFile' = None
        self.blob_queue = asyncio.Queue(loop=self.loop)

        self.blob_download_timeout = config.blob_download_timeout
        self.peer_connect_timeout = config.peer_connect_timeout
        self.max_connections = config.max_connections_per_download

    async def _request_blob(self, peer: 'KademliaPeer'):
        if self.blob.get_is_verified():
            log.info("already verified")
            return
        if peer not in self.active_connections:
            log.warning("not active, adding: %s", str(peer))
            self.active_connections[peer] = BlobExchangeClientProtocol(self.loop, self.blob_download_timeout)
        protocol = self.active_connections[peer]
        success, keep_connection = await request_blob(self.loop, self.blob, protocol, peer.address, peer.tcp_port,
                                                      self.peer_connect_timeout)
        await protocol.close()
        if not keep_connection:
            log.info("drop peer %s:%i", peer.address, peer.tcp_port)
            if peer in self.active_connections:
                async with self.lock:
                    del self.active_connections[peer]
            return
        log.info("keep peer %s:%i", peer.address, peer.tcp_port)

    def _update_requests(self):
        self.new_peer_event.clear()
        if self.blob.blob_hash not in self.requested_from:
            self.requested_from[self.blob.blob_hash] = {}
        to_add = []
        for peer in self.active_connections.keys():
            if peer not in self.requested_from[self.blob.blob_hash] and peer not in to_add:
                to_add.append(peer)
        if to_add or self.running_download_requests:
            log.info("adding download probes for %i peers to %i already active",
                     min(len(to_add), 8 - len(self.running_download_requests)),
                     len(self.running_download_requests))
        else:
            log.info("downloader idle...")
        for peer in to_add:
            if len(self.running_download_requests) >= 8:
                break
            task = self.loop.create_task(self._request_blob(peer))
            self.requested_from[self.blob.blob_hash][peer] = task
            self.running_download_requests.append(task)

    def _add_peer_protocols(self, peers: typing.List['KademliaPeer']):
        added = 0
        for peer in peers:
            if peer not in self.active_connections:
                self.active_connections[peer] = BlobExchangeClientProtocol(self.loop, self.blob_download_timeout)
                added += 1
        if added:
            if not self.new_peer_event.is_set():
                log.info("added %i new peers", len(peers))
                self.new_peer_event.set()

    async def _accumulate_connections(self, node: 'Node'):
        try:
            async with node.stream_peer_search_junction(self.blob_queue) as search_junction:
                async for peers in search_junction:
                    if not isinstance(peers, list):  # TODO: what's up with this?
                        log.error("not a list: %s %s", peers, str(type(peers)))
                    else:
                        self._add_peer_protocols(peers)
            return
        except asyncio.CancelledError:
            pass

    async def get_blob(self, blob_hash: str, node: 'Node') -> 'BlobFile':
        self.blob = self.blob_manager.get_blob(blob_hash)
        if self.blob.get_is_verified():
            return self.blob
        accumulator = self.loop.create_task(self._accumulate_connections(node))
        self.blob_queue.put_nowait(blob_hash)
        try:
            while not self.blob.get_is_verified():
                if len(self.running_download_requests) < self.max_connections:
                    self._update_requests()

                # drain the tasks into a temporary list
                download_tasks = []
                drain_into(self.running_download_requests, download_tasks)
                got_new_peer = self.loop.create_task(self.new_peer_event.wait())

                # wait for a new peer to be added or for a download attempt to finish
                await asyncio.wait([got_new_peer] + download_tasks, return_when='FIRST_COMPLETED',
                                   loop=self.loop)
                if got_new_peer and not got_new_peer.done():
                    got_new_peer.cancel()
                if self.blob.get_is_verified():
                    if got_new_peer and not got_new_peer.done():
                        got_new_peer.cancel()
                    drain_tasks(download_tasks)
                    return self.blob
        except asyncio.CancelledError:
            drain_tasks(self.running_download_requests)
            raise
        finally:
            if accumulator and not accumulator.done():
                accumulator.cancel()
