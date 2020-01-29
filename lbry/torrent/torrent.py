import asyncio
import logging
import typing


log = logging.getLogger(__name__)


class TorrentInfo:
    __slots__ = ('dht_seeds', 'http_seeds', 'trackers', 'total_size')

    def __init__(self, dht_seeds: typing.Tuple[typing.Tuple[str, int]],
                 http_seeds: typing.Tuple[typing.Dict[str, typing.Any]],
                 trackers: typing.Tuple[typing.Tuple[str, int]], total_size: int):
        self.dht_seeds = dht_seeds
        self.http_seeds = http_seeds
        self.trackers = trackers
        self.total_size = total_size

    @classmethod
    def from_libtorrent_info(cls, torrent_info):
        return cls(
            torrent_info.nodes(), tuple(
                {
                    'url': web_seed['url'],
                    'type': web_seed['type'],
                    'auth': web_seed['auth']
                } for web_seed in torrent_info.web_seeds()
            ), tuple(
                (tracker.url, tracker.tier) for tracker in torrent_info.trackers()
            ), torrent_info.total_size()
        )


class Torrent:
    def __init__(self, loop, handle):
        self._loop = loop
        self._handle = handle
        self.finished = asyncio.Event(loop=loop)

    def _threaded_update_status(self):
        status = self._handle.status()
        if not status.is_seeding:
            log.info(
                '%.2f%% complete (down: %.1f kB/s up: %.1f kB/s peers: %d) %s',
                status.progress * 100, status.download_rate / 1000, status.upload_rate / 1000,
                status.num_peers, status.state
            )
        elif not self.finished.is_set():
            self.finished.set()

    async def wait_for_finished(self):
        while True:
            await self._loop.run_in_executor(
                None, self._threaded_update_status
            )
            if self.finished.is_set():
                log.info("finished downloading torrent!")
                await self.pause()
                break
            await asyncio.sleep(1, loop=self._loop)

    async def pause(self):
        log.info("pause torrent")
        await self._loop.run_in_executor(
            None, self._handle.pause
        )

    async def resume(self):
        await self._loop.run_in_executor(
            None, self._handle.resume
        )
