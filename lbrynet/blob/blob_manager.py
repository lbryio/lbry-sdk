import os
import typing
import asyncio
import logging
from lbrynet.blob.blob_file import is_valid_blobhash, BlobFile, BlobBuffer, AbstractBlob
from lbrynet.stream.descriptor import StreamDescriptor

if typing.TYPE_CHECKING:
    from lbrynet.conf import Config
    from lbrynet.dht.protocol.data_store import DictDataStore
    from lbrynet.extras.daemon.storage import SQLiteStorage

log = logging.getLogger(__name__)


class BlobManager:
    def __init__(self, loop: asyncio.BaseEventLoop, blob_dir: str, storage: 'SQLiteStorage', config: 'Config',
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

    def _get_blob(self, blob_hash: str, length: typing.Optional[int] = None):
        if self.config.save_blobs:
            return BlobFile(
                self.loop, blob_hash, length, self.blob_completed, self.blob_dir
            )
        else:
            if length and is_valid_blobhash(blob_hash) and os.path.isfile(os.path.join(self.blob_dir, blob_hash)):
                return BlobFile(
                    self.loop, blob_hash, length, self.blob_completed, self.blob_dir
                )
            return BlobBuffer(
                self.loop, blob_hash, length, self.blob_completed, self.blob_dir
            )

    def get_blob(self, blob_hash, length: typing.Optional[int] = None):
        if blob_hash in self.blobs:
            if length and self.blobs[blob_hash].length is None:
                self.blobs[blob_hash].set_length(length)
        else:
            self.blobs[blob_hash] = self._get_blob(blob_hash, length)
        return self.blobs[blob_hash]

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
        return True

    def stop(self):
        while self.blobs:
            _, blob = self.blobs.popitem()
            blob.close()
        self.completed_blob_hashes.clear()

    def get_stream_descriptor(self, sd_hash):
        return StreamDescriptor.from_stream_descriptor_blob(self.loop, self.blob_dir, self.get_blob(sd_hash))

    def blob_completed(self, blob: AbstractBlob):
        if blob.blob_hash is None:
            raise Exception("Blob hash is None")
        if not blob.length:
            raise Exception("Blob has a length of 0")
        if not blob.get_is_verified():
            raise Exception("Blob is not verified")
        if isinstance(blob, BlobFile):
            if blob.blob_hash not in self.completed_blob_hashes:
                self.completed_blob_hashes.add(blob.blob_hash)
            self.loop.create_task(self.storage.add_blobs((blob.blob_hash, blob.length), finished=True))
        else:
            self.loop.create_task(self.storage.add_blobs((blob.blob_hash, blob.length), finished=False))

    def check_completed_blobs(self, blob_hashes: typing.List[str]) -> typing.List[str]:
        """Returns of the blobhashes_to_check, which are valid"""
        blobs = [self.get_blob(b) for b in blob_hashes]
        return [blob.blob_hash for blob in blobs if blob.get_is_verified()]

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
