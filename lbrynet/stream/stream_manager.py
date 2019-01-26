import os
import asyncio
import typing
import binascii
import logging
import random
import functools
from lbrynet.stream.reflector import auto_reflector
from lbrynet.stream.downloader import StreamDownloader
from lbrynet.stream.managed_stream import ManagedStream
from lbrynet.schema.claim import ClaimDict
from lbrynet.extras.daemon.storage import StoredStreamClaim, lbc_to_dewies
if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.dht.peer import KademliaPeer
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
    def __init__(self, loop: asyncio.AbstractEventLoop, blob_manager: 'BlobFileManager', wallet: 'LbryWalletManager',
                 storage: 'SQLiteStorage', node: typing.Optional['Node'], peer_timeout: float,
                 peer_connect_timeout: float, fixed_peers: typing.Optional[typing.List['KademliaPeer']] = None,
                 reflector_servers: typing.Optional[typing.List[typing.Tuple[str, int]]] = None,
                 auto_reflect: typing.Optional[bool] = False):
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
        self.fixed_peers = fixed_peers
        self.reflector_servers = reflector_servers
        self.auto_reflect = auto_reflect

    async def load_streams_from_database(self):
        infos = await self.storage.get_all_lbry_files()
        for file_info in infos:
            sd_blob = self.blob_manager.get_blob(file_info['sd_hash'])
            if sd_blob.get_is_verified():
                descriptor = await self.blob_manager.get_stream_descriptor(sd_blob.blob_hash)
                downloader = StreamDownloader(
                    self.loop, self.blob_manager, descriptor.sd_hash, self.peer_timeout,
                    self.peer_connect_timeout, binascii.unhexlify(file_info['download_directory']).decode(),
                    binascii.unhexlify(file_info['file_name']).decode(), self.fixed_peers
                )
                stream = ManagedStream(
                    self.loop, self.blob_manager, descriptor,
                    binascii.unhexlify(file_info['download_directory']).decode(),
                    binascii.unhexlify(file_info['file_name']).decode(),
                    downloader, file_info['status'], file_info['claim']
                )
                self.streams.add(stream)
                if self.auto_reflect:
                    await auto_reflector(typing.cast('typing.AsyncIterable', stream))

    async def resume(self):
        if not self.node:
            log.warning("no DHT node given, cannot resume downloads")
            return
        await self.node.joined.wait()
        resumed = 0
        for stream in self.streams:
            if stream.status == ManagedStream.STATUS_RUNNING:
                resumed += 1
                stream.downloader.download(self.node)
                self.wait_for_stream_finished(stream)
            if stream.status == ManagedStream.STATUS_FINISHED:
                if self.auto_reflect:
                    await auto_reflector(typing.cast('typing.AsyncIterable', stream))
        if resumed:
            log.info("resuming %i downloads", resumed)

    async def reflect_streams(self):
        async for stream in self.storage.get_streams_to_re_reflect():
            try:
                await asyncio.create_task(await stream.upload_to_reflector(self.reflector_servers))
                assert stream.fully_reflected.is_set(), self.wait_for_stream_finished(stream)
                break
            except (asyncio.CancelledError, asyncio.InvalidStateError):
                await stream.upload_to_reflector(self.reflector_servers)
                assert stream.status, StopAsyncIteration
                continue
            finally:
                await asyncio.wait_for(stream, timeout=0).add_done_callback(stream.status)
            return await stream.fully_reflected
        assert self.storage.get_streams_to_re_reflect() is None, self.reflect_streams()

    async def start(self):
        await self.load_streams_from_database()
        self.resume_downloading_task = self.loop.create_task(self.resume())
        if self.auto_reflect:
            self.loop.call_soon_threadsafe(self.reflect_streams)

    async def stop(self):
        if self.resume_downloading_task and not self.resume_downloading_task.done():
            self.resume_downloading_task.cancel()
        while self.streams:
            stream = self.streams.pop()
            await stream.stop_download()
        while self.update_stream_finished_futs:
            self.update_stream_finished_futs.pop().cancel()

    async def create_stream(self, file_path: str, key: typing.Optional[bytes] = None,
                            iv_generator: typing.Optional[typing.Generator[bytes, None, None]] = None) -> ManagedStream:
        stream = await ManagedStream.create(self.loop, self.blob_manager, file_path, key, iv_generator)
        self.streams.add(stream)
        if self.reflector_servers:
            host, port = random.choice(self.reflector_servers)
            await self.loop.create_task(stream.upload_to_reflector(host, port))
        return stream

    async def delete_stream(self, stream: ManagedStream, delete_file: typing.Optional[bool] = False):
        await stream.stop_download()
        self.streams.remove(stream)
        await self.storage.delete_stream(stream.descriptor)

        blob_hashes = [stream.sd_hash]
        for blob_info in stream.descriptor.blobs[:-1]:
            blob_hashes.append(blob_info.blob_hash)
        for blob_hash in blob_hashes:
            blob = self.blob_manager.get_blob(blob_hash)
            if blob.get_is_verified():
                await blob.delete()

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
                                          file_name: typing.Optional[str] = None, data_rate: typing.Optional[int] = 0,
                                          sd_blob_timeout: typing.Optional[float] = 60
                                          ) -> typing.Optional[ManagedStream]:

        claim = ClaimDict.load_dict(claim_info['value'])
        downloader = StreamDownloader(self.loop, self.blob_manager, claim.source_hash.decode(), self.peer_timeout,
                                      self.peer_connect_timeout, download_directory, file_name, self.fixed_peers)
        try:
            downloader.download(node)
            await asyncio.wait_for(downloader.got_descriptor.wait(), sd_blob_timeout)
            log.info("got descriptor %s for %s", claim.source_hash.decode(), claim_info['name'])
        except (asyncio.TimeoutError, asyncio.CancelledError):
            log.info("stream timeout")
            await downloader.stop()
            log.info("stopped stream")
            return
        if not await self.blob_manager.storage.stream_exists(downloader.sd_hash):
            await self.blob_manager.storage.store_stream(downloader.sd_blob, downloader.descriptor)
        if not await self.blob_manager.storage.file_exists(downloader.sd_hash):
            await self.blob_manager.storage.save_downloaded_file(
                downloader.descriptor.stream_hash, os.path.basename(downloader.output_path), download_directory,
                data_rate
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
            await downloader.stop()

    async def download_stream_from_claim(self, node: 'Node', download_directory: str, claim_info: typing.Dict,
                                         file_name: typing.Optional[str] = None,
                                         sd_blob_timeout: typing.Optional[float] = 60,
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
            self._download_stream_from_claim(node, download_directory, claim_info, file_name, 0, sd_blob_timeout)
        )
        try:
            await asyncio.wait_for(stream_task, sd_blob_timeout)
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
