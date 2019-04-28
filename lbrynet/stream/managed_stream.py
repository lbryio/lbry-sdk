import os
import asyncio
import typing
import logging
import binascii
from lbrynet.utils import generate_id
from lbrynet.schema.mime_types import guess_media_type
from lbrynet.stream.downloader import StreamDownloader
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.stream.reflector.client import StreamReflectorClient
from lbrynet.extras.daemon.storage import StoredStreamClaim
if typing.TYPE_CHECKING:
    from lbrynet.conf import Config
    from lbrynet.schema.claim import Claim
    from lbrynet.blob.blob_manager import BlobManager
    from lbrynet.blob.blob_info import BlobInfo
    from lbrynet.dht.node import Node
    from lbrynet.extras.daemon.analytics import AnalyticsManager
    from lbrynet.wallet.transaction import Transaction

log = logging.getLogger(__name__)


def _get_next_available_file_name(download_directory: str, file_name: str) -> str:
    base_name, ext = os.path.splitext(os.path.basename(file_name))
    i = 0
    while os.path.isfile(os.path.join(download_directory, file_name)):
        i += 1
        file_name = "%s_%i%s" % (base_name, i, ext)

    return file_name


async def get_next_available_file_name(loop: asyncio.BaseEventLoop, download_directory: str, file_name: str) -> str:
    return await loop.run_in_executor(None, _get_next_available_file_name, download_directory, file_name)


