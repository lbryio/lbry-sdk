import asyncio
import typing
import logging

from prometheus_client import Counter, Gauge

if typing.TYPE_CHECKING:
    from lbry.dht.node import Node
    from lbry.extras.daemon.storage import SQLiteStorage

log = logging.getLogger(__name__)


class BlobAnnouncer:
    announcements_sent_metric = Counter(
        "announcements_sent", "Number of announcements sent and their respective status.", namespace="dht_node",
        labelnames=("peers", "error"),
    )
    announcement_queue_size_metric = Gauge(
        "announcement_queue_size", "Number of hashes waiting to be announced.", namespace="dht_node",
        labelnames=("scope",)
    )

    def __init__(self, loop: asyncio.AbstractEventLoop, node: 'Node', storage: 'SQLiteStorage'):
        self.loop = loop
        self.node = node
        self.storage = storage
        self.announce_task: asyncio.Task = None
        self.announce_queue: typing.List[str] = []
        self._done = asyncio.Event()
        self.announced = set()

    async def _run_consumer(self):
        while self.announce_queue:
            try:
                blob_hash = self.announce_queue.pop()
                peers = len(await self.node.announce_blob(blob_hash))
                self.announcements_sent_metric.labels(peers=peers, error=False).inc()
                if peers > 4:
                    self.announced.add(blob_hash)
                else:
                    log.debug("failed to announce %s, could only find %d peers, retrying soon.", blob_hash[:8], peers)
            except Exception as err:
                self.announcements_sent_metric.labels(peers=0, error=True).inc()
                log.warning("error announcing %s: %s", blob_hash[:8], str(err))

    async def _announce(self, batch_size: typing.Optional[int] = 10):
        while batch_size:
            if not self.node.joined.is_set():
                await self.node.joined.wait()
            await asyncio.sleep(60)
            if not self.node.protocol.routing_table.get_peers():
                log.warning("No peers in DHT, announce round skipped")
                continue
            self.announce_queue.extend(await self.storage.get_blobs_to_announce())
            self.announcement_queue_size_metric.labels(scope="global").set(len(self.announce_queue))
            log.debug("announcer task wake up, %d blobs to announce", len(self.announce_queue))
            while len(self.announce_queue) > 0:
                log.info("%i blobs to announce", len(self.announce_queue))
                await asyncio.gather(*[self._run_consumer() for _ in range(batch_size)])
                announced = list(filter(None, self.announced))
                if announced:
                    await self.storage.update_last_announced_blobs(announced)
                    log.info("announced %i blobs", len(announced))
                    self.announced.clear()
            self._done.set()
            self._done.clear()

    def start(self, batch_size: typing.Optional[int] = 10):
        assert not self.announce_task or self.announce_task.done(), "already running"
        self.announce_task = self.loop.create_task(self._announce(batch_size))

    def stop(self):
        if self.announce_task and not self.announce_task.done():
            self.announce_task.cancel()

    def wait(self):
        return self._done.wait()
