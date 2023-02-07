import asyncio
import logging
import os
import typing
from typing import Optional
from aiohttp.web import Request, StreamResponse, HTTPRequestRangeNotSatisfiable

from lbry.error import DownloadMetadataTimeoutError
from lbry.file.source_manager import SourceManager
from lbry.file.source import ManagedDownloadSource
from lbry.schema.mime_types import guess_media_type

if typing.TYPE_CHECKING:
    from lbry.torrent.session import TorrentSession
    from lbry.conf import Config
    from lbry.wallet.transaction import Transaction
    from lbry.extras.daemon.analytics import AnalyticsManager
    from lbry.extras.daemon.storage import SQLiteStorage, StoredContentClaim
    from lbry.extras.daemon.storage import StoredContentClaim

log = logging.getLogger(__name__)


class TorrentSource(ManagedDownloadSource):
    STATUS_STOPPED = "stopped"
    filter_fields = SourceManager.filter_fields
    filter_fields.update({
        'bt_infohash'
    })

    def __init__(self, loop: asyncio.AbstractEventLoop, config: 'Config', storage: 'SQLiteStorage', identifier: str,
                 file_name: Optional[str] = None, download_directory: Optional[str] = None,
                 status: Optional[str] = STATUS_STOPPED, claim: Optional['StoredContentClaim'] = None,
                 download_id: Optional[str] = None, rowid: Optional[int] = None,
                 content_fee: Optional['Transaction'] = None,
                 analytics_manager: Optional['AnalyticsManager'] = None,
                 added_on: Optional[int] = None, torrent_session: Optional['TorrentSession'] = None):
        super().__init__(loop, config, storage, identifier, file_name, download_directory, status, claim, download_id,
                         rowid, content_fee, analytics_manager, added_on)
        self.torrent_session = torrent_session
        self._suggested_file_name = None
        self._full_path = None

    @property
    def full_path(self) -> Optional[str]:
        if not self._full_path:
            self._full_path = self.select_path()
            self._file_name = os.path.basename(self._full_path)
        self.download_directory = self.torrent_session.save_path(self.identifier)
        return self._full_path

    def select_path(self):
        wanted_name = (self.stream_claim_info.claim.stream.source.name or '') if self.stream_claim_info else ''
        wanted_index = self.torrent_session.get_index_from_name(self.identifier, wanted_name)
        if wanted_index is None:
            # maybe warn?
            largest = (None, -1)
            for (path, size) in self.torrent_session.get_files(self.identifier).items():
                largest = (path, size) if size > largest[1] else largest
            return largest[0]
        else:
            return self.torrent_session.full_path(self.identifier, wanted_index or 0)

    @property
    def suggested_file_name(self):
        self._suggested_file_name = self._suggested_file_name or os.path.basename(self.select_path())
        return self._suggested_file_name

    @property
    def mime_type(self) -> Optional[str]:
        return guess_media_type(os.path.basename(self.full_path))[0]

    async def setup(self, timeout: Optional[float] = None):
        try:
            metadata_download = self.torrent_session.add_torrent(self.identifier, self.download_directory)
            await asyncio.wait_for(metadata_download, timeout, loop=self.loop)
        except asyncio.TimeoutError:
            self.torrent_session.remove_torrent(btih=self.identifier)
            raise DownloadMetadataTimeoutError(self.identifier)
        self.download_directory = self.torrent_session.save_path(self.identifier)
        self._file_name = os.path.basename(self.full_path)

    async def start(self, timeout: Optional[float] = None, save_now: Optional[bool] = False):
        await self.setup(timeout)
        if not self.rowid:
            await self.storage.add_torrent(self.identifier, self.torrent_length, self.torrent_name)
            self.rowid = await self.storage.save_downloaded_file(
                self.identifier, self.file_name, self.download_directory, 0.0, added_on=self._added_on
            )

    async def stop(self, finished: bool = False):
        await self.torrent_session.remove_torrent(self.identifier)

    async def save_file(self, file_name: Optional[str] = None, download_directory: Optional[str] = None):
        await self.torrent_session.save_file(self.identifier, download_directory)

    @property
    def torrent_length(self):
        return self.torrent_session.get_total_size(self.identifier)

    @property
    def stream_length(self):
        return self.torrent_session.get_size(self.identifier, self.file_name)

    @property
    def written_bytes(self):
        return self.torrent_session.get_downloaded(self.identifier)

    @property
    def torrent_name(self):
        return self.torrent_session.get_name(self.identifier)

    @property
    def bt_infohash(self):
        return self.identifier

    def stop_tasks(self):
        pass

    @property
    def completed(self):
        return self.torrent_session.is_completed(self.identifier)

    @property
    def status(self):
        return self.STATUS_FINISHED if self.completed else self.STATUS_RUNNING

    async def stream_file(self, request):
        log.info("stream torrent to browser for lbry://%s#%s (btih %s...)", self.claim_name, self.claim_id,
                 self.identifier[:6])
        headers, start, end = self._prepare_range_response_headers(
            request.headers.get('range', 'bytes=0-')
        )
        target = self.suggested_file_name
        await self.start()
        response = StreamResponse(
            status=206,
            headers=headers
        )
        await response.prepare(request)
        while not os.path.exists(self.full_path):
            async for _ in self.torrent_session.stream_file(self.identifier, target, start, end):
                break
        with open(self.full_path, 'rb') as infile:
            infile.seek(start)
            async for read_size in self.torrent_session.stream_file(self.identifier, target, start, end):
                if infile.tell() + read_size < end:
                    await response.write(infile.read(read_size))
                else:
                    await response.write_eof(infile.read(end - infile.tell() + 1))
        return response

    def _prepare_range_response_headers(self, get_range: str) -> typing.Tuple[typing.Dict[str, str], int, int]:
        if '=' in get_range:
            get_range = get_range.split('=')[1]
        start, end = get_range.split('-')
        size = self.stream_length

        start = int(start)
        end = int(end) if end else size - 1

        if end >= size or not 0 <= start < size:
            raise HTTPRequestRangeNotSatisfiable()

        final_size = end - start + 1
        headers = {
            'Accept-Ranges': 'bytes',
            'Content-Range': f'bytes {start}-{end}/{size}',
            'Content-Length': str(final_size),
            'Content-Type': self.mime_type
        }
        return headers, start, end


