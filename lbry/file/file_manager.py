import time
import asyncio
import binascii
import logging
import typing
from typing import Optional
from aiohttp.web import Request
from lbry.error import ResolveError, InvalidStreamDescriptorError, DownloadSDTimeoutError, InsufficientFundsError
from lbry.error import ResolveTimeoutError, DownloadDataTimeoutError, KeyFeeAboveMaxAllowedError
from lbry.utils import cache_concurrent
from lbry.schema.claim import Claim
from lbry.schema.url import URL
from lbry.wallet.dewies import dewies_to_lbc
from lbry.wallet.transaction import Output
from lbry.file.source_manager import SourceManager
from lbry.file.source import ManagedDownloadSource
if typing.TYPE_CHECKING:
    from lbry.conf import Config
    from lbry.extras.daemon.analytics import AnalyticsManager
    from lbry.extras.daemon.storage import SQLiteStorage
    from lbry.wallet import LbryWalletManager
    from lbry.extras.daemon.exchange_rate_manager import ExchangeRateManager

log = logging.getLogger(__name__)


def path_or_none(p) -> Optional[str]:
    if not p:
        return
    return binascii.unhexlify(p).decode()


class FileManager:
    def __init__(self, loop: asyncio.AbstractEventLoop, config: 'Config', wallet_manager: 'LbryWalletManager',
                 storage: 'SQLiteStorage', analytics_manager: Optional['AnalyticsManager'] = None):
        self.loop = loop
        self.config = config
        self.wallet_manager = wallet_manager
        self.storage = storage
        self.analytics_manager = analytics_manager
        self.source_managers: typing.Dict[str, SourceManager] = {}

    async def start(self):
        await asyncio.gather(*(source_manager.start() for source_manager in self.source_managers.values()))

    def stop(self):
        while self.source_managers:
            _, source_manager = self.source_managers.popitem()
            source_manager.stop()

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

            await self.storage.save_claims(
                resolved_result, self.wallet_manager.ledger
            )

            txo = resolved_result[uri]
            claim = txo.claim
            outpoint = f"{txo.tx_ref.id}:{txo.position}"
            resolved_time = self.loop.time() - start_time

            ####################
            # update or replace
            ####################

            if claim.stream.source.bt_infohash:
                source_manager = self.source_managers['torrent']
            else:
                source_manager = self.source_managers['stream']

            # resume or update an existing stream, if the stream changed: download it and delete the old one after
            existing = self.get_filtered(sd_hash=claim.stream.source.sd_hash)
            if existing and existing[0].claim_id != txo.claim_id:
                raise ResolveError(f"stream for {existing[0].claim_id} collides with existing download {txo.claim_id}")
            if existing:
                log.info("claim contains a metadata only update to a stream we have")
                await self.storage.save_content_claim(
                    existing[0].stream_hash, outpoint
                )
                await source_manager._update_content_claim(existing[0])
                return existing[0]
            else:
                existing_for_claim_id = self.get_filtered(claim_id=txo.claim_id)
                if existing_for_claim_id:
                    log.info("claim contains an update to a stream we have, downloading it")
                    if save_file and existing_for_claim_id[0].output_file_exists:
                        save_file = False
                    await existing_for_claim_id[0].start(node=self.node, timeout=timeout, save_now=save_file)
                    if not existing_for_claim_id[0].output_file_exists and (save_file or file_name or download_directory):
                        await existing_for_claim_id[0].save_file(
                            file_name=file_name, download_directory=download_directory, node=self.node
                        )
                    return existing_for_claim_id[0]






            if updated_stream:


            ####################
            # pay fee
            ####################

            if not to_replace and txo.has_price and not txo.purchase_receipt:
                payment = await manager.create_purchase_transaction(
                    wallet.accounts, txo, exchange_rate_manager
                )

            ####################
            # make downloader and wait for start
            ####################

            stream = ManagedStream(
                self.loop, self.config, self.blob_manager, claim.stream.source.sd_hash, download_directory,
                file_name, ManagedStream.STATUS_RUNNING, content_fee=payment,
                analytics_manager=self.analytics_manager
            )
            log.info("starting download for %s", uri)

            before_download = self.loop.time()
            await stream.start(self.node, timeout)
            stream.set_claim(resolved, claim)

            ####################
            # success case: delete to_replace if applicable, broadcast fee payment
            ####################

            if to_replace:  # delete old stream now that the replacement has started downloading
                await self.delete(to_replace)

            if payment is not None:
                await self.wallet_manager.broadcast_or_release(payment)
                payment = None  # to avoid releasing in `finally` later
                log.info("paid fee of %s for %s", dewies_to_lbc(stream.content_fee.outputs[0].amount), uri)
                await self.storage.save_content_fee(stream.stream_hash, stream.content_fee)

            self._sources[stream.sd_hash] = stream
            self.storage.content_claim_callbacks[stream.stream_hash] = lambda: self._update_content_claim(stream)

            await self.storage.save_content_claim(stream.stream_hash, outpoint)
            if save_file:
                await asyncio.wait_for(stream.save_file(node=self.node), timeout - (self.loop.time() - before_download),
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
        return await self._sources[sd_hash].stream_file(request, self.node)

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
        if comparison and comparison not in comparison_operators:
            raise ValueError(f"'{comparison}' is not a valid comparison")
        if 'full_status' in search_by:
            del search_by['full_status']
        for search in search_by.keys():
            if search not in self.filter_fields:
                raise ValueError(f"'{search}' is not a valid search operation")
        if search_by:
            comparison = comparison or 'eq'
            sources = []
            for stream in self._sources.values():
                for search, val in search_by.items():
                    if comparison_operators[comparison](getattr(stream, search), val):
                        sources.append(stream)
                        break
        else:
            sources = list(self._sources.values())
        if sort_by:
            sources.sort(key=lambda s: getattr(s, sort_by))
            if reverse:
                sources.reverse()
        return sources



    # @cache_concurrent
    # async def download_from_uri(self, uri, exchange_rate_manager: 'ExchangeRateManager',
    #                             timeout: Optional[float] = None, file_name: Optional[str] = None,
    #                             download_directory: Optional[str] = None,
    #                             save_file: Optional[bool] = None, resolve_timeout: float = 3.0,
    #                             wallet: Optional['Wallet'] = None) -> ManagedDownloadSource:
    #     wallet = wallet or self.wallet_manager.default_wallet
    #     timeout = timeout or self.config.download_timeout
    #     start_time = self.loop.time()
    #     resolved_time = None
    #     stream = None
    #     txo: Optional[Output] = None
    #     error = None
    #     outpoint = None
    #     if save_file is None:
    #         save_file = self.config.save_files
    #     if file_name and not save_file:
    #         save_file = True
    #     if save_file:
    #         download_directory = download_directory or self.config.download_dir
    #     else:
    #         download_directory = None
    #
    #     payment = None
    #     try:
    #         # resolve the claim
    #         if not URL.parse(uri).has_stream:
    #             raise ResolveError("cannot download a channel claim, specify a /path")
    #         try:
    #             response = await asyncio.wait_for(
    #                 self.wallet_manager.ledger.resolve(wallet.accounts, [uri]),
    #                 resolve_timeout
    #             )
    #             resolved_result = {}
    #             for url, txo in response.items():
    #                 if isinstance(txo, Output):
    #                     tx_height = txo.tx_ref.height
    #                     best_height = self.wallet_manager.ledger.headers.height
    #                     resolved_result[url] = {
    #                         'name': txo.claim_name,
    #                         'value': txo.claim,
    #                         'protobuf': binascii.hexlify(txo.claim.to_bytes()),
    #                         'claim_id': txo.claim_id,
    #                         'txid': txo.tx_ref.id,
    #                         'nout': txo.position,
    #                         'amount': dewies_to_lbc(txo.amount),
    #                         'effective_amount': txo.meta.get('effective_amount', 0),
    #                         'height': tx_height,
    #                         'confirmations': (best_height + 1) - tx_height if tx_height > 0 else tx_height,
    #                         'claim_sequence': -1,
    #                         'address': txo.get_address(self.wallet_manager.ledger),
    #                         'valid_at_height': txo.meta.get('activation_height', None),
    #                         'timestamp': self.wallet_manager.ledger.headers[tx_height]['timestamp'],
    #                         'supports': []
    #                     }
    #                 else:
    #                     resolved_result[url] = txo
    #         except asyncio.TimeoutError:
    #             raise ResolveTimeoutError(uri)
    #         except Exception as err:
    #             if isinstance(err, asyncio.CancelledError):
    #                 raise
    #             log.exception("Unexpected error resolving stream:")
    #             raise ResolveError(f"Unexpected error resolving stream: {str(err)}")
    #         await self.storage.save_claims_for_resolve([
    #             value for value in resolved_result.values() if 'error' not in value
    #         ])
    #
    #         resolved = resolved_result.get(uri, {})
    #         resolved = resolved if 'value' in resolved else resolved.get('claim')
    #         if not resolved:
    #             raise ResolveError(f"Failed to resolve stream at '{uri}'")
    #         if 'error' in resolved:
    #             raise ResolveError(f"error resolving stream: {resolved['error']}")
    #         txo = response[uri]
    #
    #         claim = Claim.from_bytes(binascii.unhexlify(resolved['protobuf']))
    #         outpoint = f"{resolved['txid']}:{resolved['nout']}"
    #         resolved_time = self.loop.time() - start_time
    #
    #         # resume or update an existing stream, if the stream changed: download it and delete the old one after
    #         updated_stream, to_replace = await self._check_update_or_replace(outpoint, resolved['claim_id'], claim)
    #         if updated_stream:
    #             log.info("already have stream for %s", uri)
    #             if save_file and updated_stream.output_file_exists:
    #                 save_file = False
    #             await updated_stream.start(node=self.node, timeout=timeout, save_now=save_file)
    #             if not updated_stream.output_file_exists and (save_file or file_name or download_directory):
    #                 await updated_stream.save_file(
    #                     file_name=file_name, download_directory=download_directory, node=self.node
    #                 )
    #             return updated_stream
    #
    #         if not to_replace and txo.has_price and not txo.purchase_receipt:
    #             payment = await manager.create_purchase_transaction(
    #                 wallet.accounts, txo, exchange_rate_manager
    #             )
    #
    #         stream = ManagedStream(
    #             self.loop, self.config, self.blob_manager, claim.stream.source.sd_hash, download_directory,
    #             file_name, ManagedStream.STATUS_RUNNING, content_fee=payment,
    #             analytics_manager=self.analytics_manager
    #         )
    #         log.info("starting download for %s", uri)
    #
    #         before_download = self.loop.time()
    #         await stream.start(self.node, timeout)
    #         stream.set_claim(resolved, claim)
    #         if to_replace:  # delete old stream now that the replacement has started downloading
    #             await self.delete(to_replace)
    #
    #         if payment is not None:
    #             await manager.broadcast_or_release(payment)
    #             payment = None  # to avoid releasing in `finally` later
    #             log.info("paid fee of %s for %s", dewies_to_lbc(stream.content_fee.outputs[0].amount), uri)
    #             await self.storage.save_content_fee(stream.stream_hash, stream.content_fee)
    #
    #         self._sources[stream.sd_hash] = stream
    #         self.storage.content_claim_callbacks[stream.stream_hash] = lambda: self._update_content_claim(stream)
    #         await self.storage.save_content_claim(stream.stream_hash, outpoint)
    #         if save_file:
    #             await asyncio.wait_for(stream.save_file(node=self.node), timeout - (self.loop.time() - before_download),
    #                                    loop=self.loop)
    #         return stream
    #     except asyncio.TimeoutError:
    #         error = DownloadDataTimeoutError(stream.sd_hash)
    #         raise error
    #     except Exception as err:  # forgive data timeout, don't delete stream
    #         expected = (DownloadSDTimeoutError, DownloadDataTimeoutError, InsufficientFundsError,
    #                     KeyFeeAboveMaxAllowedError)
    #         if isinstance(err, expected):
    #             log.warning("Failed to download %s: %s", uri, str(err))
    #         elif isinstance(err, asyncio.CancelledError):
    #             pass
    #         else:
    #             log.exception("Unexpected error downloading stream:")
    #         error = err
    #         raise
    #     finally:
    #         if payment is not None:
    #             # payment is set to None after broadcasting, if we're here an exception probably happened
    #             await manager.ledger.release_tx(payment)
    #         if self.analytics_manager and (error or (stream and (stream.downloader.time_to_descriptor or
    #                                                              stream.downloader.time_to_first_bytes))):
    #             server = self.wallet_manager.ledger.network.client.server
    #             self.loop.create_task(
    #                 self.analytics_manager.send_time_to_first_bytes(
    #                     resolved_time, self.loop.time() - start_time, None if not stream else stream.download_id,
    #                     uri, outpoint,
    #                     None if not stream else len(stream.downloader.blob_downloader.active_connections),
    #                     None if not stream else len(stream.downloader.blob_downloader.scores),
    #                     None if not stream else len(stream.downloader.blob_downloader.connection_failures),
    #                     False if not stream else stream.downloader.added_fixed_peers,
    #                     self.config.fixed_peer_delay if not stream else stream.downloader.fixed_peers_delay,
    #                     None if not stream else stream.sd_hash,
    #                     None if not stream else stream.downloader.time_to_descriptor,
    #                     None if not (stream and stream.descriptor) else stream.descriptor.blobs[0].blob_hash,
    #                     None if not (stream and stream.descriptor) else stream.descriptor.blobs[0].length,
    #                     None if not stream else stream.downloader.time_to_first_bytes,
    #                     None if not error else error.__class__.__name__,
    #                     None if not error else str(error),
    #                     None if not server else f"{server[0]}:{server[1]}"
    #                 )
    #             )