class ManagedStream:
    STATUS_RUNNING = "running"
    STATUS_STOPPED = "stopped"
    STATUS_FINISHED = "finished"

    def __init__(self, loop: asyncio.BaseEventLoop, config: 'Config', blob_manager: 'BlobManager',
                 sd_hash: str, download_directory: typing.Optional[str] = None, file_name: typing.Optional[str] = None,
                 status: typing.Optional[str] = STATUS_STOPPED, claim: typing.Optional[StoredStreamClaim] = None,
                 download_id: typing.Optional[str] = None, rowid: typing.Optional[int] = None,
                 descriptor: typing.Optional[StreamDescriptor] = None,
                 content_fee: typing.Optional['Transaction'] = None,
                 analytics_manager: typing.Optional['AnalyticsManager'] = None):
        self.loop = loop
        self.config = config
        self.blob_manager = blob_manager
        self.sd_hash = sd_hash
        self.download_directory = download_directory
        self._file_name = file_name
        self._status = status
        self.stream_claim_info = claim
        self.download_id = download_id or binascii.hexlify(generate_id()).decode()
        self.rowid = rowid
        self.written_bytes = 0
        self.content_fee = content_fee
        self.downloader = StreamDownloader(self.loop, self.config, self.blob_manager, sd_hash, descriptor)
        self.analytics_manager = analytics_manager
        self.fully_reflected = asyncio.Event(loop=self.loop)
        self.file_output_task: typing.Optional[asyncio.Task] = None
        self.delayed_stop: typing.Optional[asyncio.Handle] = None
        self.saving = asyncio.Event(loop=self.loop)
        self.finished_writing = asyncio.Event(loop=self.loop)
        self.started_writing = asyncio.Event(loop=self.loop)

    @property
    def descriptor(self) -> StreamDescriptor:
        return self.downloader.descriptor

    @property
    def stream_hash(self) -> str:
        return self.descriptor.stream_hash

    @property
    def file_name(self) -> typing.Optional[str]:
        return self._file_name or (self.descriptor.suggested_file_name if self.descriptor else None)

    @property
    def status(self) -> str:
        return self._status

    def update_status(self, status: str):
        assert status in [self.STATUS_RUNNING, self.STATUS_STOPPED, self.STATUS_FINISHED]
        self._status = status

    @property
    def finished(self) -> bool:
        return self.status == self.STATUS_FINISHED

    @property
    def running(self) -> bool:
        return self.status == self.STATUS_RUNNING

    @property
    def claim_id(self) -> typing.Optional[str]:
        return None if not self.stream_claim_info else self.stream_claim_info.claim_id

    @property
    def txid(self) -> typing.Optional[str]:
        return None if not self.stream_claim_info else self.stream_claim_info.txid

    @property
    def nout(self) -> typing.Optional[int]:
        return None if not self.stream_claim_info else self.stream_claim_info.nout

    @property
    def outpoint(self) -> typing.Optional[str]:
        return None if not self.stream_claim_info else self.stream_claim_info.outpoint

    @property
    def claim_height(self) -> typing.Optional[int]:
        return None if not self.stream_claim_info else self.stream_claim_info.height

    @property
    def channel_claim_id(self) -> typing.Optional[str]:
        return None if not self.stream_claim_info else self.stream_claim_info.channel_claim_id

    @property
    def channel_name(self) -> typing.Optional[str]:
        return None if not self.stream_claim_info else self.stream_claim_info.channel_name

    @property
    def claim_name(self) -> typing.Optional[str]:
        return None if not self.stream_claim_info else self.stream_claim_info.claim_name

    @property
    def metadata(self) -> typing.Optional[typing.Dict]:
        return None if not self.stream_claim_info else self.stream_claim_info.claim.stream.to_dict()

    @property
    def metadata_protobuf(self) -> bytes:
        if self.stream_claim_info:
            return binascii.hexlify(self.stream_claim_info.claim.to_bytes())

    @property
    def blobs_completed(self) -> int:
        return sum([1 if self.blob_manager.is_blob_verified(b.blob_hash) else 0
                    for b in self.descriptor.blobs[:-1]])

    @property
    def blobs_in_stream(self) -> int:
        return len(self.descriptor.blobs) - 1

    @property
    def blobs_remaining(self) -> int:
        return self.blobs_in_stream - self.blobs_completed

    @property
    def full_path(self) -> typing.Optional[str]:
        return os.path.join(self.download_directory, os.path.basename(self.file_name)) \
            if self.file_name and self.download_directory else None

    @property
    def output_file_exists(self):
        return os.path.isfile(self.full_path) if self.full_path else False

    @property
    def mime_type(self):
        return guess_media_type(os.path.basename(self.descriptor.suggested_file_name))[0]

    def as_dict(self) -> typing.Dict:
        if not self.written_bytes and self.output_file_exists:
            written_bytes = os.stat(self.full_path).st_size
        else:
            written_bytes = self.written_bytes
        return {
            'completed': self.finished,
            'file_name': self.file_name,
            'download_directory': self.download_directory,
            'points_paid': 0.0,
            'stopped': not self.running,
            'stream_hash': self.stream_hash,
            'stream_name': self.descriptor.stream_name,
            'suggested_file_name': self.descriptor.suggested_file_name,
            'sd_hash': self.descriptor.sd_hash,
            'download_path': self.full_path,
            'mime_type': self.mime_type,
            'key': self.descriptor.key,
            'total_bytes_lower_bound': self.descriptor.lower_bound_decrypted_length(),
            'total_bytes': self.descriptor.upper_bound_decrypted_length(),
            'written_bytes': written_bytes,
            'blobs_completed': self.blobs_completed,
            'blobs_in_stream': self.blobs_in_stream,
            'blobs_remaining': self.blobs_remaining,
            'status': self.status,
            'claim_id': self.claim_id,
            'txid': self.txid,
            'nout': self.nout,
            'outpoint': self.outpoint,
            'metadata': self.metadata,
            'protobuf': self.metadata_protobuf,
            'channel_claim_id': self.channel_claim_id,
            'channel_name': self.channel_name,
            'claim_name': self.claim_name,
            'content_fee': self.content_fee  # TODO: this isn't in the database
        }

    @classmethod
    async def create(cls, loop: asyncio.BaseEventLoop, config: 'Config', blob_manager: 'BlobManager',
                     file_path: str, key: typing.Optional[bytes] = None,
                     iv_generator: typing.Optional[typing.Generator[bytes, None, None]] = None) -> 'ManagedStream':
        descriptor = await StreamDescriptor.create_stream(
            loop, blob_manager.blob_dir, file_path, key=key, iv_generator=iv_generator,
            blob_completed_callback=blob_manager.blob_completed
        )
        await blob_manager.storage.store_stream(
            blob_manager.get_blob(descriptor.sd_hash), descriptor
        )
        row_id = await blob_manager.storage.save_published_file(descriptor.stream_hash, os.path.basename(file_path),
                                                                os.path.dirname(file_path), 0)
        return cls(loop, config, blob_manager, descriptor.sd_hash, os.path.dirname(file_path),
                   os.path.basename(file_path), status=cls.STATUS_FINISHED, rowid=row_id, descriptor=descriptor)

    async def setup(self, node: typing.Optional['Node'] = None, save_file: typing.Optional[bool] = True,
                    file_name: typing.Optional[str] = None, download_directory: typing.Optional[str] = None):
        await self.downloader.start(node)
        if not save_file and not file_name:
            if not await self.blob_manager.storage.file_exists(self.sd_hash):
                self.rowid = await self.blob_manager.storage.save_downloaded_file(
                    self.stream_hash, None, None, 0.0
                )
                self.download_directory = None
                self._file_name = None
                self.update_status(ManagedStream.STATUS_RUNNING)
                await self.blob_manager.storage.change_file_status(self.stream_hash, ManagedStream.STATUS_RUNNING)
            self.update_delayed_stop()
        else:
            await self.save_file(file_name, download_directory)
            await self.started_writing.wait()

    def update_delayed_stop(self):
        def _delayed_stop():
            log.info("Stopping inactive download for stream %s", self.sd_hash)
            self.stop_download()

        if self.delayed_stop:
            self.delayed_stop.cancel()
        self.delayed_stop = self.loop.call_later(60, _delayed_stop)

    async def aiter_read_stream(self, start_blob_num: typing.Optional[int] = 0) -> typing.AsyncIterator[
                                                                                    typing.Tuple['BlobInfo', bytes]]:
        if start_blob_num >= len(self.descriptor.blobs[:-1]):
            raise IndexError(start_blob_num)
        for i, blob_info in enumerate(self.descriptor.blobs[start_blob_num:-1]):
            assert i + start_blob_num == blob_info.blob_num
            if self.delayed_stop:
                self.delayed_stop.cancel()
            try:
                decrypted = await self.downloader.read_blob(blob_info)
                yield (blob_info, decrypted)
            except asyncio.CancelledError:
                if not self.saving.is_set() and not self.finished_writing.is_set():
                    self.update_delayed_stop()
                raise

    async def _save_file(self, output_path: str):
        log.debug("save file %s -> %s", self.sd_hash, output_path)
        self.saving.set()
        self.finished_writing.clear()
        self.started_writing.clear()
        try:
            with open(output_path, 'wb') as file_write_handle:
                async for blob_info, decrypted in self.aiter_read_stream():
                    log.info("write blob %i/%i", blob_info.blob_num + 1, len(self.descriptor.blobs) - 1)
                    file_write_handle.write(decrypted)
                    file_write_handle.flush()
                    self.written_bytes += len(decrypted)
                    if not self.started_writing.is_set():
                        self.started_writing.set()
            self.update_status(ManagedStream.STATUS_FINISHED)
            await self.blob_manager.storage.change_file_status(self.stream_hash, ManagedStream.STATUS_FINISHED)
            if self.analytics_manager:
                self.loop.create_task(self.analytics_manager.send_download_finished(
                    self.download_id, self.claim_name, self.sd_hash
                ))
            self.finished_writing.set()
        except Exception as err:
            if os.path.isfile(output_path):
                log.info("removing incomplete download %s for %s", output_path, self.sd_hash)
                os.remove(output_path)
            if not isinstance(err, asyncio.CancelledError):
                log.exception("unexpected error encountered writing file for stream %s", self.sd_hash)
            raise err
        finally:
            self.saving.clear()

    async def save_file(self, file_name: typing.Optional[str] = None, download_directory: typing.Optional[str] = None):
        if self.file_output_task and not self.file_output_task.done():
            self.file_output_task.cancel()
        if self.delayed_stop:
            self.delayed_stop.cancel()
            self.delayed_stop = None
        self.download_directory = download_directory or self.download_directory or self.config.download_dir
        if not self.download_directory:
            raise ValueError("no directory to download to")
        if not (file_name or self._file_name or self.descriptor.suggested_file_name):
            raise ValueError("no file name to download to")
        if not os.path.isdir(self.download_directory):
            log.warning("download directory '%s' does not exist, attempting to make it", self.download_directory)
            os.mkdir(self.download_directory)
        if not await self.blob_manager.storage.file_exists(self.sd_hash):
            self._file_name = await get_next_available_file_name(
                self.loop, self.download_directory,
                file_name or self._file_name or self.descriptor.suggested_file_name
            )
            self.rowid = self.blob_manager.storage.save_downloaded_file(
                self.stream_hash, self.file_name, self.download_directory, 0.0
            )
        else:
            await self.blob_manager.storage.change_file_download_dir_and_file_name(
                self.stream_hash, self.download_directory, self.file_name
            )
        self.update_status(ManagedStream.STATUS_RUNNING)
        await self.blob_manager.storage.change_file_status(self.stream_hash, ManagedStream.STATUS_RUNNING)
        self.written_bytes = 0
        self.file_output_task = self.loop.create_task(self._save_file(self.full_path))

    def stop_download(self):
        if self.file_output_task and not self.file_output_task.done():
            self.file_output_task.cancel()
        self.file_output_task = None
        self.downloader.stop()

    async def upload_to_reflector(self, host: str, port: int) -> typing.List[str]:
        sent = []
        protocol = StreamReflectorClient(self.blob_manager, self.descriptor)
        try:
            await self.loop.create_connection(lambda: protocol, host, port)
            await protocol.send_handshake()
            sent_sd, needed = await protocol.send_descriptor()
            if sent_sd:
                sent.append(self.sd_hash)
            if not sent_sd and not needed:
                if not self.fully_reflected.is_set():
                    self.fully_reflected.set()
                    await self.blob_manager.storage.update_reflected_stream(self.sd_hash, f"{host}:{port}")
                    return []
            we_have = [
                blob_hash for blob_hash in needed if blob_hash in self.blob_manager.completed_blob_hashes
            ]
            for blob_hash in we_have:
                await protocol.send_blob(blob_hash)
                sent.append(blob_hash)
        except (asyncio.TimeoutError, ValueError):
            return sent
        except ConnectionRefusedError:
            return sent
        finally:
            if protocol.transport:
                protocol.transport.close()
        if not self.fully_reflected.is_set():
            self.fully_reflected.set()
            await self.blob_manager.storage.update_reflected_stream(self.sd_hash, f"{host}:{port}")
        return sent

    def set_claim(self, claim_info: typing.Dict, claim: 'Claim'):
        self.stream_claim_info = StoredStreamClaim(
            self.stream_hash, f"{claim_info['txid']}:{claim_info['nout']}", claim_info['claim_id'],
            claim_info['name'], claim_info['amount'], claim_info['height'],
            binascii.hexlify(claim.to_bytes()).decode(), claim.signing_channel_id, claim_info['address'],
            claim_info['claim_sequence'], claim_info.get('channel_name')
        )
