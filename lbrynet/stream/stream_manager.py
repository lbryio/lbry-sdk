import os
import asyncio
import typing
import binascii
import logging
import random
from lbrynet.error import ResolveError, InvalidStreamDescriptorError, KeyFeeAboveMaxAllowed, InsufficientFundsError, \
    DownloadDataTimeout, DownloadSDTimeout
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
    from lbrynet.extras.daemon.storage import SQLiteStorage
    from lbrynet.extras.wallet import LbryWalletManager
    from lbrynet.extras.daemon.exchange_rate_manager import ExchangeRateManager

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

    async def _update_content_claim(self, stream: ManagedStream):
        claim_info = await self.storage.get_content_claim(stream.stream_hash)
        stream.set_claim(claim_info, smart_decode(claim_info['value']))

    async def start_stream(self, stream: ManagedStream) -> bool:
        """
        Resume or rebuild a partial or completed stream
        """

        path = os.path.join(stream.download_directory, stream.file_name)

        if not stream.running and not os.path.isfile(path):
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
                await asyncio.wait_for(self.loop.create_task(stream.downloader.got_descriptor.wait()),
                                       self.config.download_timeout)
            except asyncio.TimeoutError:
                await self.stop_stream(stream)
                if stream in self.streams:
                    self.streams.remove(stream)
                return False
            file_name = os.path.basename(stream.downloader.output_path)
            await self.storage.change_file_download_dir_and_file_name(
                stream.stream_hash, self.config.download_dir, file_name
            )
            self.wait_for_stream_finished(stream)
            return True
        return True

    async def stop_stream(self, stream: ManagedStream):
        stream.stop_download()
        if not stream.finished and os.path.isfile(stream.full_path):
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

    async def add_stream(self, sd_hash: str, file_name: str, download_directory: str, status: str, claim):
        sd_blob = self.blob_manager.get_blob(sd_hash)
        if sd_blob.get_is_verified():
            try:
                descriptor = await self.blob_manager.get_stream_descriptor(sd_blob.blob_hash)
            except InvalidStreamDescriptorError as err:
                log.warning("Failed to start stream for sd %s - %s", sd_hash, str(err))
                return

            downloader = self.make_downloader(descriptor.sd_hash, download_directory, file_name)
            stream = ManagedStream(
                self.loop, self.blob_manager, descriptor, download_directory, file_name, downloader, status, claim
            )
            self.streams.add(stream)
            self.storage.content_claim_callbacks[stream.stream_hash] = lambda: self._update_content_claim(stream)

    async def load_streams_from_database(self):
        log.info("Initializing stream manager from %s", self.storage._db_path)
        file_infos = await self.storage.get_all_lbry_files()
        log.info("Initializing %i files", len(file_infos))
        await asyncio.gather(*[
            self.add_stream(
                file_info['sd_hash'], binascii.unhexlify(file_info['file_name']).decode(),
                binascii.unhexlify(file_info['download_directory']).decode(), file_info['status'], file_info['claim']
            ) for file_info in file_infos
        ])
        log.info("Started stream manager with %i files", len(file_infos))

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

    async def create_stream(self, file_path: str, key: typing.Optional[bytes] = None,
                            iv_generator: typing.Optional[typing.Generator[bytes, None, None]] = None) -> ManagedStream:
        stream = await ManagedStream.create(self.loop, self.blob_manager, file_path, key, iv_generator)
        self.streams.add(stream)
        self.storage.content_claim_callbacks[stream.stream_hash] = lambda: self._update_content_claim(stream)
        if self.config.reflect_streams and self.config.reflector_servers:
            host, port = random.choice(self.config.reflector_servers)
            self.loop.create_task(stream.upload_to_reflector(host, port))
        return stream

    async def delete_stream(self, stream: ManagedStream, delete_file: typing.Optional[bool] = False):
        await self.stop_stream(stream)
        if stream in self.streams:
            self.streams.remove(stream)
        blob_hashes = [stream.sd_hash] + [b.blob_hash for b in stream.descriptor.blobs[:-1]]
        await self.blob_manager.delete_blobs(blob_hashes, delete_from_db=False)
        await self.storage.delete_stream(stream.descriptor)
        if delete_file and os.path.isfile(stream.full_path):
            os.remove(stream.full_path)

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
            raise DownloadSDTimeout(downloader.sd_hash)
        file_name = os.path.basename(downloader.output_path)
        download_directory = os.path.dirname(downloader.output_path)
        if not await self.blob_manager.storage.stream_exists(downloader.sd_hash):
            await self.blob_manager.storage.store_stream(downloader.sd_blob, downloader.descriptor)
        if not await self.blob_manager.storage.file_exists(downloader.sd_hash):
            await self.blob_manager.storage.save_downloaded_file(
                downloader.descriptor.stream_hash, file_name, download_directory,
                0.0
            )
        await self.blob_manager.storage.save_content_claim(
            downloader.descriptor.stream_hash, f"{claim_info['txid']}:{claim_info['nout']}"
        )
        stream = ManagedStream(self.loop, self.blob_manager, downloader.descriptor, download_directory,
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
                await self.wallet.send_amount_to_address(lbc_to_dewies(str(fee_amount)), fee_address.encode('latin1'))
            return stream
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            if stream_task.exception():
                raise stream_task.exception()
            return
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
                if fee_amount > balance:
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
