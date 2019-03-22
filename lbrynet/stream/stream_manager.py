import os
import asyncio
import typing
import binascii
import logging
import random
from decimal import Decimal
from lbrynet.error import ResolveError, InvalidStreamDescriptorError, KeyFeeAboveMaxAllowed, InsufficientFundsError, \
    DownloadDataTimeout, DownloadSDTimeout
from lbrynet.utils import generate_id
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.stream.downloader import StreamDownloader
from lbrynet.stream.managed_stream import ManagedStream
from lbrynet.schema.claim import Claim
from lbrynet.schema.uri import parse_lbry_uri
from lbrynet.extras.daemon.storage import lbc_to_dewies
if typing.TYPE_CHECKING:
    from lbrynet.conf import Config
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.dht.node import Node
    from lbrynet.extras.daemon.analytics import AnalyticsManager
    from lbrynet.extras.daemon.storage import SQLiteStorage, StoredStreamClaim
    from lbrynet.wallet import LbryWalletManager
    from lbrynet.extras.daemon.exchange_rate_manager import ExchangeRateManager

log = logging.getLogger(__name__)

filter_fields = [
    'rowid',
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
    'full_status',  # TODO: remove
    'blobs_remaining',
    'blobs_in_stream'
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
                 wallet: 'LbryWalletManager', storage: 'SQLiteStorage', node: typing.Optional['Node'],
                 analytics_manager: typing.Optional['AnalyticsManager'] = None):
        self.loop = loop
        self.config = config
        self.blob_manager = blob_manager
        self.wallet = wallet
        self.storage = storage
        self.node = node
        self.analytics_manager = analytics_manager
        self.streams: typing.Set[ManagedStream] = set()
        self.starting_streams: typing.Dict[str, asyncio.Future] = {}
        self.resume_downloading_task: asyncio.Task = None
        self.re_reflect_task: asyncio.Task = None
        self.update_stream_finished_futs: typing.List[asyncio.Future] = []
        self.running_reflector_uploads: typing.List[asyncio.Task] = []

    async def _update_content_claim(self, stream: ManagedStream):
        claim_info = await self.storage.get_content_claim(stream.stream_hash)
        stream.set_claim(claim_info, claim_info['value'])

    async def start_stream(self, stream: ManagedStream) -> bool:
        """
        Resume or rebuild a partial or completed stream
        """
        if not stream.running and not stream.output_file_exists:
            if stream.downloader:
                stream.downloader.stop()
                stream.downloader = None

            # the directory is gone, can happen when the folder that contains a published file is deleted
            # reset the download directory to the default and update the file name
            if not os.path.isdir(stream.download_directory):
                stream.download_directory = self.config.download_dir

            stream.downloader = self.make_downloader(
                stream.sd_hash, stream.download_directory, stream.descriptor.suggested_file_name
            )
            if stream.status != ManagedStream.STATUS_FINISHED:
                await self.storage.change_file_status(stream.stream_hash, 'running')
                stream.update_status('running')
            stream.start_download(self.node)
            try:
                await asyncio.wait_for(self.loop.create_task(stream.downloader.wrote_bytes_event.wait()),
                                       self.config.download_timeout)
            except asyncio.TimeoutError:
                await self.stop_stream(stream)
                if stream in self.streams:
                    self.streams.remove(stream)
                return False
            file_name = os.path.basename(stream.downloader.output_path)
            output_dir = os.path.dirname(stream.downloader.output_path)
            await self.storage.change_file_download_dir_and_file_name(
                stream.stream_hash, output_dir, file_name
            )
            stream._file_name = file_name
            stream.download_directory = output_dir
            self.wait_for_stream_finished(stream)
            return True
        return True

    async def stop_stream(self, stream: ManagedStream):
        stream.stop_download()
        if not stream.finished and stream.output_file_exists:
            try:
                os.remove(stream.full_path)
            except OSError as err:
                log.warning("Failed to delete partial download %s from downloads directory: %s", stream.full_path,
                            str(err))
        if stream.running:
            stream.update_status(ManagedStream.STATUS_STOPPED)
            await self.storage.change_file_status(stream.stream_hash, ManagedStream.STATUS_STOPPED)

    def make_downloader(self, sd_hash: str, download_directory: str, file_name: str):
        return StreamDownloader(
            self.loop, self.config, self.blob_manager, sd_hash, download_directory, file_name
        )

    async def recover_streams(self, file_infos: typing.List[typing.Dict]):
        to_restore = []

        async def recover_stream(sd_hash: str, stream_hash: str, stream_name: str,
                                 suggested_file_name: str, key: str) -> typing.Optional[StreamDescriptor]:
            sd_blob = self.blob_manager.get_blob(sd_hash)
            blobs = await self.storage.get_blobs_for_stream(stream_hash)
            descriptor = await StreamDescriptor.recover(
                self.blob_manager.blob_dir, sd_blob, stream_hash, stream_name, suggested_file_name, key, blobs
            )
            if not descriptor:
                return
            to_restore.append((descriptor, sd_blob))

        await asyncio.gather(*[
            recover_stream(
                file_info['sd_hash'], file_info['stream_hash'], binascii.unhexlify(file_info['stream_name']).decode(),
                binascii.unhexlify(file_info['suggested_file_name']).decode(), file_info['key']
            ) for file_info in file_infos
        ])

        if to_restore:
            await self.storage.recover_streams(to_restore, self.config.download_dir)
        log.info("Recovered %i/%i attempted streams", len(to_restore), len(file_infos))

    async def add_stream(self, rowid: int, sd_hash: str, file_name: str, download_directory: str, status: str,
                         claim: typing.Optional['StoredStreamClaim']):
        sd_blob = self.blob_manager.get_blob(sd_hash)
        if not sd_blob.get_is_verified():
            return
        try:
            descriptor = await self.blob_manager.get_stream_descriptor(sd_blob.blob_hash)
        except InvalidStreamDescriptorError as err:
            log.warning("Failed to start stream for sd %s - %s", sd_hash, str(err))
            return
        if status == ManagedStream.STATUS_RUNNING:
            downloader = self.make_downloader(descriptor.sd_hash, download_directory, file_name)
        else:
            downloader = None
        stream = ManagedStream(
            self.loop, self.blob_manager, rowid, descriptor, download_directory, file_name, downloader, status, claim
        )
        self.streams.add(stream)
        self.storage.content_claim_callbacks[stream.stream_hash] = lambda: self._update_content_claim(stream)

    async def load_streams_from_database(self):
        to_recover = []
        for file_info in await self.storage.get_all_lbry_files():
            if not self.blob_manager.get_blob(file_info['sd_hash']).get_is_verified():
                to_recover.append(file_info)

        if to_recover:
            log.info("Attempting to recover %i streams", len(to_recover))
            await self.recover_streams(to_recover)

        to_start = []
        for file_info in await self.storage.get_all_lbry_files():
            if self.blob_manager.get_blob(file_info['sd_hash']).get_is_verified():
                to_start.append(file_info)
        log.info("Initializing %i files", len(to_start))

        await asyncio.gather(*[
            self.add_stream(
                file_info['rowid'], file_info['sd_hash'], binascii.unhexlify(file_info['file_name']).decode(),
                binascii.unhexlify(file_info['download_directory']).decode(), file_info['status'],
                file_info['claim']
            ) for file_info in to_start
        ])
        log.info("Started stream manager with %i files", len(self.streams))

    async def resume(self):
        if self.node:
            await self.node.joined.wait()
        else:
            log.warning("no DHT node given, resuming downloads trusting that we can contact reflector")
        t = [
            (stream.start_download(self.node), self.wait_for_stream_finished(stream))
            for stream in self.streams if stream.status == ManagedStream.STATUS_RUNNING
        ]
        if t:
            log.info("resuming %i downloads", len(t))

    async def reflect_streams(self):
        while True:
            if self.config.reflect_streams and self.config.reflector_servers:
                sd_hashes = await self.storage.get_streams_to_re_reflect()
                streams = list(filter(lambda s: s.sd_hash in sd_hashes, self.streams))
                batch = []
                while streams:
                    stream = streams.pop()
                    if not stream.fully_reflected.is_set():
                        host, port = random.choice(self.config.reflector_servers)
                        batch.append(stream.upload_to_reflector(host, port))
                    if len(batch) >= self.config.concurrent_reflector_uploads:
                        await asyncio.gather(*batch)
                        batch = []
                if batch:
                    await asyncio.gather(*batch)
            await asyncio.sleep(300, loop=self.loop)

    async def start(self):
        await self.load_streams_from_database()
        self.resume_downloading_task = self.loop.create_task(self.resume())
        self.re_reflect_task = self.loop.create_task(self.reflect_streams())

    def stop(self):
        if self.resume_downloading_task and not self.resume_downloading_task.done():
            self.resume_downloading_task.cancel()
        if self.re_reflect_task and not self.re_reflect_task.done():
            self.re_reflect_task.cancel()
        while self.streams:
            stream = self.streams.pop()
            stream.stop_download()
        while self.update_stream_finished_futs:
            self.update_stream_finished_futs.pop().cancel()
        while self.running_reflector_uploads:
            self.running_reflector_uploads.pop().cancel()

    async def create_stream(self, file_path: str, key: typing.Optional[bytes] = None,
                            iv_generator: typing.Optional[typing.Generator[bytes, None, None]] = None) -> ManagedStream:
        stream = await ManagedStream.create(self.loop, self.blob_manager, file_path, key, iv_generator)
        self.streams.add(stream)
        self.storage.content_claim_callbacks[stream.stream_hash] = lambda: self._update_content_claim(stream)
        if self.config.reflect_streams and self.config.reflector_servers:
            host, port = random.choice(self.config.reflector_servers)
            task = self.loop.create_task(stream.upload_to_reflector(host, port))
            self.running_reflector_uploads.append(task)
            task.add_done_callback(
                lambda _: None
                if task not in self.running_reflector_uploads else self.running_reflector_uploads.remove(task)
            )
        return stream

    async def delete_stream(self, stream: ManagedStream, delete_file: typing.Optional[bool] = False):
        await self.stop_stream(stream)
        if stream in self.streams:
            self.streams.remove(stream)
        blob_hashes = [stream.sd_hash] + [b.blob_hash for b in stream.descriptor.blobs[:-1]]
        await self.blob_manager.delete_blobs(blob_hashes, delete_from_db=False)
        await self.storage.delete_stream(stream.descriptor)
        if delete_file and stream.output_file_exists:
            os.remove(stream.full_path)

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
        if 'full_status' in search_by:
            del search_by['full_status']
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

    def wait_for_stream_finished(self, stream: ManagedStream):
        async def _wait_for_stream_finished():
            if stream.downloader and stream.running:
                await stream.downloader.stream_finished_event.wait()
                stream.update_status(ManagedStream.STATUS_FINISHED)
                if self.analytics_manager:
                    self.loop.create_task(self.analytics_manager.send_download_finished(
                        stream.download_id, stream.claim_name, stream.sd_hash
                    ))

        task = self.loop.create_task(_wait_for_stream_finished())
        self.update_stream_finished_futs.append(task)
        task.add_done_callback(
            lambda _: None if task not in self.update_stream_finished_futs else
            self.update_stream_finished_futs.remove(task)
        )

    async def _store_stream(self, downloader: StreamDownloader) -> int:
        file_name = os.path.basename(downloader.output_path)
        download_directory = os.path.dirname(downloader.output_path)
        if not await self.storage.stream_exists(downloader.sd_hash):
            await self.storage.store_stream(downloader.sd_blob, downloader.descriptor)
        if not await self.storage.file_exists(downloader.sd_hash):
            return await self.storage.save_downloaded_file(
                downloader.descriptor.stream_hash, file_name, download_directory,
                0.0
            )
        else:
            return await self.storage.rowid_for_stream(downloader.descriptor.stream_hash)

    async def _check_update_or_replace(self, outpoint: str, claim_id: str, claim: Claim) -> typing.Tuple[
                                                       typing.Optional[ManagedStream], typing.Optional[ManagedStream]]:
        existing = self.get_filtered_streams(outpoint=outpoint)
        if existing:
            await self.start_stream(existing[0])
            return existing[0], None
        existing = self.get_filtered_streams(sd_hash=claim.stream.hash)
        if existing and existing[0].claim_id != claim_id:
            raise ResolveError(f"stream for {existing[0].claim_id} collides with existing "
                               f"download {claim_id}")
        if existing:
            log.info("claim contains a metadata only update to a stream we have")
            await self.storage.save_content_claim(
                existing[0].stream_hash, outpoint
            )
            await self._update_content_claim(existing[0])
            await self.start_stream(existing[0])
            return existing[0], None
        else:
            existing_for_claim_id = self.get_filtered_streams(claim_id=claim_id)
            if existing_for_claim_id:
                log.info("claim contains an update to a stream we have, downloading it")
                return None, existing_for_claim_id[0]
        return None, None

    async def start_downloader(self, got_descriptor_time: asyncio.Future, downloader: StreamDownloader,
                               download_id: str, outpoint: str, claim: Claim, resolved: typing.Dict,
                               file_name: typing.Optional[str] = None) -> ManagedStream:
        start_time = self.loop.time()
        downloader.download(self.node)
        await downloader.got_descriptor.wait()
        got_descriptor_time.set_result(self.loop.time() - start_time)
        rowid = await self._store_stream(downloader)
        await self.storage.save_content_claim(
            downloader.descriptor.stream_hash, outpoint
        )
        stream = ManagedStream(self.loop, self.blob_manager, rowid, downloader.descriptor, self.config.download_dir,
                               file_name, downloader, ManagedStream.STATUS_RUNNING, download_id=download_id)
        stream.set_claim(resolved, claim)
        await stream.downloader.wrote_bytes_event.wait()
        self.streams.add(stream)
        return stream

    async def _download_stream_from_uri(self, uri, timeout: float, exchange_rate_manager: 'ExchangeRateManager',
                                        file_name: typing.Optional[str] = None) -> ManagedStream:
        start_time = self.loop.time()
        parsed_uri = parse_lbry_uri(uri)
        if parsed_uri.is_channel:
            raise ResolveError("cannot download a channel claim, specify a /path")

        # resolve the claim
        resolved = (await self.wallet.resolve(uri)).get(uri, {})
        resolved = resolved if 'value' in resolved else resolved.get('claim')

        if not resolved:
            raise ResolveError(f"Failed to resolve stream at '{uri}'")
        if 'error' in resolved:
            raise ResolveError(f"error resolving stream: {resolved['error']}")

        claim = Claim.from_bytes(binascii.unhexlify(resolved['hex']))
        outpoint = f"{resolved['txid']}:{resolved['nout']}"
        resolved_time = self.loop.time() - start_time

        # resume or update an existing stream, if the stream changed download it and delete the old one after
        updated_stream, to_replace = await self._check_update_or_replace(outpoint, resolved['claim_id'], claim)
        if updated_stream:
            return updated_stream

        # check that the fee is payable
        fee_amount, fee_address = None, None
        if claim.stream.has_fee:
            fee_amount = round(exchange_rate_manager.convert_currency(
                claim.stream.fee.currency, "LBC", claim.stream.fee.amount
            ), 5)
            max_fee_amount = round(exchange_rate_manager.convert_currency(
                self.config.max_key_fee['currency'], "LBC", Decimal(self.config.max_key_fee['amount'])
            ), 5)
            if fee_amount > max_fee_amount:
                msg = f"fee of {fee_amount} exceeds max configured to allow of {max_fee_amount}"
                log.warning(msg)
                raise KeyFeeAboveMaxAllowed(msg)
            balance = await self.wallet.default_account.get_balance()
            if lbc_to_dewies(str(fee_amount)) > balance:
                msg = f"fee of {fee_amount} exceeds max available balance"
                log.warning(msg)
                raise InsufficientFundsError(msg)
            fee_address = claim.stream.fee.address

        # download the stream
        download_id = binascii.hexlify(generate_id()).decode()
        downloader = StreamDownloader(self.loop, self.config, self.blob_manager, claim.stream.hash,
                                      self.config.download_dir, file_name)

        stream = None
        descriptor_time_fut = self.loop.create_future()
        start_download_time = self.loop.time()
        time_to_descriptor = None
        time_to_first_bytes = None
        error = None
        try:
            stream = await asyncio.wait_for(
                asyncio.ensure_future(
                    self.start_downloader(descriptor_time_fut, downloader, download_id, outpoint, claim, resolved,
                                          file_name)
                ), timeout
            )
            time_to_descriptor = await descriptor_time_fut
            time_to_first_bytes = self.loop.time() - start_download_time - time_to_descriptor
            self.wait_for_stream_finished(stream)
            if fee_address and fee_amount and not to_replace:
                stream.tx = await self.wallet.send_amount_to_address(
                    lbc_to_dewies(str(fee_amount)), fee_address.encode('latin1'))
            elif to_replace:  # delete old stream now that the replacement has started downloading
                await self.delete_stream(to_replace)
        except asyncio.TimeoutError:
            if descriptor_time_fut.done():
                time_to_descriptor = descriptor_time_fut.result()
                error = DownloadDataTimeout(downloader.sd_hash)
                self.blob_manager.delete_blob(downloader.sd_hash)
                await self.storage.delete_stream(downloader.descriptor)
            else:
                descriptor_time_fut.cancel()
                error = DownloadSDTimeout(downloader.sd_hash)
            if stream:
                await self.stop_stream(stream)
            else:
                downloader.stop()
        if error:
            log.warning(error)
        if self.analytics_manager:
            self.loop.create_task(
                self.analytics_manager.send_time_to_first_bytes(
                    resolved_time, self.loop.time() - start_time, download_id, parse_lbry_uri(uri).name, outpoint,
                    None if not stream else len(stream.downloader.blob_downloader.active_connections),
                    None if not stream else len(stream.downloader.blob_downloader.scores),
                    False if not downloader else downloader.added_fixed_peers,
                    self.config.fixed_peer_delay if not downloader else downloader.fixed_peers_delay,
                    claim.stream.hash, time_to_descriptor,
                    None if not (stream and stream.descriptor) else stream.descriptor.blobs[0].blob_hash,
                    None if not (stream and stream.descriptor) else stream.descriptor.blobs[0].length,
                    time_to_first_bytes, None if not error else error.__class__.__name__
                )
            )
        if error:
            raise error
        return stream

    async def download_stream_from_uri(self, uri, exchange_rate_manager: 'ExchangeRateManager',
                                       file_name: typing.Optional[str] = None,
                                       timeout: typing.Optional[float] = None) -> ManagedStream:
        timeout = timeout or self.config.download_timeout
        if uri in self.starting_streams:
            return await self.starting_streams[uri]
        fut = asyncio.Future(loop=self.loop)
        self.starting_streams[uri] = fut
        try:
            stream = await self._download_stream_from_uri(uri, timeout, exchange_rate_manager, file_name)
            fut.set_result(stream)
        except Exception as err:
            fut.set_exception(err)
        try:
            return await fut
        finally:
            del self.starting_streams[uri]
