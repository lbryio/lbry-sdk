import os
import asyncio
import typing
import binascii
import logging
import random
from lbrynet.error import ResolveError, InvalidStreamDescriptorError, KeyFeeAboveMaxAllowed, InsufficientFundsError, \
    DownloadDataTimeout, DownloadSDTimeout
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.stream.downloader import StreamDownloader
from lbrynet.stream.managed_stream import ManagedStream
from lbrynet.schema.claim import ClaimDict
from lbrynet.schema.uri import parse_lbry_uri
from lbrynet.schema.decode import smart_decode
from lbrynet.extras.daemon.storage import lbc_to_dewies
if typing.TYPE_CHECKING:
    from lbrynet.conf import Config
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.dht.node import Node
    from lbrynet.extras.daemon.storage import SQLiteStorage, StoredStreamClaim
    from lbrynet.extras.wallet import LbryWalletManager
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
        self.re_reflect_task: asyncio.Task = None
        self.update_stream_finished_futs: typing.List[asyncio.Future] = []
        self.running_reflector_uploads: typing.List[asyncio.Task] = []

    async def _update_content_claim(self, stream: ManagedStream):
        claim_info = await self.storage.get_content_claim(stream.stream_hash)
        stream.set_claim(claim_info, smart_decode(claim_info['value']))

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

    def wait_for_stream_finished(self, stream: ManagedStream):
        async def _wait_for_stream_finished():
            if stream.downloader and stream.running:
                await stream.downloader.stream_finished_event.wait()
                stream.update_status(ManagedStream.STATUS_FINISHED)
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
            raise DownloadSDTimeout(downloader.sd_hash)
        rowid = await self._store_stream(downloader)
        await self.storage.save_content_claim(
            downloader.descriptor.stream_hash, f"{claim_info['txid']}:{claim_info['nout']}"
        )
        stream = ManagedStream(self.loop, self.blob_manager, rowid, downloader.descriptor, download_directory,
                               file_name, downloader, ManagedStream.STATUS_RUNNING)
        stream.set_claim(claim_info, claim)
        self.streams.add(stream)
        try:
            await stream.downloader.wrote_bytes_event.wait()
            self.wait_for_stream_finished(stream)
            return stream
        except asyncio.CancelledError:
            downloader.stop()
            log.debug("stopped stream")
        await self.stop_stream(stream)
        raise DownloadDataTimeout(downloader.sd_hash)

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

    async def download_stream_from_claim(self, node: 'Node', claim_info: typing.Dict,
                                         file_name: typing.Optional[str] = None,
                                         timeout: typing.Optional[float] = 60,
                                         fee_amount: typing.Optional[float] = 0.0,
                                         fee_address: typing.Optional[str] = None,
                                         should_pay: typing.Optional[bool] = True) -> typing.Optional[ManagedStream]:
        claim = ClaimDict.load_dict(claim_info['value'])
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
            if should_pay and fee_address and fee_amount:
                stream.tx = await self.wallet.send_amount_to_address(
                    lbc_to_dewies(str(fee_amount)), fee_address.encode('latin1'))
            return stream
        except asyncio.TimeoutError as e:
            if stream_task.exception():
                raise stream_task.exception()
        finally:
            if sd_hash in self.starting_streams:
                del self.starting_streams[sd_hash]

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

    async def download_stream_from_uri(self, uri, exchange_rate_manager: 'ExchangeRateManager',
                                       file_name: typing.Optional[str] = None,
                                       timeout: typing.Optional[float] = None) -> typing.Optional[ManagedStream]:
        timeout = timeout or self.config.download_timeout
        parsed_uri = parse_lbry_uri(uri)
        if parsed_uri.is_channel:
            raise ResolveError("cannot download a channel claim, specify a /path")

        resolved = (await self.wallet.resolve(uri)).get(uri, {})
        resolved = resolved if 'value' in resolved else resolved.get('claim')

        if not resolved:
            raise ResolveError(
                "Failed to resolve stream at lbry://{}".format(uri.replace("lbry://", ""))
            )
        if 'error' in resolved:
            raise ResolveError(f"error resolving stream: {resolved['error']}")

        claim = ClaimDict.load_dict(resolved['value'])
        fee_amount, fee_address = None, None
        if claim.has_fee:
            fee_amount = round(exchange_rate_manager.convert_currency(
                    claim.source_fee.currency, "LBC", claim.source_fee.amount
                ), 5)
            max_fee_amount = round(exchange_rate_manager.convert_currency(
                self.config.max_key_fee['currency'], "LBC", self.config.max_key_fee['amount']
            ), 5)
            if fee_amount > max_fee_amount:
                msg = f"fee of {fee_amount} exceeds max configured to allow of {max_fee_amount}"
                log.warning(msg)
                raise KeyFeeAboveMaxAllowed(msg)
            else:
                balance = await self.wallet.default_account.get_balance()
                if lbc_to_dewies(str(fee_amount)) > balance:
                    msg = f"fee of {fee_amount} exceeds max available balance"
                    log.warning(msg)
                    raise InsufficientFundsError(msg)
            fee_address = claim.source_fee.address.decode()
        outpoint = f"{resolved['txid']}:{resolved['nout']}"
        existing = self.get_filtered_streams(outpoint=outpoint)

        if not existing:
            existing.extend(self.get_filtered_streams(sd_hash=claim.source_hash.decode()))
            if existing and existing[0].claim_id != resolved['claim_id']:
                raise Exception(f"stream for {existing[0].claim_id} collides with existing "
                                f"download {resolved['claim_id']}")
            elif not existing:
                existing.extend(self.get_filtered_streams(claim_id=resolved['claim_id']))
            if existing and existing[0].sd_hash != claim.source_hash.decode():
                log.info("claim contains an update to a stream we have, downloading it")
                stream = await self.download_stream_from_claim(
                    self.node, resolved, file_name, timeout, fee_amount, fee_address, False
                )
                log.info("started new stream, deleting old one")
                await self.delete_stream(existing[0])
                return stream
            elif existing:
                log.info("already have matching stream for %s", uri)
                stream = existing[0]
                await self.start_stream(stream)
                return stream
        else:
            stream = existing[0]
            await self.start_stream(stream)
            return stream
        log.info("download stream from %s", uri)
        return await self.download_stream_from_claim(
                self.node, resolved, file_name, timeout, fee_amount, fee_address
        )
