import asyncio
import typing
import logging
if typing.TYPE_CHECKING:
    from lbrynet.dht.node import Node
    from lbrynet.storage import SQLiteStorage

log = logging.getLogger(__name__)


class BlobAnnouncer:
    def __init__(self, loop: asyncio.BaseEventLoop, node: 'Node', storage: 'SQLiteStorage'):
        self.loop = loop
        self.node = node
        self.storage = storage
        self.pending_call: asyncio.Handle = None
        self.announce_task: asyncio.Task = None
        self.running = False
        self.announce_queue: typing.List[str] = []

    async def _announce(self, batch_size: typing.Optional[int] = 10):
        if not self.node.joined.is_set():
            await self.node.joined.wait()
        blob_hashes = await self.storage.get_blobs_to_announce()
        if blob_hashes:
            self.announce_queue.extend(blob_hashes)
            log.info("%i blobs to announce", len(blob_hashes))
        batch = []
        while len(self.announce_queue):
            cnt = 0
            announced = []
            while self.announce_queue and cnt < batch_size:
                blob_hash = self.announce_queue.pop()
                announced.append(blob_hash)
                batch.append(self.node.announce_blob(blob_hash))
                cnt += 1
            to_await = []
            while batch:
                to_await.append(batch.pop())
            if to_await:
                await asyncio.gather(*tuple(to_await), loop=self.loop)
                await self.storage.update_last_announced_blobs(announced, self.loop.time())
                log.info("announced %i blobs", len(announced))
        if self.running:
            self.pending_call = self.loop.call_later(60, self.announce, batch_size)

    def announce(self, batch_size: typing.Optional[int] = 10):
        self.announce_task = self.loop.create_task(self._announce(batch_size))

    def start(self):
        if self.running:
            raise Exception("already running")
        self.running = True
        self.announce()

    def stop(self):
        self.running = False
        if self.pending_call:
            if not self.pending_call.cancelled():
                self.pending_call.cancel()
            self.pending_call = None
        if self.announce_task:
            if not (self.announce_task.done() or self.announce_task.cancelled()):
                self.announce_task.cancel()
                self.announce_task = None
