import typing
import asyncio
import logging
from binascii import unhexlify
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
        # TODO: consider using an LRU for blobs as there could potentially
        #       be thousands of blobs loaded up, many stale
        self.blobs = {}
        self.completed_blob_hashes: typing.Set[str] = set()

    async def setup(self) -> bool:
        raw_blob_hashes = await self.storage.get_all_finished_blobs().asFuture(self.loop)
        self.completed_blob_hashes.update(raw_blob_hashes)
        if self._node_datastore is not None:
            self._node_datastore.completed_blobs.update(raw_blob_hashes)
        return True

    async def stop(self) -> bool:
        f = asyncio.Future(loop=self.loop)
        f.set_result(True)
        return await f

    def get_blob(self, blob_hash: str, length: typing.Optional[int] = None) -> BlobFile:
        """Return a blob identified by blob_hash, which may be a new blob or a
        blob that is already on the hard disk
        """
        if length is not None and not isinstance(length, int):
            raise Exception("invalid length type: {} ({})".format(length, str(type(length))))
        if blob_hash in self.blobs:
            return self.blobs[blob_hash]
        log.debug('Making a new blob for %s', blob_hash)
        blob = BlobFile(self.loop, self.blob_dir, blob_hash, length)
        self.blobs[blob_hash] = blob
        return blob

    def get_stream_descriptor(self, sd_hash):
        return StreamDescriptor.from_stream_descriptor_blob(self.loop, self.get_blob(sd_hash))

    async def create_stream(self, file_path: str, key: typing.Optional[bytes] = None,
                            iv_generator: typing.Optional[typing.Generator[bytes,
                                                                           None, None]] = None) -> StreamDescriptor:
        descriptor = await StreamDescriptor.create_stream(self.loop, self.storage, self.blob_dir, file_path, key,
                                                          iv_generator)
        futs = [
            self.blob_completed(
                BlobFile(self.loop, self.blob_dir, descriptor.sd_hash, len(descriptor.as_json())),
                should_announce=True, next_announce_time=0
            ), self.blob_completed(
                BlobFile(self.loop, self.blob_dir, descriptor.blobs[0].blob_hash, descriptor.blobs[0].length),
                should_announce=True, next_announce_time=0
            )
        ]
        if len(descriptor.blobs) > 2:
            for blob_info in descriptor.blobs[1:-1]:
                futs.append(self.blob_completed(
                    BlobFile(self.loop, self.blob_dir, blob_info.blob_hash, blob_info.length),
                ))

        await asyncio.gather(*tuple([asyncio.ensure_future(f, loop=self.loop) for f in futs]), loop=self.loop)
        await descriptor.save_to_database(self.loop, self)
        return descriptor

    async def blob_completed(self, blob: BlobFile, should_announce: typing.Optional[bool] = False,
                             next_announce_time: typing.Optional[float] = None):
        if blob.blob_hash is None:
            raise Exception("Blob hash is None")
        if not blob.length:
            raise Exception("Blob has a length of 0")
        if blob.blob_hash not in self.completed_blob_hashes:
            self.completed_blob_hashes.add(blob.blob_hash)
        if self._node_datastore is not None:
            self._node_datastore.completed_blobs.add(unhexlify(blob.blob_hash))

        if blob.blob_hash in self.blobs:
            if not self.blobs[blob.blob_hash].length:
                self.blobs[blob.blob_hash].length = blob.length
        else:
            self.blobs[blob.blob_hash] = blob
        await self.storage.add_completed_blob(
            blob.blob_hash, blob.length, next_announce_time, should_announce
        ).asFuture(self.loop)

    def check_completed_blobs(self, blob_hashes: typing.List[str]) -> typing.List[str]:
        """Returns of the blobhashes_to_check, which are valid"""
        blobs = [self.get_blob(b) for b in blob_hashes]
        return [blob.blob_hash for blob in blobs if blob.get_is_verified()]

    async def count_should_announce_blobs(self):
        return await self.storage.count_should_announce_blobs().asFuture(self.loop)

    async def set_should_announce(self, blob_hash: str, should_announce: bool):
        now = self.storage.clock.seconds()
        return await self.storage.set_should_announce(blob_hash, now, should_announce).asFuture(self.loop)

    async def get_should_announce(self, blob_hash: str) -> bool:
        return await self.storage.should_announce(blob_hash).asFuture(self.loop)

    async def get_all_verified_blobs(self) -> typing.List[str]:
        blob_hashes = await self.storage.get_all_blob_hashes().asFuture(self.loop)
        return self.check_completed_blobs(blob_hashes)

    async def delete_blobs(self, blob_hashes):
        bh_to_delete_from_db = []
        for blob_hash in blob_hashes:
            if not blob_hash:
                continue
            if self._node_datastore is not None:
                try:
                    self._node_datastore.completed_blobs.remove(unhexlify(blob_hash))
                except KeyError:
                    pass
            try:
                blob = self.get_blob(blob_hash)
                await blob.delete()
                bh_to_delete_from_db.append(blob_hash)
                del self.blobs[blob_hash]
            except Exception as e:
                log.warning("Failed to delete blob file. Reason: %s", e)
        try:
            await self.storage.delete_blobs_from_db(bh_to_delete_from_db).asFuture(self.loop)
        except IntegrityError as err:
            if str(err) != "FOREIGN KEY constraint failed":
                raise err
