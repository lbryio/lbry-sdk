import os
import asyncio
import typing
import binascii
import logging
from lbrynet.stream.downloader import StreamDownloader
from lbrynet.stream.managed_stream import ManagedStream
from lbrynet.schema.claim import ClaimDict
from lbrynet.storage import StoredStreamClaim
if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.dht.node import Node
    from lbrynet.storage import SQLiteStorage
    from lbrynet.extras.wallet import LbryWalletManager

log = logging.getLogger(__name__)


filter_fields = [
    'status',
    'file_name',
    'sd_hash',
    'stream_hash',
    'claim_name',
    'claim_height'
    'claim_id',
    'outpoint',
    'txid',
    'nout',
    'channel_claim_id',
    'channel_name',
]

comparison_operators = {
    'eq': lambda a, b: a == b,
    'ne': lambda a, b: a != b,
    'g': lambda a, b: a > b,
    'l': lambda a, b: a < b,
    'ge': lambda a, b: a >= b,
    'le': lambda a, b: a <= b,
}


class StreamManager:
    def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: 'BlobFileManager', wallet: 'LbryWalletManager',
                 storage: 'SQLiteStorage', node: 'Node', peer_timeout: int, peer_connect_timeout: int):
        self.loop = loop
        self.blob_manager = blob_manager
        self.wallet = wallet
        self.storage = storage
        self.node = node
        self.peer_timeout = peer_timeout
        self.peer_connect_timeout = peer_connect_timeout
        self.streams: typing.Set[ManagedStream] = set()
        self.starting_streams: typing.Dict[str, asyncio.Future] = {}
        self.resume_downloading_task: asyncio.Task = None
        self.update_stream_finished_futs: typing.List[asyncio.Future] = []

    async def load_streams_from_database(self):
        infos = await self.storage.get_all_lbry_files()
        for file_info in infos:
            sd_blob = self.blob_manager.get_blob(file_info['sd_hash'])
            if sd_blob.get_is_verified():
                descriptor = await self.blob_manager.get_stream_descriptor(sd_blob.blob_hash)
                downloader = StreamDownloader(
                    self.loop, self.blob_manager, descriptor.sd_hash, self.peer_timeout,
                    self.peer_connect_timeout, binascii.unhexlify(file_info['download_directory']).decode(),
                    binascii.unhexlify(file_info['file_name']).decode()
                )
                stream = ManagedStream(
                    self.loop, self.blob_manager, descriptor,
                    binascii.unhexlify(file_info['download_directory']).decode(),
                    binascii.unhexlify(file_info['file_name']).decode(),
                    downloader, file_info['status'], file_info['claim']
                )
                self.streams.add(stream)

    async def resume(self):
        await self.node.joined.wait()
        resumed = 0
        for stream in self.streams:
            if stream.status == ManagedStream.STATUS_RUNNING:
                resumed += 1
                stream.downloader.download(self.node)
                self.wait_for_stream_finished(stream)
        if resumed:
            log.info("resuming %i downloads", resumed)

    async def start(self):
        await self.load_streams_from_database()
        self.resume_downloading_task = self.loop.create_task(self.resume())

    def stop(self):
        if self.resume_downloading_task and not self.resume_downloading_task.done():
            self.resume_downloading_task.cancel()
        while self.streams:
            stream = self.streams.pop()
            stream.stop_download()
        while self.update_stream_finished_futs:
            self.update_stream_finished_futs.pop().cancel()

    async def create_stream(self, file_path: str) -> ManagedStream:
        stream = await ManagedStream.create(self.loop, self.blob_manager, file_path)
        self.streams.add(stream)
        return stream

    async def delete_stream(self, stream: ManagedStream, delete_file: typing.Optional[bool] = False):
        if stream.running:
            stream.stop_download()
        self.streams.remove(stream)
        await self.storage.delete_stream(stream.descriptor)
        if delete_file:
            path = os.path.join(stream.download_directory, stream.file_name)
            if os.path.isfile(path):
                os.remove(path)

    def wait_for_stream_finished(self, stream: ManagedStream):
        async def _wait_for_stream_finished():
            if stream.downloader and stream.running:
                try:
                    await stream.downloader.stream_finished_event.wait()
                    stream.update_status(ManagedStream.STATUS_FINISHED)
                except asyncio.CancelledError:
                    pass
        fut = asyncio.ensure_future(_wait_for_stream_finished(), loop=self.loop)
        self.update_stream_finished_futs.append(fut)
        fut.add_done_callback(
            lambda _: None if fut not in self.update_stream_finished_futs else
            self.update_stream_finished_futs.remove(fut)
        )

    async def _download_stream_from_claim(self, node: 'Node', download_directory: str, claim_info: typing.Dict,
                                          file_name: typing.Optional[str] = None, data_rate: typing.Optional[int] = 0,
                                          sd_blob_timeout: typing.Optional[float] = 60
                                          ) -> typing.Optional[ManagedStream]:

        claim = ClaimDict.load_dict(claim_info['value'])
        downloader = StreamDownloader(self.loop, self.blob_manager, claim.source_hash.decode(), self.peer_timeout,
                                      self.peer_connect_timeout, download_directory, file_name)
        downloader.download(node)
        try:
            await asyncio.wait_for(downloader.got_descriptor.wait(), sd_blob_timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError) as err:
            log.info("stream timeout")
            downloader.stop()
            log.info("stopped stream")
            return

        # TODO: do this in one db call instead of three
        await self.blob_manager.storage.store_stream(downloader.sd_blob, downloader.descriptor)
        await self.blob_manager.storage.save_downloaded_file(
            downloader.descriptor.stream_hash, os.path.basename(downloader.output_path), download_directory, data_rate
        )
        await self.blob_manager.storage.save_content_claim(
            downloader.descriptor.stream_hash, f"{claim_info['txid']}:{claim_info['nout']}"
        )

        stored_claim = StoredStreamClaim(
            downloader.descriptor.stream_hash, f"{claim_info['txid']}:{claim_info['nout']}", claim_info['claim_id'],
            claim_info['name'], claim_info['amount'], claim_info['height'], claim_info['hex'],
            claim.certificate_id, claim_info['address'], claim_info['claim_sequence'],
            claim_info.get('channel_name')
        )
        stream = ManagedStream(self.loop, self.blob_manager, downloader.descriptor, download_directory,
                               os.path.basename(downloader.output_path), downloader, ManagedStream.STATUS_RUNNING,
                               stored_claim)
        self.streams.add(stream)
        try:
            await stream.downloader.wrote_bytes_event.wait()
            self.wait_for_stream_finished(stream)
            return stream
        except asyncio.CancelledError:
            downloader.stop()

    async def download_stream_from_claim(self, node: 'Node', download_directory: str, claim_info: typing.Dict,
                                         file_name: typing.Optional[str] = None,
                                         sd_blob_timeout: typing.Optional[float] = 60
                                         ) -> typing.Optional[ManagedStream]:
        claim = ClaimDict.load_dict(claim_info['value'])
        sd_hash = claim.source_hash.decode()
        if sd_hash in self.starting_streams:
            return await self.starting_streams[sd_hash]
        already_started = tuple(filter(lambda s: s.descriptor.sd_hash == sd_hash, self.streams))
        if already_started:
            return already_started[0]

        self.starting_streams[sd_hash] = asyncio.Future(loop=self.loop)
        stream_task = self.loop.create_task(
            self._download_stream_from_claim(node, download_directory, claim_info, file_name, 0, sd_blob_timeout)
        )
        try:
            await asyncio.wait_for(stream_task, sd_blob_timeout)
            stream = await stream_task
            self.starting_streams[sd_hash].set_result(stream)
            return stream
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return
        finally:
            if sd_hash in self.starting_streams:
                del self.starting_streams[sd_hash]

    def get_filtered_streams(self, sort_by: typing.Optional[str] = None, reverse: typing.Optional[bool] = False,
                             comparison: typing.Optional[str] = None,
                             **search_by: typing.Dict[str, typing.Union[str, int]]) -> typing.List[ManagedStream]:
        """
        Get a list of filtered and sorted ManagedStream objects

        :param sort_by: field to sort by
        :param reverse: reverse sorting
        :param comparison: comparison operator used for filtering
        :param search_by: fields and values to filter by
        """
        if sort_by and sort_by not in filter_fields:
            raise ValueError(f"'{sort_by}' is not a valid field to sort by")
        if comparison and comparison not in comparison_operators:
            raise ValueError(f"'{comparison}' is not a valid comparison")
        for search in search_by.keys():
            if search not in filter_fields:
                raise ValueError(f"'{search}' is not a valid search operation")
        if search_by:
            comparison = comparison or 'eq'
            streams = []
            for stream in self.streams:
                for search, val in search_by.items():
                    if comparison_operators[comparison](getattr(stream, search), val):
                        streams.append(stream)
                        break
        else:
            streams = list(self.streams)
        if sort_by:
            streams.sort(key=lambda s: getattr(s, sort_by))
            if reverse:
                streams.reverse()
        return streams
