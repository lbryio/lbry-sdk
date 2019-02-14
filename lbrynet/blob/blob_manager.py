import os
import typing
import asyncio
import logging
from lbrynet.extras.daemon.storage import SQLiteStorage
from lbrynet.blob.blob_file import BlobFile, is_valid_blobhash
from lbrynet.stream.descriptor import StreamDescriptor

if typing.TYPE_CHECKING:
    from lbrynet.dht.protocol.data_store import DictDataStore

log = logging.getLogger(__name__)


class BlobFileManager:
    def __init__(self, loop: asyncio.BaseEventLoop, blob_dir: str, storage: SQLiteStorage,
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
        self.blobs: typing.Dict[str, BlobFile] = {}

    async def setup(self) -> bool:
        def initialize_blob_hashes():
            self.completed_blob_hashes.update(
                item.name for item in os.scandir(self.blob_dir) if is_valid_blobhash(item.name)
            )
        await self.loop.run_in_executor(None, initialize_blob_hashes)
        return True

    def get_blob(self, blob_hash, length: typing.Optional[int] = None):
        if blob_hash in self.blobs:
            if length and self.blobs[blob_hash].length is None:
                self.blobs[blob_hash].set_length(length)
        else:
            self.blobs[blob_hash] = BlobFile(self.loop, self.blob_dir, blob_hash, length, self.blob_completed)
        return self.blobs[blob_hash]

    def get_stream_descriptor(self, sd_hash):
        return StreamDescriptor.from_stream_descriptor_blob(self.loop, self.blob_dir, self.get_blob(sd_hash))

    async def blob_completed(self, blob: BlobFile):
        if blob.blob_hash is None:
            raise Exception("Blob hash is None")
        if not blob.length:
            raise Exception("Blob has a length of 0")
        if blob.blob_hash not in self.completed_blob_hashes:
            self.completed_blob_hashes.add(blob.blob_hash)
        await self.storage.add_completed_blob(blob.blob_hash)

    def check_completed_blobs(self, blob_hashes: typing.List[str]) -> typing.List[str]:
        """Returns of the blobhashes_to_check, which are valid"""
        blobs = [self.get_blob(b) for b in blob_hashes]
        return [blob.blob_hash for blob in blobs if blob.get_is_verified()]

    def delete_blob(self, blob_hash: str):
        if not is_valid_blobhash(blob_hash):
            raise Exception("invalid blob hash to delete")

        if blob_hash not in self.blobs:
            if os.path.isfile(os.path.join(self.blob_dir, blob_hash)):
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
