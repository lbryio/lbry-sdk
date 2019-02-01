import os
import asyncio
import typing
import binascii
import logging
import random
from lbrynet.stream.downloader import StreamDownloader
from lbrynet.stream.managed_stream import ManagedStream
from lbrynet.schema.claim import ClaimDict
from lbrynet.schema.decode import smart_decode
from lbrynet.extras.daemon.storage import lbc_to_dewies
if typing.TYPE_CHECKING:
    from lbrynet.conf import Config
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.dht.node import Node
    from lbrynet.extras.daemon.storage import SQLiteStorage
    from lbrynet.extras.wallet import LbryWalletManager

log = logging.getLogger(__name__)


filter_fields = [
    'status',
    'file_name',
    'sd_hash',
    'stream_hash',
    'claim_name',
    'claim_height',
    'claim_id',
    'outpoint',
    'txid',
    'nout',
    'channel_claim_id',
    'channel_name',
    'full_status'
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
    def __init__(self, loop: asyncio.BaseEventLoop, config: 'Config', blob_manager: 'BlobFileManager',
                 wallet: 'LbryWalletManager', storage: 'SQLiteStorage', node: typing.Optional['Node']):
        self.loop = loop
        self.config = config
        self.blob_manager = blob_manager
        self.wallet = wallet
        self.storage = storage
        self.node = node
        self.streams: typing.Set[ManagedStream] = set()
        self.starting_streams: typing.Dict[str, asyncio.Future] = {}
        self.resume_downloading_task: asyncio.Task = None
        self.update_stream_finished_futs: typing.List[asyncio.Future] = []

    async def _update_content_claim(self, stream: ManagedStream):
        claim_info = await self.storage.get_content_claim(stream.stream_hash)
        stream.set_claim(claim_info, smart_decode(claim_info['value']))

    async def start_stream(self, stream: ManagedStream):
        path = os.path.join(stream.download_directory, stream.file_name)

        if not stream.running or not os.path.isfile(path):
            if stream.downloader:
                stream.downloader.stop()
                stream.downloader = None
            if not os.path.isfile(path) and not os.path.isfile(
                    os.path.join(self.config.download_dir, stream.file_name)):
                await self.storage.change_file_download_dir(stream.stream_hash, self.config.download_dir)
                stream.download_directory = self.config.download_dir
            stream.downloader = self.make_downloader(
                stream.sd_hash, stream.download_directory, stream.file_name
            )
            stream.start_download(self.node)
            await self.storage.change_file_status(stream.stream_hash, 'running')
            stream.update_status('running')
            self.wait_for_stream_finished(stream)

    def make_downloader(self, sd_hash: str, download_directory: str, file_name: str):
        return StreamDownloader(
            self.loop, self.config, self.blob_manager, sd_hash, download_directory, file_name
        )

    async def add_stream(self, sd_hash: str, file_name: str, download_directory: str, status: str, claim):
        sd_blob = self.blob_manager.get_blob(sd_hash)
        if sd_blob.get_is_verified():
            descriptor = await self.blob_manager.get_stream_descriptor(sd_blob.blob_hash)
            downloader = self.make_downloader(descriptor.sd_hash, download_directory, file_name)
            stream = ManagedStream(
                self.loop, self.blob_manager, descriptor,
                download_directory,
                file_name,
                downloader, status, claim
            )
            self.streams.add(stream)
            self.storage.content_claim_callbacks[stream.stream_hash] = lambda: self._update_content_claim(stream)

    async def load_streams_from_database(self):
        file_infos = await self.storage.get_all_lbry_files()
        await asyncio.gather(*[
            self.add_stream(
                file_info['sd_hash'], binascii.unhexlify(file_info['file_name']).decode(),
                binascii.unhexlify(file_info['download_directory']).decode(), file_info['status'], file_info['claim']
            ) for file_info in file_infos
        ])

    async def resume(self):
        if not self.node:
            log.warning("no DHT node given, cannot resume downloads")
            return
        await self.node.joined.wait()
        resumed = 0
        t = [self.start_stream(stream) for stream in self.streams if stream.status == ManagedStream.STATUS_RUNNING]
        if resumed:
            log.info("resuming %i downloads", t)
        await asyncio.gather(*t, loop=self.loop)

    async def reflect_streams(self):
        streams = list(self.streams)
        batch = []
        while streams:
            stream = streams.pop()
            if not stream.fully_reflected.is_set():
                host, port = random.choice(self.reflector_servers)
                batch.append(stream.upload_to_reflector(host, port))
            if len(batch) >= 10:
                await asyncio.gather(*batch)
                batch = []
        if batch:
            await asyncio.gather(*batch)

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

    async def create_stream(self, file_path: str, key: typing.Optional[bytes] = None,
                            iv_generator: typing.Optional[typing.Generator[bytes, None, None]] = None) -> ManagedStream:
        stream = await ManagedStream.create(self.loop, self.blob_manager, file_path, key, iv_generator)
        self.streams.add(stream)
        self.storage.content_claim_callbacks[stream.stream_hash] = lambda: self._update_content_claim(stream)
        if self.config.reflector_servers:
            host, port = random.choice(self.config.reflector_servers)
            self.loop.create_task(stream.upload_to_reflector(host, port))
        return stream

    async def delete_stream(self, stream: ManagedStream, delete_file: typing.Optional[bool] = False):
        stream.stop_download()
        self.streams.remove(stream)
        await self.storage.delete_stream(stream.descriptor)

        blob_hashes = [stream.sd_hash]
        for blob_info in stream.descriptor.blobs[:-1]:
            blob_hashes.append(blob_info.blob_hash)
        await self.blob_manager.delete_blobs(blob_hashes)
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
        task = self.loop.create_task(_wait_for_stream_finished())
        self.update_stream_finished_futs.append(task)
        task.add_done_callback(
            lambda _: None if task not in self.update_stream_finished_futs else
            self.update_stream_finished_futs.remove(task)
        )

    async def _download_stream_from_claim(self, node: 'Node', download_directory: str, claim_info: typing.Dict,
                                          file_name: typing.Optional[str] = None) -> typing.Optional[ManagedStream]:

        claim = smart_decode(claim_info['value'])
        downloader = StreamDownloader(self.loop, self.config, self.blob_manager, claim.source_hash.decode(),
                                      download_directory, file_name)
        try:
            downloader.download(node)
            await downloader.got_descriptor.wait()
            log.info("got descriptor %s for %s", claim.source_hash.decode(), claim_info['name'])
        except (asyncio.TimeoutError, asyncio.CancelledError):
            log.info("stream timeout")
            downloader.stop()
            log.info("stopped stream")
            return
        if not await self.blob_manager.storage.stream_exists(downloader.sd_hash):
            await self.blob_manager.storage.store_stream(downloader.sd_blob, downloader.descriptor)
        if not await self.blob_manager.storage.file_exists(downloader.sd_hash):
            await self.blob_manager.storage.save_downloaded_file(
                downloader.descriptor.stream_hash, os.path.basename(downloader.output_path), download_directory,
                0.0
            )
        await self.blob_manager.storage.save_content_claim(
            downloader.descriptor.stream_hash, f"{claim_info['txid']}:{claim_info['nout']}"
        )
        stream = ManagedStream(self.loop, self.blob_manager, downloader.descriptor, download_directory,
                               os.path.basename(downloader.output_path), downloader, ManagedStream.STATUS_RUNNING)
        stream.set_claim(claim_info, claim)
        self.streams.add(stream)
        try:
            await stream.downloader.wrote_bytes_event.wait()
            self.wait_for_stream_finished(stream)
            return stream
        except asyncio.CancelledError:
            downloader.stop()
            log.debug("stopped stream")

    async def download_stream_from_claim(self, node: 'Node', claim_info: typing.Dict,
                                         file_name: typing.Optional[str] = None,
                                         timeout: typing.Optional[float] = 60,
                                         fee_amount: typing.Optional[float] = 0.0,
                                         fee_address: typing.Optional[str] = None) -> typing.Optional[ManagedStream]:
        log.info("get lbry://%s#%s", claim_info['name'], claim_info['claim_id'])
        claim = ClaimDict.load_dict(claim_info['value'])
        if fee_address and fee_amount:
            if fee_amount > await self.wallet.default_account.get_balance():
                raise Exception("not enough funds")
        sd_hash = claim.source_hash.decode()
        if sd_hash in self.starting_streams:
            return await self.starting_streams[sd_hash]
        already_started = tuple(filter(lambda s: s.descriptor.sd_hash == sd_hash, self.streams))
        if already_started:
            return already_started[0]

        self.starting_streams[sd_hash] = asyncio.Future(loop=self.loop)
        stream_task = self.loop.create_task(
            self._download_stream_from_claim(node, self.config.download_dir, claim_info, file_name)
        )
        try:
            await asyncio.wait_for(stream_task, timeout or self.config.download_timeout)
            stream = await stream_task
            self.starting_streams[sd_hash].set_result(stream)
            if fee_address and fee_amount:
                await self.wallet.send_amount_to_address(lbc_to_dewies(str(fee_amount)), fee_address.encode('latin1'))
            return stream
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return
        finally:
            if sd_hash in self.starting_streams:
                del self.starting_streams[sd_hash]
            log.info("returned from get lbry://%s#%s", claim_info['name'], claim_info['claim_id'])

    def get_stream_by_stream_hash(self, stream_hash: str) -> typing.Optional[ManagedStream]:
        streams = tuple(filter(lambda stream: stream.stream_hash == stream_hash, self.streams))
        if streams:
            return streams[0]

    def get_filtered_streams(self, sort_by: typing.Optional[str] = None, reverse: typing.Optional[bool] = False,
                             comparison: typing.Optional[str] = None,
                             **search_by) -> typing.List[ManagedStream]:
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
                    if search == 'full_status':
                        continue
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
