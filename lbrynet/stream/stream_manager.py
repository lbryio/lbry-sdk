import os
import asyncio
import typing
import binascii
import logging
from lbrynet.mime_types import guess_mime_type
from lbrynet.stream.downloader import StreamDownloader
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.schema.claim import ClaimDict
if typing.TYPE_CHECKING:
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.dht.node import Node
    from lbrynet.storage import SQLiteStorage
    from lbrynet.extras.wallet import LbryWalletManager

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
                 descriptor: StreamDescriptor, download_directory: str, file_name: str,
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
    def status(self):
        return self._status

    def update_status(self, status):
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
    def claim_id(self):
        return None if not self.claim else self.claim.claim_id

    @property
    def txid(self):
        return None if not self.claim else self.claim.txid

    @property
    def nout(self):
        return None if not self.claim else self.claim.nout

    @property
    def outpoint(self):
        return None if not self.claim else self.claim.outpoint

    @property
    def channel_claim_id(self):
        return None if not self.claim else self.claim.channel_claim_id

    @property
    def channel_name(self):
        return None if not self.claim else self.claim.channel_name

    @property
    def claim_name(self):
        return None if not self.claim else self.claim.claim_name

    @property
    def blobs_completed(self):
        return sum([1 if self.blob_manager.get_blob(b.blob_hash).get_is_verified() else 0
                            for b in self.descriptor.blobs[:-1]])

    @property
    def blobs_in_stream(self):
        return len(self.descriptor.blobs) - 1

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
        self.downloader.stop()
        if not self.finished:
            self.update_status(self.STATUS_STOPPED)


class StreamManager:
    def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: 'BlobFileManager', wallet: 'LbryWalletManager',
                 storage: 'SQLiteStorage', node: 'Node', peer_timeout: int, peer_connect_timeout: int):
        self.loop = loop
        self.blob_manager = blob_manager
        self.wallet = wallet
        self.storage = storage
        self.node = node
        self.peer_timeout = peer_timeout
        self.peer_connect_timeout = peer_connect_timeout
        self.streams: typing.Set[ManagedStream] = set()
        self.starting_streams: typing.Dict[str, asyncio.Future] = {}
        self.resume_downloading_task: asyncio.Task = None

    async def resume(self):
        await self.node.joined.wait()
        resumed = 0
        for stream in self.streams:
            if stream.status == ManagedStream.STATUS_RUNNING:
                resumed += 1
                stream.downloader.download(self.node, lambda: stream.update_status(ManagedStream.STATUS_FINISHED))
        if resumed:
            log.info("resumed %i downloads", resumed)

    async def start(self):
        infos = await self.storage.get_all_lbry_files().asFuture(self.loop)
        for file_dict in infos:
            claim_info = await self.storage.get_content_claim(file_dict['stream_hash'], False).asFuture(self.loop)
            sd_blob = self.blob_manager.get_blob(file_dict['sd_hash'])
            if sd_blob.get_is_verified():
                descriptor = await self.blob_manager.get_stream_descriptor(sd_blob.blob_hash)
                stream = self.init_stream_from_database(descriptor, file_dict)
                stream.set_content_claim(claim_info)
        self.resume_downloading_task = self.loop.create_task(self.resume())

    def stop(self):
        while self.streams:
            stream = self.streams.pop()
            stream.stop_download()
        if self.resume_downloading_task and not self.resume_downloading_task.done():
            self.resume_downloading_task.cancel()

    async def create_stream(self, file_path: str) -> ManagedStream:
        stream = await ManagedStream.create(self.loop, self.storage, self.blob_manager, file_path)
        self.streams.add(stream)
        return stream

    async def _download_stream_from_claim(self, node: 'Node', download_directory: str, claim_info: typing.Dict,
                                          file_name: typing.Optional[str] = None,
                                          data_rate: typing.Optional[int] = 0) -> ManagedStream:
        claim = ClaimDict.load_dict(claim_info['value'])
        finished = asyncio.Event(loop=self.loop)
        downloader = StreamDownloader(self.loop, self.blob_manager, claim.source_hash.decode(), self.peer_timeout,
                                      self.peer_connect_timeout, download_directory, file_name)
        downloader.download(node, finished.set)

        await downloader.got_descriptor.wait()

        # TODO: do this in one db call instead of three
        await self.blob_manager.storage.store_stream(downloader.sd_blob, downloader.descriptor).asFuture(self.loop)
        await self.blob_manager.storage.save_downloaded_file(
            downloader.descriptor.stream_hash, os.path.basename(downloader.output_path), download_directory, data_rate
        ).asFuture(self.loop)
        await self.blob_manager.storage.save_content_claim(
            downloader.descriptor.stream_hash, f"{claim_info['txid']}:{claim_info['nout']}"
        ).asFuture(self.loop)

        stream = ManagedStream(self.loop, self.storage, self.blob_manager, downloader.descriptor, download_directory,
                               os.path.basename(downloader.output_path), downloader, ManagedStream.STATUS_RUNNING)
        stream.set_content_claim(claim_info)
        self.streams.add(stream)
        await stream.downloader.wrote_bytes_event.wait()
        return stream

    async def download_stream_from_claim(self, node: 'Node', download_directory: str, claim_info: typing.Dict,
                                         file_name: typing.Optional[str] = None) -> ManagedStream:
        claim = ClaimDict.load_dict(claim_info['value'])
        sd_hash = claim.source_hash.decode()
        if sd_hash in self.starting_streams:
            return await self.starting_streams[sd_hash]
        already_started = tuple(filter(lambda s: s.descriptor.sd_hash == sd_hash, self.streams))
        if already_started:
            return already_started[0]

        self.starting_streams[sd_hash] = asyncio.Future(loop=self.loop)
        stream = await self._download_stream_from_claim(node, download_directory, claim_info, file_name)
        self.starting_streams[sd_hash].set_result(stream)
        if sd_hash in self.starting_streams:
            del self.starting_streams[sd_hash]
        return stream

    async def delete_stream(self, stream: ManagedStream, delete_file: typing.Optional[bool] = False):
        self.streams.remove(stream)
        blob_hashes = [stream.descriptor.sd_hash]
        blob_hashes.extend([blob.blob_hash for blob in stream.descriptor.blobs[:-1]])
        await self.storage.delete_stream(stream.descriptor).asFuture(self.loop)
        await self.blob_manager.delete_blobs(blob_hashes)
        if delete_file:
            path = os.path.join(stream.download_directory, stream.file_name)
            if os.path.isfile(path):
                os.remove(path)

    def init_stream_from_database(self, descriptor: StreamDescriptor, file_info: typing.Dict) -> ManagedStream:
        downloader = StreamDownloader(
            self.loop, self.blob_manager, descriptor.sd_hash, self.peer_timeout,
            self.peer_connect_timeout, binascii.unhexlify(file_info['download_directory']).decode(),
            binascii.unhexlify(file_info['file_name']).decode()
        )
        stream = ManagedStream(
            self.loop, self.storage, self.blob_manager, descriptor,
            binascii.unhexlify(file_info['download_directory']).decode(),
            binascii.unhexlify(file_info['file_name']).decode(),
            downloader, file_info['status']
        )
        self.streams.add(stream)
        return stream
