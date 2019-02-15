import os
import asyncio
import typing
import logging
import binascii
from lbrynet.extras.daemon.mime_types import guess_media_type
from lbrynet.stream.downloader import StreamDownloader
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.stream.reflector.client import StreamReflectorClient
from lbrynet.extras.daemon.storage import StoredStreamClaim
if typing.TYPE_CHECKING:
    from lbrynet.schema.claim import ClaimDict
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.dht.node import Node

log = logging.getLogger(__name__)


class ManagedStream:
    STATUS_RUNNING = "running"
    STATUS_STOPPED = "stopped"
    STATUS_FINISHED = "finished"

    def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: 'BlobFileManager', rowid: int,
                 descriptor: 'StreamDescriptor', download_directory: str, file_name: str,
                 downloader: typing.Optional[StreamDownloader] = None,
                 status: typing.Optional[str] = STATUS_STOPPED, claim: typing.Optional[StoredStreamClaim] = None):
        self.loop = loop
        self.blob_manager = blob_manager
        self.rowid = rowid
        self.download_directory = download_directory
        self._file_name = file_name
        self.descriptor = descriptor
        self.downloader = downloader
        self.stream_hash = descriptor.stream_hash
        self.stream_claim_info = claim
        self._status = status
        self.fully_reflected = asyncio.Event(loop=self.loop)

    @property
    def file_name(self):
        return self.downloader.output_file_name if self.downloader else self._file_name

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
    def metadata(self) ->typing.Optional[typing.Dict]:
        return None if not self.stream_claim_info else self.stream_claim_info.claim.claim_dict['stream']['metadata']

    @property
    def blobs_completed(self) -> int:
        return sum([1 if self.blob_manager.get_blob(b.blob_hash).get_is_verified() else 0
                    for b in self.descriptor.blobs[:-1]])

    @property
    def blobs_in_stream(self) -> int:
        return len(self.descriptor.blobs) - 1

    @property
    def sd_hash(self):
        return self.descriptor.sd_hash

    @property
    def blobs_remaining(self) -> int:
        return self.blobs_in_stream - self.blobs_completed

    @property
    def full_path(self) -> str:
        return os.path.join(self.download_directory, os.path.basename(self.file_name))

    def as_dict(self) -> typing.Dict:
        full_path = self.full_path
        if not os.path.isfile(full_path):
            full_path = None
        mime_type = guess_media_type(os.path.basename(self.file_name))

        if self.downloader and self.downloader.written_bytes:
            written_bytes = self.downloader.written_bytes
        elif full_path:
            written_bytes = os.stat(full_path).st_size
        else:
            written_bytes = None
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
            'download_path': full_path,
            'mime_type': mime_type,
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
            'channel_claim_id': self.channel_claim_id,
            'channel_name': self.channel_name,
            'claim_name': self.claim_name
        }

    @classmethod
    async def create(cls, loop: asyncio.BaseEventLoop, blob_manager: 'BlobFileManager',
                     file_path: str, key: typing.Optional[bytes] = None,
                     iv_generator: typing.Optional[typing.Generator[bytes, None, None]] = None) -> 'ManagedStream':
        descriptor = await StreamDescriptor.create_stream(
            loop, blob_manager.blob_dir, file_path, key=key, iv_generator=iv_generator
        )
        sd_blob = blob_manager.get_blob(descriptor.sd_hash)
        await blob_manager.storage.store_stream(
            blob_manager.get_blob(descriptor.sd_hash), descriptor
        )
        await blob_manager.blob_completed(sd_blob)
        for blob in descriptor.blobs[:-1]:
            await blob_manager.blob_completed(blob_manager.get_blob(blob.blob_hash, blob.length))
        row_id = await blob_manager.storage.save_published_file(descriptor.stream_hash, os.path.basename(file_path),
                                                                os.path.dirname(file_path), 0)
        return cls(loop, blob_manager, row_id, descriptor, os.path.dirname(file_path), os.path.basename(file_path),
                   status=cls.STATUS_FINISHED)

    def start_download(self, node: typing.Optional['Node']):
        self.downloader.download(node)
        self.update_status(self.STATUS_RUNNING)

    def stop_download(self):
        if self.downloader:
            self.downloader.stop()
        self.downloader = None

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
            we_have = [blob_hash for blob_hash in needed if blob_hash in self.blob_manager.completed_blob_hashes]
            for blob_hash in we_have:
                await protocol.send_blob(blob_hash)
                sent.append(blob_hash)
        except (asyncio.CancelledError, asyncio.TimeoutError, ValueError):
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

    def set_claim(self, claim_info: typing.Dict, claim: 'ClaimDict'):
        self.stream_claim_info = StoredStreamClaim(
            self.stream_hash, f"{claim_info['txid']}:{claim_info['nout']}", claim_info['claim_id'],
            claim_info['name'], claim_info['amount'], claim_info['height'],
            binascii.hexlify(claim.serialized).decode(), claim.certificate_id, claim_info['address'],
            claim_info['claim_sequence'], claim_info.get('channel_name')
        )