class TorrentManager(SourceManager):
    _sources: typing.Dict[str, ManagedDownloadSource]

    filter_fields = set(SourceManager.filter_fields)
    filter_fields.update({
        'bt_infohash',
        'blobs_remaining',  # TODO: here they call them "parts", but its pretty much the same concept
        'blobs_in_stream'
    })

    def __init__(self, loop: asyncio.AbstractEventLoop, config: 'Config', torrent_session: 'TorrentSession',
                 storage: 'SQLiteStorage', analytics_manager: Optional['AnalyticsManager'] = None):
        super().__init__(loop, config, storage, analytics_manager)
        self.torrent_session: 'TorrentSession' = torrent_session

    async def recover_streams(self, file_infos: typing.List[typing.Dict]):
        raise NotImplementedError

    async def _load_stream(self, rowid: int, bt_infohash: str, file_name: Optional[str],
                           download_directory: Optional[str], status: str,
                           claim: Optional['StoredContentClaim'], content_fee: Optional['Transaction'],
                           added_on: Optional[int], **kwargs):
        stream = TorrentSource(
            self.loop, self.config, self.storage, identifier=bt_infohash, file_name=file_name,
            download_directory=download_directory, status=status, claim=claim, rowid=rowid,
            content_fee=content_fee, analytics_manager=self.analytics_manager, added_on=added_on,
            torrent_session=self.torrent_session
        )
        self.add(stream)
        await stream.setup()

    async def initialize_from_database(self):
        for file in await self.storage.get_all_torrent_files():
            claim = await self.storage.get_content_claim_for_torrent(file['bt_infohash'])
            file['download_directory'] = bytes.fromhex(file['download_directory'] or '').decode() or None
            file['file_name'] = bytes.fromhex(file['file_name'] or '').decode() or None
            await self._load_stream(claim=claim, **file)

    async def start(self):
        await super().start()

    def stop(self):
        super().stop()
        log.info("finished stopping the torrent manager")

    async def delete(self, source: ManagedDownloadSource, delete_file: Optional[bool] = False):
        await super().delete(source, delete_file)
        self.torrent_session.remove_torrent(source.identifier, delete_file)

    async def create(self, file_path: str, key: Optional[bytes] = None,
                     iv_generator: Optional[typing.Generator[bytes, None, None]] = None):
        raise NotImplementedError

    async def _delete(self, source: ManagedDownloadSource, delete_file: Optional[bool] = False):
        raise NotImplementedError

    async def stream_partial_content(self, request: Request, identifier: str):
        return await self._sources[identifier].stream_file(request)
