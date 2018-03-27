import logging
import os
from sqlite3 import IntegrityError
from twisted.internet import threads, defer, task
from lbrynet import conf
from lbrynet.blob.blob_file import BlobFile
from lbrynet.blob.creator import BlobFileCreator

log = logging.getLogger(__name__)


class DiskBlobManager(object):
    def __init__(self, blob_dir, storage):
        """
        This class stores blobs on the hard disk

        blob_dir - directory where blobs are stored
        storage - SQLiteStorage object
        """
        self.storage = storage
        self.blob_dir = blob_dir
        self.blob_creator_type = BlobFileCreator
        # TODO: consider using an LRU for blobs as there could potentially
        #       be thousands of blobs loaded up, many stale
        self.blobs = {}
        self.blob_hashes_to_delete = {}  # {blob_hash: being_deleted (True/False)}

        self.check_should_announce_lc = None
        if conf.settings['run_reflector_server']: # TODO: move this looping call to SQLiteStorage
            self.check_should_announce_lc = task.LoopingCall(self.storage.verify_will_announce_all_head_and_sd_blobs)

    def setup(self):
        if self.check_should_announce_lc and not self.check_should_announce_lc.running:
            self.check_should_announce_lc.start(600)
        return defer.succeed(True)

    def stop(self):
        if self.check_should_announce_lc and self.check_should_announce_lc.running:
            self.check_should_announce_lc.stop()
        return defer.succeed(True)

    def get_blob(self, blob_hash, length=None):
        """Return a blob identified by blob_hash, which may be a new blob or a
        blob that is already on the hard disk
        """
        if length is not None and not isinstance(length, int):
            raise Exception("invalid length type: %s (%s)" % (length, str(type(length))))
        if blob_hash in self.blobs:
            return defer.succeed(self.blobs[blob_hash])
        return self._make_new_blob(blob_hash, length)

    def get_blob_creator(self):
        return self.blob_creator_type(self.blob_dir)

    def _make_new_blob(self, blob_hash, length=None):
        log.debug('Making a new blob for %s', blob_hash)
        blob = BlobFile(self.blob_dir, blob_hash, length)
        self.blobs[blob_hash] = blob
        return defer.succeed(blob)

    @defer.inlineCallbacks
    def blob_completed(self, blob, next_announce_time=None, should_announce=True):
        yield self.storage.add_completed_blob(
            blob.blob_hash, blob.length, next_announce_time, should_announce
        )

    def completed_blobs(self, blobhashes_to_check):
        return self._completed_blobs(blobhashes_to_check)

    def count_should_announce_blobs(self):
        return self.storage.count_should_announce_blobs()

    def set_should_announce(self, blob_hash, should_announce):
        return self.storage.set_should_announce(blob_hash, should_announce)

    def get_should_announce(self, blob_hash):
        return self.storage.should_announce(blob_hash)

    def creator_finished(self, blob_creator, should_announce):
        log.debug("blob_creator.blob_hash: %s", blob_creator.blob_hash)
        if blob_creator.blob_hash is None:
            raise Exception("Blob hash is None")
        if blob_creator.blob_hash in self.blobs:
            raise Exception("Creator finished for blob that is already marked as completed")
        if blob_creator.length is None:
            raise Exception("Blob has a length of 0")
        new_blob = BlobFile(self.blob_dir, blob_creator.blob_hash, blob_creator.length)
        self.blobs[blob_creator.blob_hash] = new_blob
        return self.blob_completed(new_blob, should_announce)

    def get_all_verified_blobs(self):
        d = self._get_all_verified_blob_hashes()
        d.addCallback(self.completed_blobs)
        return d

    @defer.inlineCallbacks
    def delete_blobs(self, blob_hashes):
        bh_to_delete_from_db = []
        for blob_hash in blob_hashes:
            try:
                blob = yield self.get_blob(blob_hash)
                yield blob.delete()
                bh_to_delete_from_db.append(blob_hash)
                del self.blobs[blob_hash]
            except Exception as e:
                log.warning("Failed to delete blob file. Reason: %s", e)
        try:
            yield self.storage.delete_blobs_from_db(bh_to_delete_from_db)
        except IntegrityError as err:
            if err.message != "FOREIGN KEY constraint failed":
                raise err

    @defer.inlineCallbacks
    def _completed_blobs(self, blobhashes_to_check):
        """Returns of the blobhashes_to_check, which are valid"""
        blobs = yield defer.DeferredList([self.get_blob(b) for b in blobhashes_to_check])
        blob_hashes = [b.blob_hash for success, b in blobs if success and b.verified]
        defer.returnValue(blob_hashes)

    def _get_all_verified_blob_hashes(self):
        d = self.storage.get_all_blob_hashes()

        def get_verified_blobs(blobs):
            verified_blobs = []
            for blob_hash in blobs:
                file_path = os.path.join(self.blob_dir, blob_hash)
                if os.path.isfile(file_path):
                    verified_blobs.append(blob_hash)
            return verified_blobs

        d.addCallback(lambda blobs: threads.deferToThread(get_verified_blobs, blobs))
        return d
