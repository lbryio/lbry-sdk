import typing
import asyncio
import logging
from sqlite3 import IntegrityError
from lbrynet.dht.protocol.data_store import DictDataStore
from lbrynet.storage import SQLiteStorage
from lbrynet.blob.blob_file import BlobFile
from lbrynet.stream.descriptor import StreamDescriptor

log = logging.getLogger(__name__)


class BlobFileManager:
    def __init__(self, loop: asyncio.BaseEventLoop, blob_dir: str, storage: SQLiteStorage,
                 node_datastore: typing.Optional[DictDataStore] = None):
        """
        This class stores blobs on the hard disk

        blob_dir - directory where blobs are stored
        storage - SQLiteStorage object
        """
        self.loop = loop
        self.blob_dir = blob_dir
        self.storage = storage
        self._node_datastore = node_datastore
        self.completed_blob_hashes: typing.Set[str] = set() if not self._node_datastore else \
                                                      self._node_datastore.completed_blobs

    async def setup(self) -> bool:
        raw_blob_hashes = await self.get_all_verified_blobs()
        self.completed_blob_hashes.update(raw_blob_hashes)
        return True

    def get_blob(self, blob_hash, length: typing.Optional[int] = None):
        return BlobFile(self.loop, self.blob_dir, blob_hash, length, self.blob_completed)

    def get_stream_descriptor(self, sd_hash):
        return StreamDescriptor.from_stream_descriptor_blob(self.loop, self, self.get_blob(sd_hash))

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

    async def set_should_announce(self, blob_hash: str, should_announce: bool):
        now = self.loop.time()
        return await self.storage.set_should_announce(blob_hash, now, should_announce)

    async def get_all_verified_blobs(self) -> typing.List[str]:
        blob_hashes = await self.storage.get_all_blob_hashes()
        return self.check_completed_blobs(blob_hashes)

    async def delete_blobs(self, blob_hashes: typing.List[str]):
        bh_to_delete_from_db = []
        for blob_hash in blob_hashes:
            if not blob_hash:
                continue
            try:
                blob = self.get_blob(blob_hash)
                await blob.delete()
                bh_to_delete_from_db.append(blob_hash)
            except Exception as e:
                log.warning("Failed to delete blob file. Reason: %s", e)
            if blob_hash in self.completed_blob_hashes:
                self.completed_blob_hashes.remove(blob_hash)
        try:
            await self.storage.delete_blobs_from_db(bh_to_delete_from_db)
        except IntegrityError as err:
            if str(err) != "FOREIGN KEY constraint failed":
                raise err
