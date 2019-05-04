import os
import asyncio
import typing
import binascii
import logging
import random
from decimal import Decimal
from aiohttp.web import Request
from lbrynet.error import ResolveError, InvalidStreamDescriptorError, KeyFeeAboveMaxAllowed, InsufficientFundsError
from lbrynet.error import ResolveTimeout
from lbrynet.utils import cache_concurrent
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.stream.managed_stream import ManagedStream
from lbrynet.schema.claim import Claim
from lbrynet.schema.uri import parse_lbry_uri
from lbrynet.extras.daemon.storage import lbc_to_dewies
if typing.TYPE_CHECKING:
    from lbrynet.conf import Config
    from lbrynet.blob.blob_manager import BlobManager
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


def path_or_none(p) -> typing.Optional[str]:
    return None if p == '{stream}' else binascii.unhexlify(p).decode()


class StreamManager:
    def __init__(self, loop: asyncio.BaseEventLoop, config: 'Config', blob_manager: 'BlobManager',
                 wallet: 'LbryWalletManager', storage: 'SQLiteStorage', node: typing.Optional['Node'],
                 analytics_manager: typing.Optional['AnalyticsManager'] = None):
        self.loop = loop
        self.config = config
        self.blob_manager = blob_manager
        self.wallet = wallet
        self.storage = storage
        self.node = node
        self.analytics_manager = analytics_manager
        self.streams: typing.Dict[str, ManagedStream] = {}
        self.resume_downloading_task: asyncio.Task = None
        self.re_reflect_task: asyncio.Task = None
        self.update_stream_finished_futs: typing.List[asyncio.Future] = []
        self.running_reflector_uploads: typing.List[asyncio.Task] = []
        self.started = asyncio.Event(loop=self.loop)

    async def _update_content_claim(self, stream: ManagedStream):
        claim_info = await self.storage.get_content_claim(stream.stream_hash)
        self.streams.setdefault(stream.sd_hash, stream).set_claim(claim_info, claim_info['value'])

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

        # if self.blob_manager._save_blobs:
        #     log.info("Recovered %i/%i attempted streams", len(to_restore), len(file_infos))

    async def add_stream(self, rowid: int, sd_hash: str, file_name: typing.Optional[str],
                         download_directory: typing.Optional[str], status: str,
                         claim: typing.Optional['StoredStreamClaim']):
        try:
            descriptor = await self.blob_manager.get_stream_descriptor(sd_hash)
        except InvalidStreamDescriptorError as err:
            log.warning("Failed to start stream for sd %s - %s", sd_hash, str(err))
            return
        stream = ManagedStream(
            self.loop, self.config, self.blob_manager, descriptor.sd_hash, download_directory, file_name, status,
            claim, rowid=rowid, descriptor=descriptor, analytics_manager=self.analytics_manager
        )
        self.streams[sd_hash] = stream

    async def load_streams_from_database(self):
        to_recover = []
        to_start = []

        # this will set streams marked as finished and are missing blobs as being stopped
        # await self.storage.sync_files_to_blobs()
        for file_info in await self.storage.get_all_lbry_files():
            # if the sd blob is not verified, try to reconstruct it from the database
            # this could either be because the blob files were deleted manually or save_blobs was not true when
            # the stream was downloaded
            if not self.blob_manager.is_blob_verified(file_info['sd_hash']):
                to_recover.append(file_info)
            to_start.append(file_info)
        if to_recover:
            await self.recover_streams(to_recover)

        log.info("Initializing %i files", len(to_start))
        if to_start:
            await asyncio.gather(*[
                self.add_stream(
                    file_info['rowid'], file_info['sd_hash'], path_or_none(file_info['file_name']),
                    path_or_none(file_info['download_directory']), file_info['status'],
                    file_info['claim']
                ) for file_info in to_start
            ])
        log.info("Started stream manager with %i files", len(self.streams))

    async def resume(self):
        if not self.node:
            log.warning("no DHT node given, resuming downloads trusting that we can contact reflector")
        t = [
            self.loop.create_task(
                stream.start(node=self.node, save_now=(stream.full_path is not None))
            ) for stream in self.streams.values() if stream.running
        ]
        if t:
            log.info("resuming %i downloads", len(t))
            await asyncio.gather(*t, loop=self.loop)

    async def reflect_streams(self):
        while True:
            if self.config.reflect_streams and self.config.reflector_servers:
                sd_hashes = await self.storage.get_streams_to_re_reflect()
                sd_hashes = [sd for sd in sd_hashes if sd in self.streams]
                batch = []
                while sd_hashes:
                    stream = self.streams[sd_hashes.pop()]
                    if self.blob_manager.is_blob_verified(stream.sd_hash) and stream.blobs_completed:
                        if not stream.fully_reflected.is_set():
                            host, port = random.choice(self.config.reflector_servers)
                            batch.append(stream.upload_to_reflector(host, port))
                    if len(batch) >= self.config.concurrent_reflector_uploads:
                        await asyncio.gather(*batch, loop=self.loop)
                        batch = []
                if batch:
                    await asyncio.gather(*batch, loop=self.loop)
            await asyncio.sleep(300, loop=self.loop)

    async def start(self):
        await self.load_streams_from_database()
        self.resume_downloading_task = self.loop.create_task(self.resume())
        self.re_reflect_task = self.loop.create_task(self.reflect_streams())
        self.started.set()

    def stop(self):
        if self.resume_downloading_task and not self.resume_downloading_task.done():
            self.resume_downloading_task.cancel()
        if self.re_reflect_task and not self.re_reflect_task.done():
            self.re_reflect_task.cancel()
        while self.streams:
            _, stream = self.streams.popitem()
            stream.stop_tasks()
        while self.update_stream_finished_futs:
            self.update_stream_finished_futs.pop().cancel()
        while self.running_reflector_uploads:
            self.running_reflector_uploads.pop().cancel()
        self.started.clear()
        log.info("finished stopping the stream manager")

    async def create_stream(self, file_path: str, key: typing.Optional[bytes] = None,
                            iv_generator: typing.Optional[typing.Generator[bytes, None, None]] = None) -> ManagedStream:
        stream = await ManagedStream.create(self.loop, self.config, self.blob_manager, file_path, key, iv_generator)
        self.streams[stream.sd_hash] = stream
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
        stream.stop_tasks()
        if stream.sd_hash in self.streams:
            del self.streams[stream.sd_hash]
        blob_hashes = [stream.sd_hash] + [b.blob_hash for b in stream.descriptor.blobs[:-1]]
        await self.blob_manager.delete_blobs(blob_hashes, delete_from_db=False)
        await self.storage.delete_stream(stream.descriptor)
        if delete_file and stream.output_file_exists:
            os.remove(stream.full_path)

    def get_stream_by_stream_hash(self, stream_hash: str) -> typing.Optional[ManagedStream]:
        streams = tuple(filter(lambda stream: stream.stream_hash == stream_hash, self.streams.values()))
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
            for stream in self.streams.values():
                for search, val in search_by.items():
                    if comparison_operators[comparison](getattr(stream, search), val):
                        streams.append(stream)
                        break
        else:
            streams = list(self.streams.values())
        if sort_by:
            streams.sort(key=lambda s: getattr(s, sort_by))
            if reverse:
                streams.reverse()
        return streams

    async def _check_update_or_replace(self, outpoint: str, claim_id: str, claim: Claim) -> typing.Tuple[
                                                       typing.Optional[ManagedStream], typing.Optional[ManagedStream]]:
        existing = self.get_filtered_streams(outpoint=outpoint)
        if existing:
            return existing[0], None
        existing = self.get_filtered_streams(sd_hash=claim.stream.source.sd_hash)
        if existing and existing[0].claim_id != claim_id:
            raise ResolveError(f"stream for {existing[0].claim_id} collides with existing download {claim_id}")
        if existing:
            log.info("claim contains a metadata only update to a stream we have")
            await self.storage.save_content_claim(
                existing[0].stream_hash, outpoint
            )
            await self._update_content_claim(existing[0])
            return existing[0], None
        else:
            existing_for_claim_id = self.get_filtered_streams(claim_id=claim_id)
            if existing_for_claim_id:
                log.info("claim contains an update to a stream we have, downloading it")
                return None, existing_for_claim_id[0]
        return None, None

    @cache_concurrent
    async def download_stream_from_uri(self, uri, exchange_rate_manager: 'ExchangeRateManager',
                                       timeout: typing.Optional[float] = None,
                                       file_name: typing.Optional[str] = None,
                                       download_directory: typing.Optional[str] = None,
                                       save_file: typing.Optional[bool] = None,
                                       resolve_timeout: float = 3.0) -> ManagedStream:
        timeout = timeout or self.config.download_timeout
        start_time = self.loop.time()
        resolved_time = None
        stream = None
        error = None
        outpoint = None
        if save_file is None:
            save_file = self.config.save_files
        if file_name and not save_file:
            save_file = True
        if save_file:
            download_directory = download_directory or self.config.download_dir
        else:
            download_directory = None

        try:
            # resolve the claim
            parsed_uri = parse_lbry_uri(uri)
            if parsed_uri.is_channel:
                raise ResolveError("cannot download a channel claim, specify a /path")
            try:
                resolved_result = await asyncio.wait_for(self.wallet.ledger.resolve(0, 1, uri), resolve_timeout)
            except asyncio.TimeoutError:
                raise ResolveTimeout(uri)
            await self.storage.save_claims_for_resolve([
                value for value in resolved_result.values() if 'error' not in value
            ])
            resolved = resolved_result.get(uri, {})
            resolved = resolved if 'value' in resolved else resolved.get('claim')
            if not resolved:
                raise ResolveError(f"Failed to resolve stream at '{uri}'")
            if 'error' in resolved:
                raise ResolveError(f"error resolving stream: {resolved['error']}")

            claim = Claim.from_bytes(binascii.unhexlify(resolved['protobuf']))
            outpoint = f"{resolved['txid']}:{resolved['nout']}"
            resolved_time = self.loop.time() - start_time

            # resume or update an existing stream, if the stream changed download it and delete the old one after
            updated_stream, to_replace = await self._check_update_or_replace(outpoint, resolved['claim_id'], claim)
            if updated_stream:
                log.info("already have stream for %s", uri)
                if save_file and updated_stream.output_file_exists:
                    save_file = False
                await updated_stream.start(node=self.node, timeout=timeout, save_now=save_file)
                return updated_stream

            content_fee = None

            # check that the fee is payable
            if not to_replace and claim.stream.has_fee:
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

                content_fee = await self.wallet.send_amount_to_address(
                    lbc_to_dewies(str(fee_amount)), fee_address.encode('latin1')
                )

                log.info("paid fee of %s for %s", fee_amount, uri)

            stream = ManagedStream(
                self.loop, self.config, self.blob_manager, claim.stream.source.sd_hash, download_directory,
                file_name, ManagedStream.STATUS_RUNNING, content_fee=content_fee,
                analytics_manager=self.analytics_manager
            )
            log.info("starting download for %s", uri)
            await stream.start(self.node, timeout, save_now=save_file)
            if to_replace:  # delete old stream now that the replacement has started downloading
                await self.delete_stream(to_replace)
            self.streams[stream.sd_hash] = stream
            stream.set_claim(resolved, claim)
            await self.storage.save_content_claim(stream.stream_hash, outpoint)
            return stream
        except Exception as err:  # forgive data timeout, dont delete stream
            error = err
            raise
        finally:
            if self.analytics_manager and (error or (stream and (stream.downloader.time_to_descriptor or
                                                                 stream.downloader.time_to_first_bytes))):
                self.loop.create_task(
                    self.analytics_manager.send_time_to_first_bytes(
                        resolved_time, self.loop.time() - start_time, None if not stream else stream.download_id,
                        uri, outpoint,
                        None if not stream else len(stream.downloader.blob_downloader.active_connections),
                        None if not stream else len(stream.downloader.blob_downloader.scores),
                        False if not stream else stream.downloader.added_fixed_peers,
                        self.config.fixed_peer_delay if not stream else stream.downloader.fixed_peers_delay,
                        None if not stream else stream.sd_hash,
                        None if not stream else stream.downloader.time_to_descriptor,
                        None if not (stream and stream.descriptor) else stream.descriptor.blobs[0].blob_hash,
                        None if not (stream and stream.descriptor) else stream.descriptor.blobs[0].length,
                        None if not stream else stream.downloader.time_to_first_bytes,
                        None if not error else error.__class__.__name__
                    )
                )

    async def stream_partial_content(self, request: Request, sd_hash: str):
        return await self.streams[sd_hash].stream_file(request, self.node)
