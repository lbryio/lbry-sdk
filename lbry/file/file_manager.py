import asyncio
import logging
import typing
from typing import Optional
from aiohttp.web import Request
from lbry.error import ResolveError, DownloadSDTimeoutError, InsufficientFundsError
from lbry.error import ResolveTimeoutError, DownloadDataTimeoutError, KeyFeeAboveMaxAllowedError
from lbry.stream.managed_stream import ManagedStream
from lbry.utils import cache_concurrent
from lbry.schema.url import URL
from lbry.wallet.dewies import dewies_to_lbc
from lbry.file.source_manager import SourceManager
from lbry.file.source import ManagedDownloadSource
if typing.TYPE_CHECKING:
    from lbry.conf import Config
    from lbry.extras.daemon.analytics import AnalyticsManager
    from lbry.extras.daemon.storage import SQLiteStorage
    from lbry.wallet import WalletManager
    from lbry.extras.daemon.exchange_rate_manager import ExchangeRateManager

log = logging.getLogger(__name__)


class FileManager:
    def __init__(self, loop: asyncio.AbstractEventLoop, config: 'Config', wallet_manager: 'WalletManager',
                 storage: 'SQLiteStorage', analytics_manager: Optional['AnalyticsManager'] = None):
        self.loop = loop
        self.config = config
        self.wallet_manager = wallet_manager
        self.storage = storage
        self.analytics_manager = analytics_manager
        self.source_managers: typing.Dict[str, SourceManager] = {}
        self.started = asyncio.Event()

    @property
    def streams(self):
        return self.source_managers['stream']._sources

    async def create_stream(self, file_path: str, key: Optional[bytes] = None, **kwargs) -> ManagedDownloadSource:
        if 'stream' in self.source_managers:
            return await self.source_managers['stream'].create(file_path, key, **kwargs)
        raise NotImplementedError

    async def start(self):
        await asyncio.gather(*(source_manager.start() for source_manager in self.source_managers.values()))
        for manager in self.source_managers.values():
            await manager.started.wait()
        self.started.set()

    def stop(self):
        for manager in self.source_managers.values():
            # fixme: pop or not?
            manager.stop()
        self.started.clear()

    @cache_concurrent
    async def download_from_uri(self, uri, exchange_rate_manager: 'ExchangeRateManager',
                                timeout: Optional[float] = None, file_name: Optional[str] = None,
                                download_directory: Optional[str] = None,
                                save_file: Optional[bool] = None, resolve_timeout: float = 3.0,
                                wallet: Optional['Wallet'] = None) -> ManagedDownloadSource:

        wallet = wallet or self.wallet_manager.default_wallet
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

        payment = None
        try:
            # resolve the claim
            if not URL.parse(uri).has_stream:
                raise ResolveError("cannot download a channel claim, specify a /path")
            try:
                resolved_result = await asyncio.wait_for(
                    self.wallet_manager.ledger.resolve(wallet.accounts, [uri]),
                    resolve_timeout
                )
            except asyncio.TimeoutError:
                raise ResolveTimeoutError(uri)
            except Exception as err:
                if isinstance(err, asyncio.CancelledError):
                    raise
                log.exception("Unexpected error resolving stream:")
                raise ResolveError(f"Unexpected error resolving stream: {str(err)}")
            if not resolved_result:
                raise ResolveError(f"Failed to resolve stream at '{uri}'")
            if 'error' in resolved_result:
                raise ResolveError(f"Unexpected error resolving uri for download: {resolved_result['error']}")

            txo = resolved_result[uri]
            claim = txo.claim
            outpoint = f"{txo.tx_ref.id}:{txo.position}"
            resolved_time = self.loop.time() - start_time
            await self.storage.save_claim_from_output(self.wallet_manager.ledger, txo)

            ####################
            # update or replace
            ####################

            if claim.stream.source.bt_infohash:
                source_manager = self.source_managers['torrent']
            else:
                source_manager = self.source_managers['stream']

            # resume or update an existing stream, if the stream changed: download it and delete the old one after
            existing = self.get_filtered(sd_hash=claim.stream.source.sd_hash)
            to_replace, updated_stream = None, None
            if existing and existing[0].claim_id != txo.claim_id:
                raise ResolveError(f"stream for {existing[0].claim_id} collides with existing download {txo.claim_id}")
            if existing:
                log.info("claim contains a metadata only update to a stream we have")
                await self.storage.save_content_claim(
                    existing[0].stream_hash, outpoint
                )
                await source_manager._update_content_claim(existing[0])
                updated_stream = existing[0]
            else:
                existing_for_claim_id = self.get_filtered(claim_id=txo.claim_id)
                if existing_for_claim_id:
                    log.info("claim contains an update to a stream we have, downloading it")
                    if save_file and existing_for_claim_id[0].output_file_exists:
                        save_file = False
                    await existing_for_claim_id[0].start(timeout=timeout, save_now=save_file)
                    if not existing_for_claim_id[0].output_file_exists and (
                            save_file or file_name or download_directory):
                        await existing_for_claim_id[0].save_file(
                            file_name=file_name, download_directory=download_directory
                        )
                    to_replace = existing_for_claim_id[0]

            # resume or update an existing stream, if the stream changed: download it and delete the old one after
            if updated_stream:
                log.info("already have stream for %s", uri)
                if save_file and updated_stream.output_file_exists:
                    save_file = False
                await updated_stream.start(timeout=timeout, save_now=save_file)
                if not updated_stream.output_file_exists and (save_file or file_name or download_directory):
                    await updated_stream.save_file(
                        file_name=file_name, download_directory=download_directory
                    )
                return updated_stream


            ####################
            # pay fee
            ####################

            if not to_replace and txo.has_price and not txo.purchase_receipt:
                payment = await self.wallet_manager.create_purchase_transaction(
                    wallet.accounts, txo, exchange_rate_manager
                )

            ####################
            # make downloader and wait for start
            ####################

            if not claim.stream.source.bt_infohash:
                stream = ManagedStream(
                    self.loop, self.config, source_manager.blob_manager, claim.stream.source.sd_hash,
                    download_directory, file_name, ManagedStream.STATUS_RUNNING, content_fee=payment,
                    analytics_manager=self.analytics_manager
                )
            else:
                stream = None
            log.info("starting download for %s", uri)

            before_download = self.loop.time()
            await stream.start(timeout, save_file)

            ####################
            # success case: delete to_replace if applicable, broadcast fee payment
            ####################

            if to_replace:  # delete old stream now that the replacement has started downloading
                await source_manager.delete(to_replace)

            if payment is not None:
                await self.wallet_manager.broadcast_or_release(payment)
                payment = None  # to avoid releasing in `finally` later
                log.info("paid fee of %s for %s", dewies_to_lbc(stream.content_fee.outputs[0].amount), uri)
                await self.storage.save_content_fee(stream.stream_hash, stream.content_fee)

            source_manager.add(stream)

            await self.storage.save_content_claim(stream.stream_hash, outpoint)
            if save_file:
                await asyncio.wait_for(stream.save_file(), timeout - (self.loop.time() - before_download),
                                       loop=self.loop)
            return stream
        except asyncio.TimeoutError:
            error = DownloadDataTimeoutError(stream.sd_hash)
            raise error
        except Exception as err:  # forgive data timeout, don't delete stream
            expected = (DownloadSDTimeoutError, DownloadDataTimeoutError, InsufficientFundsError,
                        KeyFeeAboveMaxAllowedError)
            if isinstance(err, expected):
                log.warning("Failed to download %s: %s", uri, str(err))
            elif isinstance(err, asyncio.CancelledError):
                pass
            else:
                log.exception("Unexpected error downloading stream:")
            error = err
            raise
        finally:
            if payment is not None:
                # payment is set to None after broadcasting, if we're here an exception probably happened
                await self.wallet_manager.ledger.release_tx(payment)
            if self.analytics_manager and (error or (stream and (stream.downloader.time_to_descriptor or
                                                                 stream.downloader.time_to_first_bytes))):
                server = self.wallet_manager.ledger.network.client.server
                self.loop.create_task(
                    self.analytics_manager.send_time_to_first_bytes(
                        resolved_time, self.loop.time() - start_time, None if not stream else stream.download_id,
                        uri, outpoint,
                        None if not stream else len(stream.downloader.blob_downloader.active_connections),
                        None if not stream else len(stream.downloader.blob_downloader.scores),
                        None if not stream else len(stream.downloader.blob_downloader.connection_failures),
                        False if not stream else stream.downloader.added_fixed_peers,
                        self.config.fixed_peer_delay if not stream else stream.downloader.fixed_peers_delay,
                        None if not stream else stream.sd_hash,
                        None if not stream else stream.downloader.time_to_descriptor,
                        None if not (stream and stream.descriptor) else stream.descriptor.blobs[0].blob_hash,
                        None if not (stream and stream.descriptor) else stream.descriptor.blobs[0].length,
                        None if not stream else stream.downloader.time_to_first_bytes,
                        None if not error else error.__class__.__name__,
                        None if not error else str(error),
                        None if not server else f"{server[0]}:{server[1]}"
                    )
                )

    async def stream_partial_content(self, request: Request, sd_hash: str):
        return await self.source_managers['stream'].stream_partial_content(request, sd_hash)

    def get_filtered(self, *args, **kwargs) -> typing.List[ManagedDownloadSource]:
        """
        Get a list of filtered and sorted ManagedStream objects

        :param sort_by: field to sort by
        :param reverse: reverse sorting
        :param comparison: comparison operator used for filtering
        :param search_by: fields and values to filter by
        """
        return sum((manager.get_filtered(*args, **kwargs) for manager in self.source_managers.values()), [])

    async def delete(self, source: ManagedDownloadSource, delete_file=False):
        for manager in self.source_managers.values():
            return await manager.delete(source, delete_file)
