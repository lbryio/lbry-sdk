import asyncio
import binascii
import os
import logging
import random
from hashlib import sha1
from tempfile import mkdtemp
from typing import Optional, Tuple

import libtorrent


log = logging.getLogger(__name__)
DEFAULT_FLAGS = (  # fixme: somehow the logic here is inverted?
        libtorrent.add_torrent_params_flags_t.flag_auto_managed
        | libtorrent.add_torrent_params_flags_t.flag_update_subscribe
        | libtorrent.add_torrent_params_flags_t.flag_sequential_download
        | libtorrent.add_torrent_params_flags_t.flag_paused
)


class TorrentHandle:
    def __init__(self, loop, executor, handle):
        self._loop = loop
        self._executor = executor
        self._handle: libtorrent.torrent_handle = handle
        self.started = asyncio.Event(loop=loop)
        self.finished = asyncio.Event(loop=loop)
        self.metadata_completed = asyncio.Event(loop=loop)
        self.size = 0
        self.total_wanted_done = 0
        self.name = ''
        self.tasks = []
        self._torrent_info: libtorrent.torrent_info = handle.torrent_file()
        self._base_path = None

    @property
    def torrent_file(self) -> Optional[libtorrent.file_storage]:
        return self._torrent_info.files()

    @property
    def largest_file(self) -> Optional[str]:
        if self.torrent_file is None:
            return None
        index = self.largest_file_index
        return os.path.join(self._base_path, self.torrent_file.file_path(index))

    @property
    def save_path(self) -> Optional[str]:
        return self._base_path

    @property
    def largest_file_index(self):
        largest_size, index = 0, 0
        for file_num in range(self.torrent_file.num_files()):
            if self.torrent_file.file_size(file_num) > largest_size:
                largest_size = self.torrent_file.file_size(file_num)
                index = file_num
        return index

    def stop_tasks(self):
        while self.tasks:
            self.tasks.pop().cancel()

    def byte_range_to_piece_range(
            self, file_index, start_offset, end_offset) -> Tuple[libtorrent.peer_request, libtorrent.peer_request]:
        start_piece = self._torrent_info.map_file(file_index, start_offset, 0)
        end_piece = self._torrent_info.map_file(file_index, end_offset, 0)
        return start_piece, end_piece

    async def stream_range_as_completed(self, file_index, start, end):
        first_piece, final_piece = self.byte_range_to_piece_range(file_index, start, end)
        start_piece_offset = final_piece.start
        piece_size = self._torrent_info.piece_length()
        log.info("Streaming torrent from piece %d to %d (bytes: %d -> %d): %s",
                 first_piece.piece, final_piece.piece, start, end, self.name)
        self.prioritize(file_index, start, end)
        await self.resume()
        for piece_index in range(first_piece.piece, final_piece.piece + 1):
            while not self._handle.have_piece(piece_index):
                log.info("Waiting for piece %d: %s", piece_index, self.name)
                self._handle.set_piece_deadline(piece_index, 0)
                await asyncio.sleep(0.2)
            log.info("Streaming piece offset %d / %d for torrent %s", piece_index, final_piece.piece, self.name)
            yield piece_size - start_piece_offset

    def _show_status(self):
        # fixme: cleanup
        if not self._handle.is_valid():
            return
        status = self._handle.status()
        if status.has_metadata:
            self.size = status.total_wanted
            self.total_wanted_done = status.total_wanted_done
            self.name = status.name
            if not self.metadata_completed.is_set():
                self.metadata_completed.set()
                self._torrent_info = self._handle.torrent_file()
                log.info("Metadata completed for btih:%s - %s", status.info_hash, self.name)
                # prioritize first 2mb
                self.prioritize(self.largest_file_index, 0, 2 * 1024 * 1024)
                self._base_path = status.save_path
            first_piece = self.torrent_file.piece_index_at_file(self.largest_file_index)
            if not self.started.is_set():
                if self._handle.have_piece(first_piece):
                    log.debug("Got first piece, set started - %s", self.name)
                    self.started.set()
        log.debug('%.2f%% complete (down: %.1f kB/s up: %.1f kB/s peers: %d seeds: %d) %s - %s',
                  status.progress * 100, status.download_rate / 1000, status.upload_rate / 1000,
                  status.num_peers, status.num_seeds, status.state, status.save_path)
        if (status.is_finished or status.is_seeding) and not self.finished.is_set():
            self.finished.set()
            log.info("Torrent finished: %s", self.name)

    def prioritize(self, file_index, start, end, cleanup=False):
        first_piece, last_piece = self.byte_range_to_piece_range(file_index, start, end)
        priorities = self._handle.get_piece_priorities()
        priorities = [0 if cleanup else 1 for _ in priorities]
        self._handle.clear_piece_deadlines()
        for idx, piece_number in enumerate(range(first_piece.piece, last_piece.piece + 1)):
            priorities[piece_number] = 7 - idx if 0 <= idx <= 6 else 1
            self._handle.set_piece_deadline(piece_number, idx)
        log.debug("Prioritizing pieces for %s: %s", self.name, priorities)
        self._handle.prioritize_pieces(priorities)

    async def status_loop(self):
        while True:
            self._show_status()
            if self.finished.is_set():
                break
            await asyncio.sleep(0.1)

    async def pause(self):
        await self._loop.run_in_executor(
            self._executor, self._handle.pause
        )

    async def resume(self):
        await self._loop.run_in_executor(
            self._executor, lambda: self._handle.resume()  # pylint: disable=unnecessary-lambda
        )


