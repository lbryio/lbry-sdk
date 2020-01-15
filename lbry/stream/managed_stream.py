import os
import asyncio
import time
import typing
import logging
import binascii
from typing import Optional
from aiohttp.web import Request, StreamResponse, HTTPRequestRangeNotSatisfiable
from lbry.utils import generate_id
from lbry.error import DownloadSDTimeoutError
from lbry.schema.mime_types import guess_media_type
from lbry.stream.downloader import StreamDownloader
from lbry.stream.descriptor import StreamDescriptor, sanitize_file_name
from lbry.stream.reflector.client import StreamReflectorClient
from lbry.extras.daemon.storage import StoredContentClaim
from lbry.blob import MAX_BLOB_SIZE
from lbry.file.source import ManagedDownloadSource

if typing.TYPE_CHECKING:
    from lbry.conf import Config
    from lbry.schema.claim import Claim
    from lbry.blob.blob_manager import BlobManager
    from lbry.blob.blob_info import BlobInfo
    from lbry.extras.daemon.storage import SQLiteStorage
    from lbry.dht.node import Node
    from lbry.extras.daemon.analytics import AnalyticsManager
    from lbry.wallet.transaction import Transaction

log = logging.getLogger(__name__)


def _get_next_available_file_name(download_directory: str, file_name: str) -> str:
    base_name, ext = os.path.splitext(os.path.basename(file_name))
    i = 0
    while os.path.isfile(os.path.join(download_directory, file_name)):
        i += 1
        file_name = "%s_%i%s" % (base_name, i, ext)

    return file_name


async def get_next_available_file_name(loop: asyncio.AbstractEventLoop, download_directory: str, file_name: str) -> str:
    return await loop.run_in_executor(None, _get_next_available_file_name, download_directory, file_name)


