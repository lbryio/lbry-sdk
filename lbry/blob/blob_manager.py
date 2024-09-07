import os
import typing
import asyncio
import logging
from collections import defaultdict
from lbry.utils import LRUCacheWithMetrics
from lbry.blob import BLOBHASH_LENGTH
from lbry.blob.blob_file import (
    HEXMATCH,
    is_valid_blobhash,
    BlobFile,
    BlobBuffer,
    AbstractBlob,
)
from lbry.stream.descriptor import StreamDescriptor
from lbry.connection_manager import ConnectionManager

if typing.TYPE_CHECKING:
    from lbry.conf import Config
    from lbry.dht.protocol.data_store import DictDataStore
    from lbry.extras.daemon.storage import SQLiteStorage

log = logging.getLogger(__name__)


class BlobManager:
    def __init__(self, loop: asyncio.AbstractEventLoop, blob_dirs: typing.List[str],
                 storage: 'SQLiteStorage', config: 'Config',
                 node_data_store: typing.Optional['DictDataStore'] = None):
        """
        This class stores blobs on the hard disk

        blob_dirs - directories where blobs are stored
        storage - SQLiteStorage object
        """
        self.loop = loop
        self.blob_dirs = defaultdict(list)
        self.blob_dirs.update({ '': blob_dirs if isinstance(blob_dirs, list) else [blob_dirs]})
        self.blob_dirs_max_prefix_len = 0  # Maximum key length in "blob_dirs" dictionary.
        self.storage = storage
        self._node_data_store = node_data_store
        self.completed_blob_hashes: typing.Set[str] = set() if not self._node_data_store\
            else self._node_data_store.completed_blobs
        self.blobs: typing.Dict[str, AbstractBlob] = {}
        self.config = config
        self.decrypted_blob_lru_cache = None if not self.config.blob_lru_cache_size else LRUCacheWithMetrics(
            self.config.blob_lru_cache_size)
        self.connection_manager = ConnectionManager(loop)

    def _blob_dir(self, blob_hash: str) -> typing.Tuple[str, bool]:
        """
        Locate blob directory matching longest prefix of blob hash.
        An existing blob is preferred, even if it doesn't reside in
        the directory with longest prefix.
        """
        best_dir = None
        for prefix in [blob_hash[:i] for i in range(min(len(blob_hash), self.blob_dirs_max_prefix_len), -1, -1)]:
            if prefix in self.blob_dirs:
                if not best_dir:
                    best_dir = self.blob_dirs[prefix][0]
                for path in self.blob_dirs[prefix]:
                    if os.path.isfile(os.path.join(path, blob_hash)):
                        #print(f'blob {blob_hash} FOUND at location: {path}')
                        return path, True
        #print(f'blob {blob_hash} has BEST location: {best_dir}')
        return best_dir, False


    def _get_blob(self, blob_hash: str, length: typing.Optional[int] = None, is_mine: bool = False):
        if self.config.save_blobs:
            return BlobFile(
                self.loop, blob_hash, length, self.blob_completed, self, is_mine=is_mine
            )
        _, blob_found = self._blob_dir(blob_hash)
        if blob_found:
            return BlobFile(
                self.loop, blob_hash, length, self.blob_completed, self, is_mine=is_mine
            )
        return BlobBuffer(
            self.loop, blob_hash, length, self.blob_completed, self, is_mine=is_mine
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
        _, blob_found = self._blob_dir(blob_hash)
        if not blob_found:
            return False
        if blob_hash in self.blobs:
            return self.blobs[blob_hash].get_is_verified()
        return self._get_blob(blob_hash, length).get_is_verified()

    def list_blobs(self, paths = None, prefix = '', setup=False):
        """
        Recursively search for blob files within path(s) and subdirectories.
        When setup=True, subdirectories which are candidates for blob storage
        are added to the "self.blob_dirs" dictionary.
        """
        blobfiles = set()
        subdirs = defaultdict(list)
        for path in paths if paths is not None else self.blob_dirs[prefix]:
            with os.scandir(path) as entries:
                for item in entries:
                    if item.is_file() and is_valid_blobhash(item.name):
                        blobfiles.add(item.name)
                    elif item.is_dir() and len(prefix+item.name) < BLOBHASH_LENGTH and HEXMATCH.match(item.name):
                        subdirs[item.name].append(item.path)
        # Recursively process subdirectories which may also contain blobs.
        for name, subdir_paths in subdirs.items():
            if setup:
                self.blob_dirs[prefix+name] = subdir_paths
                self.blob_dirs_max_prefix_len = max(self.blob_dirs_max_prefix_len, len(prefix+name))
            blobfiles.update(self.list_blobs(paths=subdir_paths, prefix=prefix+name, setup=setup))
        return blobfiles

    async def setup(self) -> bool:
        in_blobfiles_dir = await self.loop.run_in_executor(None, lambda: self.list_blobs(setup=True))
        #print(f'blob dirs: {self.blob_dirs}')
        to_add = await self.storage.sync_missing_blobs(in_blobfiles_dir)
        if to_add:
            self.completed_blob_hashes.update(to_add)
        # check blobs that aren't set as finished but were seen on disk
        await self.ensure_completed_blobs_status(in_blobfiles_dir - to_add)
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
        return StreamDescriptor.from_stream_descriptor_blob(self.loop, self, self.get_blob(sd_hash))

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

    async def ensure_completed_blobs_status(self, blob_hashes: typing.Iterable[str]):
        """Ensures that completed blobs from a given list of blob hashes are set as 'finished' in the database."""
        to_add = []
        for blob_hash in blob_hashes:
            if not self.is_blob_verified(blob_hash):
                continue
            blob = self.get_blob(blob_hash)
            to_add.append((blob.blob_hash, blob.length, blob.added_on, blob.is_mine))
            if len(to_add) > 500:
                await self.storage.add_blobs(*to_add, finished=True)
                to_add.clear()
        return await self.storage.add_blobs(*to_add, finished=True)

    def delete_blob(self, blob_hash: str):
        if not is_valid_blobhash(blob_hash):
            raise Exception("invalid blob hash to delete")

        if blob_hash not in self.blobs:
            blob_dir, blob_found = self._blob_dir(blob_hash)
            if blob_dir and blob_found:
                os.remove(os.path.join(blob_dir, blob_hash))
        else:
            self.blobs.pop(blob_hash).delete()
            if blob_hash in self.completed_blob_hashes:
                self.completed_blob_hashes.remove(blob_hash)

    async def delete_blobs(self, blob_hashes: typing.List[str], delete_from_db: typing.Optional[bool] = True):
        for blob_hash in blob_hashes:
            self.delete_blob(blob_hash)

        if delete_from_db:
            await self.storage.delete_blobs_from_db(blob_hashes)