class TorrentSession:
    def __init__(self, loop, executor):
        self._loop = loop
        self._executor = executor
        self._session: Optional[libtorrent.session] = None
        self._handles = {}
        self.tasks = []
        self.wait_start = True

    async def add_fake_torrent(self):
        tmpdir = mkdtemp()
        info, btih = _create_fake_torrent(tmpdir)
        flags = libtorrent.add_torrent_params_flags_t.flag_seed_mode
        handle = self._session.add_torrent({
            'ti': info, 'save_path': tmpdir, 'flags': flags
        })
        self._handles[btih] = TorrentHandle(self._loop, self._executor, handle)
        return btih

    async def bind(self, interface: str = '0.0.0.0', port: int = 10889):
        settings = {
            'listen_interfaces': f"{interface}:{port}",
            'enable_natpmp': False,
            'enable_upnp': False
        }
        self._session = await self._loop.run_in_executor(
            self._executor, libtorrent.session, settings  # pylint: disable=c-extension-no-member
        )
        self.tasks.append(self._loop.create_task(self.process_alerts()))

    def stop(self):
        while self.tasks:
            self.tasks.pop().cancel()
        self._session.save_state()
        self._session.pause()
        self._session.stop_dht()
        self._session.stop_lsd()
        self._session.stop_natpmp()
        self._session.stop_upnp()
        self._session = None

    def _pop_alerts(self):
        for alert in self._session.pop_alerts():
            log.info("torrent alert: %s", alert)

    async def process_alerts(self):
        while True:
            await self._loop.run_in_executor(
                self._executor, self._pop_alerts
            )
            await asyncio.sleep(1)

    async def pause(self):
        await self._loop.run_in_executor(
            self._executor, lambda: self._session.save_state()  # pylint: disable=unnecessary-lambda
        )
        await self._loop.run_in_executor(
            self._executor, lambda: self._session.pause()  # pylint: disable=unnecessary-lambda
        )

    async def resume(self):
        await self._loop.run_in_executor(
            self._executor, self._session.resume
        )

    def _add_torrent(self, btih: str, download_directory: Optional[str]):
        params = {'info_hash': binascii.unhexlify(btih.encode()), 'flags': DEFAULT_FLAGS}
        if download_directory:
            params['save_path'] = download_directory
        handle = self._session.add_torrent(params)
        handle.force_dht_announce()
        self._handles[btih] = TorrentHandle(self._loop, self._executor, handle)

    def full_path(self, btih):
        return self._handles[btih].largest_file

    def save_path(self, btih):
        return self._handles[btih].save_path

    async def add_torrent(self, btih, download_path):
        await self._loop.run_in_executor(
            self._executor, self._add_torrent, btih, download_path
        )
        self._handles[btih].tasks.append(self._loop.create_task(self._handles[btih].status_loop()))
        await self._handles[btih].metadata_completed.wait()
        if self.wait_start:
            # fixme: temporary until we add streaming support, otherwise playback fails!
            await self._handles[btih].started.wait()

    def remove_torrent(self, btih, remove_files=False):
        if btih in self._handles:
            handle = self._handles[btih]
            handle.stop_tasks()
            self._session.remove_torrent(handle._handle, 1 if remove_files else 0)
            self._handles.pop(btih)

    async def save_file(self, btih, download_directory):
        handle = self._handles[btih]
        await handle.resume()

    def get_size(self, btih):
        return self._handles[btih].size

    def get_name(self, btih):
        return self._handles[btih].name

    def get_downloaded(self, btih):
        return self._handles[btih].total_wanted_done

    def is_completed(self, btih):
        return self._handles[btih].finished.is_set()

    def stream_largest_file(self, btih, start, end):
        handle = self._handles[btih]
        return handle.stream_range_as_completed(handle.largest_file_index, start, end)


def get_magnet_uri(btih):
    return f"magnet:?xt=urn:btih:{btih}"


def _create_fake_torrent(tmpdir):
    # beware, that's just for testing
    path = os.path.join(tmpdir, 'tmp')
    with open(path, 'wb') as myfile:
        size = myfile.write(bytes([random.randint(0, 255) for _ in range(40)]) * 1024)
    file_storage = libtorrent.file_storage()
    file_storage.add_file('tmp', size)
    t = libtorrent.create_torrent(file_storage, 0, 4 * 1024 * 1024)
    libtorrent.set_piece_hashes(t, tmpdir)
    info = libtorrent.torrent_info(t.generate())
    btih = sha1(info.metadata()).hexdigest()
    return info, btih


async def main():
    if os.path.exists("~/Downloads/ubuntu-18.04.3-live-server-amd64.torrent"):
        os.remove("~/Downloads/ubuntu-18.04.3-live-server-amd64.torrent")
    if os.path.exists("~/Downloads/ubuntu-18.04.3-live-server-amd64.iso"):
        os.remove("~/Downloads/ubuntu-18.04.3-live-server-amd64.iso")

    btih = "dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c"

    executor = None
    session = TorrentSession(asyncio.get_event_loop(), executor)
    await session.bind()
    await session.add_torrent(btih, os.path.expanduser("~/Downloads"))
    while True:
        session.full_path(btih)
        await asyncio.sleep(1)
    await session.pause()
    executor.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)-4s %(name)s:%(lineno)d: %(message)s")
    log = logging.getLogger(__name__)
    asyncio.run(main())
