import os
import typing
import asyncio
import logging
from lbry.utils import LRUCacheWithMetrics
from lbry.blob.blob_file import is_valid_blobhash, BlobFile, BlobBuffer, AbstractBlob
from lbry.stream.descriptor import StreamDescriptor
from lbry.connection_manager import ConnectionManager

if typing.TYPE_CHECKING:
    from lbry.conf import Config
    from lbry.dht.protocol.data_store import DictDataStore
    from lbry.extras.daemon.storage import SQLiteStorage

log = logging.getLogger(__name__)


class BlobManager:
    def __init__(self, loop: asyncio.AbstractEventLoop, blob_dir: str, storage: 'SQLiteStorage', config: 'Config',
                 node_data_store: typing.Optional['DictDataStore'] = None):
        """
        This class stores blobs on the hard disk

        blob_dir - directory where blobs are stored
        storage - SQLiteStorage object
        """
        self.loop = loop
        self.blob_dir = blob_dir
        self.storage = storage
        self._node_data_store = node_data_store
        self.completed_blob_hashes: typing.Set[str] = set() if not self._node_data_store\
            else self._node_data_store.completed_blobs
        self.blobs: typing.Dict[str, AbstractBlob] = {}
        self.config = config
        self.decrypted_blob_lru_cache = None if not self.config.blob_lru_cache_size else LRUCacheWithMetrics(
            self.config.blob_lru_cache_size)
        self.connection_manager = ConnectionManager(loop)

    def _get_blob(self, blob_hash: str, length: typing.Optional[int] = None, is_mine: bool = False):
        if self.config.save_blobs or (
                is_valid_blobhash(blob_hash) and os.path.isfile(os.path.join(self.blob_dir, blob_hash))):
            return BlobFile(
                self.loop, blob_hash, length, self.blob_completed, self.blob_dir, is_mine=is_mine
            )
        return BlobBuffer(
            self.loop, blob_hash, length, self.blob_completed, self.blob_dir, is_mine=is_mine
        )

    def get_blob(self, blob_hash, length: typing.Optional[int] = None, is_mine: bool = False):
        if blob_hash in self.blobs:
            if self.config.save_blobs and isinstance(self.blobs[blob_hash], BlobBuffer):
                buffer = self.blobs.pop(blob_hash)
                if blob_hash in self.completed_blob_hashes:
                    self.completed_blob_hashes.remove(blob_hash)
                self.blobs[blob_hash] = self._get_blob(blob_hash, length, is_mine)
                if buffer.is_readable():
                    with buffer.reader_context() as reader:
                        self.blobs[blob_hash].write_blob(reader.read())
            if length and self.blobs[blob_hash].length is None:
                self.blobs[blob_hash].set_length(length)
        else:
            self.blobs[blob_hash] = self._get_blob(blob_hash, length, is_mine)
        return self.blobs[blob_hash]

    def is_blob_verified(self, blob_hash: str, length: typing.Optional[int] = None) -> bool:
        if not is_valid_blobhash(blob_hash):
            raise ValueError(blob_hash)
        if not os.path.isfile(os.path.join(self.blob_dir, blob_hash)):
            return False
        if blob_hash in self.blobs:
            return self.blobs[blob_hash].get_is_verified()
        return self._get_blob(blob_hash, length).get_is_verified()

    async def setup(self) -> bool:
        def get_files_in_blob_dir() -> typing.Set[str]:
            if not self.blob_dir:
                return set()
            return {
                item.name for item in os.scandir(self.blob_dir) if is_valid_blobhash(item.name)
            }

        in_blobfiles_dir = await self.loop.run_in_executor(None, get_files_in_blob_dir)
        to_add = await self.storage.sync_missing_blobs(in_blobfiles_dir)
        if to_add:
            self.completed_blob_hashes.update(to_add)
        if self.config.track_bandwidth:
            self.connection_manager.start()
        return True

    def stop(self):
        self.connection_manager.stop()
        while self.blobs:
            _, blob = self.blobs.popitem()
            blob.close()
        self.completed_blob_hashes.clear()

    def get_stream_descriptor(self, sd_hash):
        return StreamDescriptor.from_stream_descriptor_blob(self.loop, self.blob_dir, self.get_blob(sd_hash))

    def blob_completed(self, blob: AbstractBlob) -> asyncio.Task:
        if blob.blob_hash is None:
            raise Exception("Blob hash is None")
        if not blob.length:
            raise Exception("Blob has a length of 0")
        if isinstance(blob, BlobFile):
            if blob.blob_hash not in self.completed_blob_hashes:
                self.completed_blob_hashes.add(blob.blob_hash)
            return self.loop.create_task(self.storage.add_blobs(
                (blob.blob_hash, blob.length, blob.added_on, blob.is_mine), finished=True)
            )
        else:
            return self.loop.create_task(self.storage.add_blobs(
                (blob.blob_hash, blob.length, blob.added_on, blob.is_mine), finished=False)
            )

    def ensure_completed_blobs_status(self, blob_hashes: typing.List[str]) -> asyncio.Task:
        """Ensures that completed blobs from a given list of blob hashes are set as 'finished' in the database."""
        to_add = []
        for blob_hash in blob_hashes:
            if not self.is_blob_verified(blob_hash):
                continue
            blob = self.get_blob(blob_hash)
            to_add.append((blob.blob_hash, blob.length, blob.added_on, blob.is_mine))
        return self.loop.create_task(self.storage.add_blobs(*to_add, finished=True))

    def delete_blob(self, blob_hash: str):
        if not is_valid_blobhash(blob_hash):
            raise Exception("invalid blob hash to delete")

        if blob_hash not in self.blobs:
            if self.blob_dir and os.path.isfile(os.path.join(self.blob_dir, blob_hash)):
                os.remove(os.path.join(self.blob_dir, blob_hash))
        else:
            self.blobs.pop(blob_hash).delete()
            if blob_hash in self.completed_blob_hashes:
                self.completed_blob_hashes.remove(blob_hash)

    async def delete_blobs(self, blob_hashes: typing.List[str], delete_from_db: typing.Optional[bool] = True):
        for blob_hash in blob_hashes:
            self.delete_blob(blob_hash)

        if delete_from_db:
            await self.storage.delete_blobs_from_db(blob_hashes)
