import os
import asyncio
import typing
import logging
from lbrynet.mime_types import guess_mime_type
from lbrynet.stream.downloader import StreamDownloader
if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.storage import SQLiteStorage
    from lbrynet.stream.descriptor import StreamDescriptor

log = logging.getLogger(__name__)


class StreamClaimInfo:
    def __init__(self, claim_info: typing.Dict):
        self.claim_id = claim_info['claim_id']
        self.txid = claim_info['txid']
        self.nout = claim_info['nout']
        self.channel_claim_id = claim_info.get('channel_claim_id')
        self.outpoint = "%s:%i" % (self.txid, self.nout)
        self.claim_name = claim_info['name']
        self.channel_name = claim_info.get('channel_name')
        self.metadata = claim_info['value']['stream']['metadata']


class ManagedStream:
    STATUS_RUNNING = "running"
    STATUS_STOPPED = "stopped"
    STATUS_FINISHED = "finished"

    def __init__(self,  loop: asyncio.BaseEventLoop, storage: 'SQLiteStorage', blob_manager: 'BlobFileManager',
                 descriptor: 'StreamDescriptor', download_directory: str, file_name: str,
                 downloader: typing.Optional[StreamDownloader] = None, status: typing.Optional[str] = STATUS_STOPPED):
        self.loop = loop
        self.storage = storage
        self.blob_manager = blob_manager
        self.download_directory = download_directory
        self.file_name = file_name
        self.descriptor = descriptor
        self.downloader = downloader
        self.stream_hash = descriptor.stream_hash
        self._claim_info: StreamClaimInfo = None
        self._status = status
        self._store_after_finished: asyncio.Task = None

    @property
    def status(self) -> str:
        return self._status

    def update_status(self, status: str):
        assert status in [self.STATUS_RUNNING, self.STATUS_STOPPED, self.STATUS_FINISHED]
        self._status = status

    @property
    def claim(self) -> typing.Optional[StreamClaimInfo]:
        return self._claim_info

    @property
    def finished(self) -> bool:
        return self.status == self.STATUS_FINISHED

    @property
    def running(self) -> bool:
        return self.status == self.STATUS_RUNNING

    @property
    def claim_id(self) -> typing.Optional[str]:
        return None if not self.claim else self.claim.claim_id

    @property
    def txid(self) -> typing.Optional[str]:
        return None if not self.claim else self.claim.txid

    @property
    def nout(self) -> typing.Optional[int]:
        return None if not self.claim else self.claim.nout

    @property
    def outpoint(self) -> typing.Optional[str]:
        return None if not self.claim else self.claim.outpoint

    @property
    def channel_claim_id(self) -> typing.Optional[str]:
        return None if not self.claim else self.claim.channel_claim_id

    @property
    def channel_name(self) -> typing.Optional[str]:
        return None if not self.claim else self.claim.channel_name

    @property
    def claim_name(self) -> typing.Optional[str]:
        return None if not self.claim else self.claim.claim_name

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

    def as_dict(self) -> typing.Dict:
        full_path = os.path.join(self.download_directory, self.file_name)
        mime_type = guess_mime_type(os.path.basename(self.file_name))
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
            'total_bytes_upper_bound': self.descriptor.upper_bound_decrypted_length(),
            'written_bytes': self.downloader.written_bytes or os.stat(full_path).st_size,
            'blobs_completed': self.blobs_completed,
            'blobs_in_stream': self.blobs_in_stream,
            'status': self.status,
            'claim_id': self.claim_id,
            'txid': self.txid,
            'nout': self.nout,
            'outpoint': self.outpoint,
            'metadata': None if not self.claim else self.claim.metadata,
            'channel_claim_id': self.channel_claim_id,
            'channel_name': self.channel_name,
            'claim_name': self.claim_name
        }

    @classmethod
    async def create(cls, loop: asyncio.BaseEventLoop, storage: 'SQLiteStorage', blob_manager: 'BlobFileManager',
                     file_path: str) -> 'ManagedStream':
        descriptor = await StreamDescriptor.create_stream(
            loop, blob_manager, file_path
        )
        return cls(loop, storage, blob_manager, descriptor, os.path.dirname(file_path), os.path.basename(file_path),
                   status=cls.STATUS_FINISHED)

    def set_content_claim(self, claim_info: typing.Dict):
        self._claim_info = StreamClaimInfo(claim_info)

    async def get_claim_info(self) -> typing.Dict:
        claim_info = await self.storage.get_content_claim(self.downloader.descriptor.stream_hash).asFuture(self.loop)
        if claim_info:
            self.set_content_claim(claim_info)
        return claim_info

    def stop_download(self):
        if self.downloader:
            self.downloader.stop()
        if not self.finished:
            self.update_status(self.STATUS_STOPPED)
