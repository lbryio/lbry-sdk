import asyncio
import typing
import logging
if typing.TYPE_CHECKING:
    from lbrynet.dht.node import Node
    from lbrynet.extras.daemon.storage import SQLiteStorage

log = logging.getLogger(__name__)


class BlobAnnouncer:
    def __init__(self, loop: asyncio.BaseEventLoop, node: 'Node', storage: 'SQLiteStorage'):
        self.loop = loop
        self.node = node
        self.storage = storage
        self.announce_task: asyncio.Task = None
        self.announce_queue: typing.List[str] = []

    async def _submit_announcement(self, blob_hash):
        try:
            peers = len(await self.node.announce_blob(blob_hash))
            if peers > 4:
                return blob_hash
            else:
                log.warning("failed to announce %s, could only find %d peers, retrying soon.", blob_hash[:8], peers)
        except Exception as err:
            log.warning("error announcing %s: %s", blob_hash[:8], str(err))


    async def _announce(self, batch_size: typing.Optional[int] = 10):
        while batch_size:
            if not self.node.joined.is_set():
                await self.node.joined.wait()
            self.announce_queue.extend(await self.storage.get_blobs_to_announce())
            log.debug("announcer task wake up, %d blobs to announce", len(self.announce_queue))
            while len(self.announce_queue):
                log.info("%i blobs to announce", len(self.announce_queue))
                announced = await asyncio.gather(*[
                    self._submit_announcement(
                        self.announce_queue.pop()) for _ in range(batch_size) if self.announce_queue
                ], loop=self.loop)
                announced = list(filter(None, announced))
                if announced:
                    await self.storage.update_last_announced_blobs(announced)
                    log.info("announced %i blobs", len(announced))
            await asyncio.sleep(60)

    def start(self, batch_size: typing.Optional[int] = 10):
        assert not self.announce_task or self.announce_task.done(), "already running"
        self.announce_task = self.loop.create_task(self._announce(batch_size))

    def stop(self):
        if self.announce_task and not self.announce_task.done():
            self.announce_task.cancel()
