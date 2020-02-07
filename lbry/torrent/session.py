import asyncio
import binascii
import os
from hashlib import sha1
from tempfile import mkdtemp
from typing import Optional

import libtorrent


NOTIFICATION_MASKS = [
    "error",
    "peer",
    "port_mapping",
    "storage",
    "tracker",
    "debug",
    "status",
    "progress",
    "ip_block",
    "dht",
    "stats",
    "session_log",
    "torrent_log",
    "peer_log",
    "incoming_request",
    "dht_log",
    "dht_operation",
    "port_mapping_log",
    "picker_log",
    "file_progress",
    "piece_progress",
    "upload",
    "block_progress"
]


DEFAULT_FLAGS = (  # fixme: somehow the logic here is inverted?
        libtorrent.add_torrent_params_flags_t.flag_auto_managed
        | libtorrent.add_torrent_params_flags_t.flag_duplicate_is_error
        | libtorrent.add_torrent_params_flags_t.flag_update_subscribe
)


def get_notification_type(notification) -> str:
    for i, notification_type in enumerate(NOTIFICATION_MASKS):
        if (1 << i) & notification:
            return notification_type
    raise ValueError("unrecognized notification type")


class TorrentHandle:
    def __init__(self, loop, executor, handle):
        self._loop = loop
        self._executor = executor
        self._handle: libtorrent.torrent_handle = handle
        self.finished = asyncio.Event(loop=loop)
        self.metadata_completed = asyncio.Event(loop=loop)

    def _show_status(self):
        # fixme: cleanup
        status = self._handle.status()
        if status.has_metadata:
            self.metadata_completed.set()
            # metadata: libtorrent.torrent_info = self._handle.get_torrent_info()
            # print(metadata)
            # print(metadata.files())
            # print(type(self._handle))
        if not status.is_seeding:
            print('%.2f%% complete (down: %.1f kB/s up: %.1f kB/s peers: %d seeds: %d) %s - %s' % (
                status.progress * 100, status.download_rate / 1000, status.upload_rate / 1000,
                status.num_peers, status.num_seeds, status.state, status.save_path))
        elif not self.finished.is_set():
            self.finished.set()
            print("finished!")

    async def status_loop(self):
        while True:
            await self._loop.run_in_executor(
                self._executor, self._show_status
            )
            if self.finished.is_set():
                break
            await asyncio.sleep(0.1, loop=self._loop)

    async def pause(self):
        await self._loop.run_in_executor(
            self._executor, self._handle.pause
        )

    async def resume(self):
        await self._loop.run_in_executor(
            self._executor, self._handle.resume
        )


class TorrentSession:
    def __init__(self, loop, executor):
        self._loop = loop
        self._executor = executor
        self._session: Optional[libtorrent.session] = None
        self._handles = {}

    async def add_fake_torrent(self):
        dir = mkdtemp()
        info, btih = self._create_fake(dir)
        flags = libtorrent.add_torrent_params_flags_t.flag_seed_mode
        handle = self._session.add_torrent({
            'ti': info, 'save_path': dir, 'flags': flags
        })
        self._handles[btih] = TorrentHandle(self._loop, self._executor, handle)
        return btih

    def _create_fake(self, dir):
        # beware, that's just for testing
        path = os.path.join(dir, 'tmp')
        with open(path, 'wb') as myfile:
            size = myfile.write(b'0' * 40 * 1024 * 1024)
        fs = libtorrent.file_storage()
        fs.add_file('tmp', size)
        print(fs.file_path(0))
        t = libtorrent.create_torrent(fs, 0, 4 * 1024 * 1024)
        libtorrent.set_piece_hashes(t, dir)
        info = libtorrent.torrent_info(t.generate())
        btih = sha1(info.metadata()).hexdigest()
        return info, btih

    async def bind(self, interface: str = '0.0.0.0', port: int = 10889):
        settings = {
            'listen_interfaces': f"{interface}:{port}",
            'enable_outgoing_utp': True,
            'enable_incoming_utp': True,
            'enable_outgoing_tcp': False,
            'enable_incoming_tcp': False
        }
        self._session = await self._loop.run_in_executor(
            self._executor, libtorrent.session, settings  # pylint: disable=c-extension-no-member
        )
        self._loop.create_task(self.process_alerts())

    def _pop_alerts(self):
        for alert in self._session.pop_alerts():
            print("alert: ", alert)

    async def process_alerts(self):
        while True:
            await self._loop.run_in_executor(
                self._executor, self._pop_alerts
            )
            await asyncio.sleep(1, loop=self._loop)

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
        params = {'info_hash': binascii.unhexlify(btih.encode())}
        flags = DEFAULT_FLAGS
        print(bin(flags))
        flags ^= libtorrent.add_torrent_params_flags_t.flag_paused
        # flags ^= libtorrent.add_torrent_params_flags_t.flag_auto_managed
        # flags ^= libtorrent.add_torrent_params_flags_t.flag_stop_when_ready
        print(bin(flags))
        # params['flags'] = flags
        if download_directory:
            params['save_path'] = download_directory
        handle = self._handles[btih] = TorrentHandle(self._loop, self._executor, self._session.add_torrent(params))
        handle._handle.force_dht_announce()

    async def add_torrent(self, btih, download_path):
        await self._loop.run_in_executor(
            self._executor, self._add_torrent, btih, download_path
        )
        self._loop.create_task(self._handles[btih].status_loop())
        await self._handles[btih].metadata_completed.wait()

    async def remove_torrent(self, btih, remove_files=False):
        if btih in self._handles:
            handle = self._handles[btih]
            self._session.remove_torrent(handle, 1 if remove_files else 0)
            self._handles.pop(btih)


def get_magnet_uri(btih):
    return f"magnet:?xt=urn:btih:{btih}"


async def main():
    if os.path.exists("~/Downloads/ubuntu-18.04.3-live-server-amd64.torrent"):
        os.remove("~/Downloads/ubuntu-18.04.3-live-server-amd64.torrent")
    if os.path.exists("~/Downloads/ubuntu-18.04.3-live-server-amd64.iso"):
        os.remove("~/Downloads/ubuntu-18.04.3-live-server-amd64.iso")

    btih = "dd8255ecdc7ca55fb0bbf81323d87062db1f6d1c"

    executor = None
    session = TorrentSession(asyncio.get_event_loop(), executor)
    session2 = TorrentSession(asyncio.get_event_loop(), executor)
    await session.bind('localhost', port=4040)
    await session2.bind('localhost', port=4041)
    btih = await session.add_fake_torrent()
    session2._session.add_dht_node(('localhost', 4040))
    await session2.add_torrent(btih, "/tmp/down")
    print('added')
    while True:
        print("idling")
        await asyncio.sleep(100)
    await session.pause()
    executor.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