class ManagedStream(ManagedDownloadSource):
    def __init__(self, loop: asyncio.AbstractEventLoop, config: 'Config', blob_manager: 'BlobManager',
                 sd_hash: str, download_directory: Optional[str] = None, file_name: Optional[str] = None,
                 status: Optional[str] = ManagedDownloadSource.STATUS_STOPPED,
                 claim: Optional[StoredContentClaim] = None,
                 download_id: Optional[str] = None, rowid: Optional[int] = None,
                 descriptor: Optional[StreamDescriptor] = None,
                 content_fee: Optional['Transaction'] = None,
                 analytics_manager: Optional['AnalyticsManager'] = None,
                 added_on: Optional[int] = None):
        super().__init__(loop, config, blob_manager.storage, sd_hash, file_name, download_directory, status, claim,
                         download_id, rowid, content_fee, analytics_manager, added_on)
        self.blob_manager = blob_manager
        self.purchase_receipt = None
        self.downloader = StreamDownloader(self.loop, self.config, self.blob_manager, sd_hash, descriptor)
        self.analytics_manager = analytics_manager

        self.fully_reflected = asyncio.Event(loop=self.loop)
        self.reflector_progress = 0
        self.uploading_to_reflector = False
        self.file_output_task: typing.Optional[asyncio.Task] = None
        self.delayed_stop_task: typing.Optional[asyncio.Task] = None
        self.streaming_responses: typing.List[typing.Tuple[Request, StreamResponse]] = []
        self.fully_reflected = asyncio.Event(loop=self.loop)
        self.streaming = asyncio.Event(loop=self.loop)
        self._running = asyncio.Event(loop=self.loop)

    @property
    def sd_hash(self) -> str:
        return self.identifier

    @property
    def is_fully_reflected(self) -> bool:
        return self.fully_reflected.is_set()

    @property
    def descriptor(self) -> StreamDescriptor:
        return self.downloader.descriptor

    @property
    def stream_hash(self) -> str:
        return self.descriptor.stream_hash

    @property
    def file_name(self) -> Optional[str]:
        return self._file_name or (self.descriptor.suggested_file_name if self.descriptor else None)

    @property
    def written_bytes(self) -> int:
        return 0 if not self.output_file_exists else os.stat(self.full_path).st_size

    @property
    def completed(self):
        return self.written_bytes >= self.descriptor.lower_bound_decrypted_length()

    @property
    def stream_url(self):
        return f"http://{self.config.streaming_host}:{self.config.streaming_port}/stream/{self.sd_hash}"

    async def update_status(self, status: str):
        assert status in [self.STATUS_RUNNING, self.STATUS_STOPPED, self.STATUS_FINISHED]
        self._status = status
        await self.blob_manager.storage.change_file_status(self.stream_hash, status)

    @property
    def blobs_completed(self) -> int:
        return sum([1 if b.blob_hash in self.blob_manager.completed_blob_hashes else 0
                    for b in self.descriptor.blobs[:-1]])

    @property
    def blobs_in_stream(self) -> int:
        return len(self.descriptor.blobs) - 1

    @property
    def blobs_remaining(self) -> int:
        return self.blobs_in_stream - self.blobs_completed

    @property
    def mime_type(self):
        return guess_media_type(os.path.basename(self.descriptor.suggested_file_name))[0]

    # @classmethod
    # async def create(cls, loop: asyncio.AbstractEventLoop, config: 'Config',
    #                  file_path: str, key: Optional[bytes] = None,
    #                  iv_generator: Optional[typing.Generator[bytes, None, None]] = None) -> 'ManagedDownloadSource':
    #     """
    #     Generate a stream from a file and save it to the db
    #     """
    #     descriptor = await StreamDescriptor.create_stream(
    #         loop, blob_manager.blob_dir, file_path, key=key, iv_generator=iv_generator,
    #         blob_completed_callback=blob_manager.blob_completed
    #     )
    #     await blob_manager.storage.store_stream(
    #         blob_manager.get_blob(descriptor.sd_hash), descriptor
    #     )
    #     row_id = await blob_manager.storage.save_published_file(descriptor.stream_hash, os.path.basename(file_path),
    #                                                             os.path.dirname(file_path), 0)
    #     return cls(loop, config, blob_manager, descriptor.sd_hash, os.path.dirname(file_path),
    #                os.path.basename(file_path), status=cls.STATUS_FINISHED, rowid=row_id, descriptor=descriptor)

    async def start(self, node: Optional['Node'] = None, timeout: Optional[float] = None,
                    save_now: bool = False):
        timeout = timeout or self.config.download_timeout
        if self._running.is_set():
            return
        log.info("start downloader for stream (sd hash: %s)", self.sd_hash)
        self._running.set()
        try:
            await asyncio.wait_for(self.downloader.start(node), timeout, loop=self.loop)
        except asyncio.TimeoutError:
            self._running.clear()
            raise DownloadSDTimeoutError(self.sd_hash)

        if self.delayed_stop_task and not self.delayed_stop_task.done():
            self.delayed_stop_task.cancel()
        self.delayed_stop_task = self.loop.create_task(self._delayed_stop())
        if not await self.blob_manager.storage.file_exists(self.sd_hash):
            if save_now:
                file_name, download_dir = self._file_name, self.download_directory
            else:
                file_name, download_dir = None, None
            self._added_on = int(time.time())
            self.rowid = await self.blob_manager.storage.save_downloaded_file(
                self.stream_hash, file_name, download_dir, 0.0, added_on=self._added_on
            )
        if self.status != self.STATUS_RUNNING:
            await self.update_status(self.STATUS_RUNNING)

    async def stop(self, finished: bool = False):
        """
        Stop any running save/stream tasks as well as the downloader and update the status in the database
        """

        self.stop_tasks()
        if (finished and self.status != self.STATUS_FINISHED) or self.status == self.STATUS_RUNNING:
            await self.update_status(self.STATUS_FINISHED if finished else self.STATUS_STOPPED)

    async def _aiter_read_stream(self, start_blob_num: Optional[int] = 0, connection_id: int = 0)\
            -> typing.AsyncIterator[typing.Tuple['BlobInfo', bytes]]:
        if start_blob_num >= len(self.descriptor.blobs[:-1]):
            raise IndexError(start_blob_num)
        for i, blob_info in enumerate(self.descriptor.blobs[start_blob_num:-1]):
            assert i + start_blob_num == blob_info.blob_num
            if connection_id == self.STREAMING_ID:
                decrypted = await self.downloader.cached_read_blob(blob_info)
            else:
                decrypted = await self.downloader.read_blob(blob_info, connection_id)
            yield (blob_info, decrypted)

    async def stream_file(self, request: Request, node: Optional['Node'] = None) -> StreamResponse:
        log.info("stream file to browser for lbry://%s#%s (sd hash %s...)", self.claim_name, self.claim_id,
                 self.sd_hash[:6])
        headers, size, skip_blobs, first_blob_start_offset = self._prepare_range_response_headers(
            request.headers.get('range', 'bytes=0-')
        )
        await self.start(node)
        response = StreamResponse(
            status=206,
            headers=headers
        )
        await response.prepare(request)
        self.streaming_responses.append((request, response))
        self.streaming.set()
        wrote = 0
        try:
            async for blob_info, decrypted in self._aiter_read_stream(skip_blobs, connection_id=self.STREAMING_ID):
                if not wrote:
                    decrypted = decrypted[first_blob_start_offset:]
                if (blob_info.blob_num == len(self.descriptor.blobs) - 2) or (len(decrypted) + wrote >= size):
                    decrypted += (b'\x00' * (size - len(decrypted) - wrote - (skip_blobs * (MAX_BLOB_SIZE - 1))))
                    log.debug("sending browser final blob (%i/%i)", blob_info.blob_num + 1,
                              len(self.descriptor.blobs) - 1)
                    await response.write_eof(decrypted)
                else:
                    log.debug("sending browser blob (%i/%i)", blob_info.blob_num + 1, len(self.descriptor.blobs) - 1)
                    await response.write(decrypted)
                wrote += len(decrypted)
                log.info("sent browser %sblob %i/%i", "(final) " if response._eof_sent else "",
                         blob_info.blob_num + 1, len(self.descriptor.blobs) - 1)
                if response._eof_sent:
                    break
            return response
        except ConnectionResetError:
            log.warning("connection was reset after sending browser %i blob bytes", wrote)
            raise asyncio.CancelledError("range request transport was reset")
        finally:
            response.force_close()
            if (request, response) in self.streaming_responses:
                self.streaming_responses.remove((request, response))
            if not self.streaming_responses:
                self.streaming.clear()

    @staticmethod
    def _write_decrypted_blob(output_path: str, data: bytes):
        with open(output_path, 'ab') as handle:
            handle.write(data)
            handle.flush()

    async def _save_file(self, output_path: str):
        log.info("save file for lbry://%s#%s (sd hash %s...) -> %s", self.claim_name, self.claim_id, self.sd_hash[:6],
                 output_path)
        self.saving.set()
        self.finished_write_attempt.clear()
        self.finished_writing.clear()
        self.started_writing.clear()
        try:
            open(output_path, 'wb').close()
            async for blob_info, decrypted in self._aiter_read_stream(connection_id=self.SAVING_ID):
                log.info("write blob %i/%i", blob_info.blob_num + 1, len(self.descriptor.blobs) - 1)
                await self.loop.run_in_executor(None, self._write_decrypted_blob, output_path, decrypted)
                if not self.started_writing.is_set():
                    self.started_writing.set()
            await self.update_status(ManagedStream.STATUS_FINISHED)
            if self.analytics_manager:
                self.loop.create_task(self.analytics_manager.send_download_finished(
                    self.download_id, self.claim_name, self.sd_hash
                ))
            self.finished_writing.set()
            log.info("finished saving file for lbry://%s#%s (sd hash %s...) -> %s", self.claim_name, self.claim_id,
                     self.sd_hash[:6], self.full_path)
            await self.blob_manager.storage.set_saved_file(self.stream_hash)
        except Exception as err:
            if os.path.isfile(output_path):
                log.warning("removing incomplete download %s for %s", output_path, self.sd_hash)
                os.remove(output_path)
            if isinstance(err, asyncio.TimeoutError):
                self.downloader.stop()
                await self.blob_manager.storage.change_file_download_dir_and_file_name(
                    self.stream_hash, None, None
                )
                self._file_name, self.download_directory = None, None
                await self.blob_manager.storage.clear_saved_file(self.stream_hash)
                await self.update_status(self.STATUS_STOPPED)
                return
            elif not isinstance(err, asyncio.CancelledError):
                log.exception("unexpected error encountered writing file for stream %s", self.sd_hash)
            raise err
        finally:
            self.saving.clear()
            self.finished_write_attempt.set()

    async def save_file(self, file_name: Optional[str] = None, download_directory: Optional[str] = None,
                        node: Optional['Node'] = None):
        await self.start(node)
        if self.file_output_task and not self.file_output_task.done():  # cancel an already running save task
            self.file_output_task.cancel()
        self.download_directory = download_directory or self.download_directory or self.config.download_dir
        if not self.download_directory:
            raise ValueError("no directory to download to")
        if not (file_name or self._file_name or self.descriptor.suggested_file_name):
            raise ValueError("no file name to download to")
        if not os.path.isdir(self.download_directory):
            log.warning("download directory '%s' does not exist, attempting to make it", self.download_directory)
            os.mkdir(self.download_directory)
        self._file_name = await get_next_available_file_name(
            self.loop, self.download_directory,
            file_name or self._file_name or sanitize_file_name(self.descriptor.suggested_file_name)
        )
        await self.blob_manager.storage.change_file_download_dir_and_file_name(
            self.stream_hash, self.download_directory, self.file_name
        )
        await self.update_status(ManagedStream.STATUS_RUNNING)
        self.file_output_task = self.loop.create_task(self._save_file(self.full_path))
        try:
            await asyncio.wait_for(self.started_writing.wait(), self.config.download_timeout, loop=self.loop)
        except asyncio.TimeoutError:
            log.warning("timeout starting to write data for lbry://%s#%s", self.claim_name, self.claim_id)
            self.stop_tasks()
            await self.update_status(ManagedStream.STATUS_STOPPED)

    def stop_tasks(self):
        if self.file_output_task and not self.file_output_task.done():
            self.file_output_task.cancel()
        self.file_output_task = None
        while self.streaming_responses:
            req, response = self.streaming_responses.pop()
            response.force_close()
            req.transport.close()
        self.downloader.stop()
        self._running.clear()

    async def upload_to_reflector(self, host: str, port: int) -> typing.List[str]:
        sent = []
        protocol = StreamReflectorClient(self.blob_manager, self.descriptor)
        try:
            self.uploading_to_reflector = True
            await self.loop.create_connection(lambda: protocol, host, port)
            await protocol.send_handshake()
            sent_sd, needed = await protocol.send_descriptor()
            if sent_sd:  # reflector needed the sd blob
                sent.append(self.sd_hash)
            if not sent_sd and not needed:  # reflector already has the stream
                if not self.fully_reflected.is_set():
                    self.fully_reflected.set()
                    await self.blob_manager.storage.update_reflected_stream(self.sd_hash, f"{host}:{port}")
                    return []
            we_have = [
                blob_hash for blob_hash in needed if blob_hash in self.blob_manager.completed_blob_hashes
            ]
            log.info("we have %i/%i needed blobs needed by reflector for lbry://%s#%s", len(we_have), len(needed),
                     self.claim_name, self.claim_id)
            for i, blob_hash in enumerate(we_have):
                await protocol.send_blob(blob_hash)
                sent.append(blob_hash)
                self.reflector_progress = int((i + 1) / len(we_have) * 100)
        except (asyncio.TimeoutError, ValueError):
            return sent
        except ConnectionRefusedError:
            return sent
        finally:
            if protocol.transport:
                protocol.transport.close()
            self.uploading_to_reflector = False
        if not self.fully_reflected.is_set():
            self.fully_reflected.set()
            await self.blob_manager.storage.update_reflected_stream(self.sd_hash, f"{host}:{port}")
        return sent

    def set_claim(self, claim_info: typing.Dict, claim: 'Claim'):
        self.stream_claim_info = StoredContentClaim(
            f"{claim_info['txid']}:{claim_info['nout']}", claim_info['claim_id'],
            claim_info['name'], claim_info['amount'], claim_info['height'],
            binascii.hexlify(claim.to_bytes()).decode(), claim.signing_channel_id, claim_info['address'],
            claim_info['claim_sequence'], claim_info.get('channel_name')
        )

    async def update_content_claim(self, claim_info: Optional[typing.Dict] = None):
        if not claim_info:
            claim_info = await self.blob_manager.storage.get_content_claim(self.stream_hash)
        self.set_claim(claim_info, claim_info['value'])

    async def _delayed_stop(self):
        stalled_count = 0
        while self._running.is_set():
            if self.saving.is_set() or self.streaming.is_set():
                stalled_count = 0
            else:
                stalled_count += 1
            if stalled_count > 1:
                log.info("stopping inactive download for lbry://%s#%s (%s...)", self.claim_name, self.claim_id,
                         self.sd_hash[:6])
                await self.stop()
                return
            await asyncio.sleep(1, loop=self.loop)

    def _prepare_range_response_headers(self, get_range: str) -> typing.Tuple[typing.Dict[str, str], int, int, int]:
        if '=' in get_range:
            get_range = get_range.split('=')[1]
        start, end = get_range.split('-')
        size = 0

        for blob in self.descriptor.blobs[:-1]:
            size += blob.length - 1
        if self.stream_claim_info and self.stream_claim_info.claim.stream.source.size:
            size_from_claim = int(self.stream_claim_info.claim.stream.source.size)
            if not size_from_claim <= size <= size_from_claim + 16:
                raise ValueError("claim contains implausible stream size")
            log.debug("using stream size from claim")
            size = size_from_claim
        elif self.stream_claim_info:
            log.debug("estimating stream size")

        start = int(start)
        if not 0 <= start < size:
            raise HTTPRequestRangeNotSatisfiable()

        end = int(end) if end else size - 1

        if end >= size:
            raise HTTPRequestRangeNotSatisfiable()

        skip_blobs = start // (MAX_BLOB_SIZE - 2)  # -2 because ... dont remember
        skip = skip_blobs * (MAX_BLOB_SIZE - 1)  # -1 because
        skip_first_blob = start - skip
        start = skip_first_blob + skip
        final_size = end - start + 1
        headers = {
            'Accept-Ranges': 'bytes',
            'Content-Range': f'bytes {start}-{end}/{size}',
            'Content-Length': str(final_size),
            'Content-Type': self.mime_type
        }
        return headers, size, skip_blobs, skip_first_blob
