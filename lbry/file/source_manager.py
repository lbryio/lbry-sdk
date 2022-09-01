import os
import asyncio
import logging
import typing
from typing import Optional
from lbry.file.source import ManagedDownloadSource
if typing.TYPE_CHECKING:
    from lbry.conf import Config
    from lbry.extras.daemon.analytics import AnalyticsManager
    from lbry.extras.daemon.storage import SQLiteStorage

log = logging.getLogger(__name__)

COMPARISON_OPERATORS = {
    'eq': lambda a, b: a == b,
    'ne': lambda a, b: a != b,
    'g': lambda a, b: a > b,
    'l': lambda a, b: a < b,
    'ge': lambda a, b: a >= b,
    'le': lambda a, b: a <= b,
}


class SourceManager:
    filter_fields = {
        'identifier',
        'rowid',
        'status',
        'file_name',
        'added_on',
        'download_path',
        'claim_name',
        'claim_height',
        'claim_id',
        'outpoint',
        'txid',
        'nout',
        'channel_claim_id',
        'channel_name',
        'completed'
    }

    set_filter_fields = {
        "claim_ids": "claim_id",
        "channel_claim_ids": "channel_claim_id",
        "outpoints": "outpoint"
    }

    source_class = ManagedDownloadSource

    def __init__(self, loop: asyncio.AbstractEventLoop, config: 'Config', storage: 'SQLiteStorage',
                 analytics_manager: Optional['AnalyticsManager'] = None):
        self.loop = loop
        self.config = config
        self.storage = storage
        self.analytics_manager = analytics_manager
        self._sources: typing.Dict[str, ManagedDownloadSource] = {}
        self.started = asyncio.Event()

    def add(self, source: ManagedDownloadSource):
        self._sources[source.identifier] = source

    def remove(self, source: ManagedDownloadSource):
        if source.identifier not in self._sources:
            return
        self._sources.pop(source.identifier)
        source.stop_tasks()

    async def initialize_from_database(self):
        raise NotImplementedError()

    async def start(self):
        await self.initialize_from_database()
        self.started.set()

    def stop(self):
        while self._sources:
            _, source = self._sources.popitem()
            source.stop_tasks()
        self.started.clear()

    async def create(self, file_path: str, key: Optional[bytes] = None,
                     iv_generator: Optional[typing.Generator[bytes, None, None]] = None) -> ManagedDownloadSource:
        raise NotImplementedError()

    async def delete(self, source: ManagedDownloadSource, delete_file: Optional[bool] = False):
        self.remove(source)
        if delete_file and source.output_file_exists:
            os.remove(source.full_path)

    def get_filtered(self, sort_by: Optional[str] = None, reverse: Optional[bool] = False,
                     comparison: Optional[str] = None, **search_by) -> typing.List[ManagedDownloadSource]:
        """
        Get a list of filtered and sorted ManagedStream objects

        :param sort_by: field to sort by
        :param reverse: reverse sorting
        :param comparison: comparison operator used for filtering
        :param search_by: fields and values to filter by
        """
        if sort_by and sort_by not in self.filter_fields:
            raise ValueError(f"'{sort_by}' is not a valid field to sort by")
        if comparison and comparison not in COMPARISON_OPERATORS:
            raise ValueError(f"'{comparison}' is not a valid comparison")
        if 'full_status' in search_by:
            del search_by['full_status']

        for search in search_by:
            if search not in self.filter_fields:
                raise ValueError(f"'{search}' is not a valid search operation")

        compare_sets = {}
        if isinstance(search_by.get('claim_id'), list):
            compare_sets['claim_ids'] = search_by.pop('claim_id')
        if isinstance(search_by.get('outpoint'), list):
            compare_sets['outpoints'] = search_by.pop('outpoint')
        if isinstance(search_by.get('channel_claim_id'), list):
            compare_sets['channel_claim_ids'] = search_by.pop('channel_claim_id')

        if search_by or compare_sets:
            comparison = comparison or 'eq'
            streams = []
            for stream in self._sources.values():
                if compare_sets and not all(
                        getattr(stream, self.set_filter_fields[set_search]) in val
                        for set_search, val in compare_sets.items()):
                    continue
                if search_by and not all(
                        COMPARISON_OPERATORS[comparison](getattr(stream, search), val)
                        for search, val in search_by.items()):
                    continue
                streams.append(stream)
        else:
            streams = list(self._sources.values())
        if sort_by:
            streams.sort(key=lambda s: getattr(s, sort_by) or "")
            if reverse:
                streams.reverse()
        return streams
