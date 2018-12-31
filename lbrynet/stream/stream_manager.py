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

log = logging.getLogger()


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
                 node: 'Node', descriptor: StreamDescriptor, stream_hash: str, download_directory: str, file_name: str,
                 peer_timeout: int, peer_connect_timeout: int, status: typing.Optional[str] = STATUS_STOPPED,
                 downloader: typing.Optional[StreamDownloader] = None):
        self.loop = loop
        self.storage = storage
        self.blob_manager = blob_manager
        self.node = node
        self.download_directory = download_directory
        self.file_name = file_name
        self.descriptor = descriptor
        self.downloader = downloader or StreamDownloader(
            self.loop, self.blob_manager, self.node, descriptor.sd_hash, peer_timeout,
            peer_connect_timeout, self.download_directory, self.file_name
        )
        self.stream_hash = stream_hash
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
                 node: 'Node', file_path: str, peer_timeout: int, peer_connect_timeout: int) -> 'ManagedStream':
        descriptor = await StreamDescriptor.create_stream(
            loop, blob_manager, file_path
        )
        return cls(loop, storage, blob_manager, node, descriptor, descriptor.stream_hash,
                   os.path.dirname(file_path), os.path.basename(file_path), peer_timeout, peer_connect_timeout,
                   cls.STATUS_FINISHED)

    @classmethod
    async def download_from_claim(cls, loop: asyncio.BaseEventLoop, storage: 'SQLiteStorage',
                                  blob_manager: 'BlobFileManager', node: 'Node', claim_info: typing.Dict,
                                  download_directory: str, file_name: str, peer_timeout: int,
                                  peer_connect_timeout: int,
                                  data_rate: typing.Optional[int] = 0) -> 'ManagedStream':
        claim = ClaimDict.load_dict(claim_info['value'])
        finished = asyncio.Event(loop=loop)

        downloader = StreamDownloader(loop, blob_manager, node, claim.source_hash.decode(), peer_timeout,
                                      peer_connect_timeout, download_directory, file_name)
        downloader.download(finished.set)
        await downloader.got_descriptor.wait()

        # TODO: do this in one db call instead of three
        await blob_manager.storage.store_stream(downloader.sd_blob, downloader.descriptor).asFuture(loop)
        await blob_manager.storage.save_downloaded_file(
            downloader.descriptor.stream_hash, os.path.basename(downloader.output_path), download_directory, data_rate
        ).asFuture(loop)
        await blob_manager.storage.save_content_claim(
            downloader.descriptor.stream_hash, f"{claim_info['txid']}:{claim_info['nout']}"
        ).asFuture(loop)

        self = cls(loop, storage, blob_manager, node, downloader.descriptor, downloader.descriptor.stream_hash,
                   download_directory, os.path.basename(downloader.output_path), peer_timeout, peer_connect_timeout,
                   cls.STATUS_RUNNING, downloader)
        self.set_content_claim(claim_info)
        await self.downloader.wrote_bytes_event.wait()
        return self

    def stop_download(self):
        self.downloader.stop()
        if not self.finished:
            self.update_status(self.STATUS_STOPPED)

    async def wait_for_first_blob_decrypted(self):
        if not self.running:
            raise Exception("not running")
        await self.downloader.first_bytes_written.wait()

    async def wait_for_download_finished(self):
        if not self.running:
            raise Exception("not running")
        await self.downloader.download_finished.wait()

    def set_content_claim(self, claim_info: typing.Dict):
        self._claim_info = StreamClaimInfo(claim_info)

    async def get_claim_info(self) -> typing.Dict:
        claim_info = await self.storage.get_content_claim(self.downloader.descriptor.stream_hash).asFuture(self.loop)
        if claim_info:
            self.set_content_claim(claim_info)
        return claim_info


class StreamManager:
    def __init__(self, loop: asyncio.BaseEventLoop, node: 'Node', blob_manager: 'BlobFileManager',
                 wallet: 'LbryWalletManager', storage: 'SQLiteStorage', peer_timeout: int,
                 peer_connect_timeout: int):
        self.loop = loop
        self.node = node
        self.blob_manager = blob_manager
        self.wallet = wallet
        self.storage = storage
        self.peer_timeout = peer_timeout
        self.peer_connect_timeout = peer_connect_timeout
        self.streams: typing.Set[ManagedStream] = set()
        self.starting_streams: typing.Dict[str, asyncio.Future] = {}

    async def start(self):
        infos = await self.storage.get_all_lbry_files().asFuture(self.loop)
        for file_dict in infos:
            claim_info = await self.storage.get_content_claim(file_dict['stream_hash'], False).asFuture(self.loop)
            sd_blob = self.blob_manager.get_blob(file_dict['sd_hash'])
            if sd_blob.get_is_verified():
                descriptor = await self.blob_manager.get_stream_descriptor(sd_blob.blob_hash)

                downloader = StreamDownloader(
                        self.loop, self.blob_manager, self.node, descriptor.sd_hash, self.peer_timeout,
                        self.peer_connect_timeout, binascii.unhexlify(file_dict['download_directory']).decode(),
                        binascii.unhexlify(file_dict['file_name']).decode()
                    )

                stream = ManagedStream(
                    self.loop, self.storage, self.blob_manager, self.node, descriptor,
                    file_dict['stream_hash'], binascii.unhexlify(file_dict['download_directory']).decode(),
                    binascii.unhexlify(file_dict['file_name']).decode(),
                    self.peer_timeout, self.peer_connect_timeout, file_dict['status'], downloader
                )
                if stream.status == ManagedStream.STATUS_RUNNING:
                    stream.downloader.download(lambda: stream.update_status(ManagedStream.STATUS_FINISHED))
                stream.set_content_claim(claim_info)
                self.streams.add(stream)

    def stop(self):
        while self.streams:
            stream = self.streams.pop()
            stream.stop_download()

    async def create_stream(self, file_path: str) -> ManagedStream:
        stream = await ManagedStream.create(self.loop, self.storage, self.blob_manager, self.node, file_path,
                                            self.peer_timeout, self.peer_connect_timeout)
        self.streams.add(stream)
        return stream

    async def _download_stream_from_claim(self, download_directory: str, claim_info: typing.Dict,
                                         file_name: typing.Optional[str] = None) -> ManagedStream:
        stream = await ManagedStream.download_from_claim(
            self.loop, self.storage, self.blob_manager, self.node, claim_info, download_directory, file_name,
            self.peer_timeout, self.peer_connect_timeout
        )
        self.streams.add(stream)
        return stream

    async def download_stream_from_claim(self, download_directory: str, claim_info: typing.Dict,
                                         file_name: typing.Optional[str] = None) -> ManagedStream:
        claim = ClaimDict.load_dict(claim_info['value'])
        sd_hash = claim.source_hash.decode()
        if sd_hash in self.starting_streams:
            return await self.starting_streams[sd_hash]
        already_started = tuple(filter(lambda s: s.descriptor.sd_hash == sd_hash, self.streams))
        if already_started:
            return already_started[0]

        self.starting_streams[sd_hash] = asyncio.Future(loop=self.loop)
        stream = await self._download_stream_from_claim(download_directory, claim_info, file_name)
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

        # {
        #     "row_id": rowid,
        #     "stream_hash": stream_hash,
        #     "file_name": file_name,
        #     "download_directory": download_dir,
        #     "blob_data_rate": data_rate,
        #     "status": status,
        #     "sd_hash": sd_hash,
        #     "key": stream_key,
        #     "stream_name": stream_name,
        #     "suggested_file_name": suggested_file_name
        # }
