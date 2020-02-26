import asyncio
import binascii
import logging
import typing
from typing import Optional
from aiohttp.web import Request
from lbry.file.source_manager import SourceManager
from lbry.file.source import ManagedDownloadSource

if typing.TYPE_CHECKING:
    from lbry.torrent.session import TorrentSession
    from lbry.conf import Config
    from lbry.wallet.transaction import Transaction
    from lbry.extras.daemon.analytics import AnalyticsManager
    from lbry.extras.daemon.storage import SQLiteStorage, StoredContentClaim
    from lbry.extras.daemon.storage import StoredContentClaim

log = logging.getLogger(__name__)


def path_or_none(encoded_path) -> Optional[str]:
    if not encoded_path:
        return
    return binascii.unhexlify(encoded_path).decode()


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

    async def start(self, timeout: Optional[float] = None, save_now: Optional[bool] = False):
        await self.torrent_session.add_torrent(self.identifier, self.download_directory)

    async def stop(self, finished: bool = False):
        await self.torrent_session.remove_torrent(self.identifier)

    async def save_file(self, file_name: Optional[str] = None, download_directory: Optional[str] = None):
        await self.torrent_session.save_file(self.identifier, download_directory)

    @property
    def torrent_length(self):
        return self.torrent_session.get_size(self.identifier)

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
        return self.torrent_session.get_downloaded(self.identifier) == self.torrent_length


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
                           added_on: Optional[int]):
        stream = TorrentSource(
            self.loop, self.config, self.storage, identifier=bt_infohash, file_name=file_name,
            download_directory=download_directory, status=status, claim=claim, rowid=rowid,
            content_fee=content_fee, analytics_manager=self.analytics_manager, added_on=added_on,
            torrent_session=self.torrent_session
        )
        self.add(stream)

    async def initialize_from_database(self):
        pass

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
        # blob_hashes = [source.sd_hash] + [b.blob_hash for b in source.descriptor.blobs[:-1]]
        # await self.blob_manager.delete_blobs(blob_hashes, delete_from_db=False)
        # await self.storage.delete_stream(source.descriptor)

    async def stream_partial_content(self, request: Request, sd_hash: str):
        raise NotImplementedError
