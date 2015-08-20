import logging
import os
import leveldb
import time
import json
from twisted.internet import threads, defer, reactor, task
from twisted.python.failure import Failure
from lbrynet.core.HashBlob import BlobFile, TempBlob, BlobFileCreator, TempBlobCreator
from lbrynet.core.server.DHTHashAnnouncer import DHTHashSupplier
from lbrynet.core.utils import is_valid_blobhash
from lbrynet.core.cryptoutils import get_lbry_hash_obj


class BlobManager(DHTHashSupplier):
    """This class is subclassed by classes which keep track of which blobs are available
       and which give access to new/existing blobs"""
    def __init__(self, hash_announcer):
        DHTHashSupplier.__init__(self, hash_announcer)

    def setup(self):
        pass

    def get_blob(self, blob_hash, upload_allowed, length):
        pass

    def get_blob_creator(self):
        pass

    def _make_new_blob(self, blob_hash, upload_allowed, length):
        pass

    def blob_completed(self, blob, next_announce_time=None):
        pass

    def completed_blobs(self, blobs_to_check):
        pass

    def hashes_to_announce(self):
        pass

    def creator_finished(self, blob_creator):
        pass

    def delete_blob(self, blob_hash):
        pass

    def get_blob_length(self, blob_hash):
        pass

    def check_consistency(self):
        pass

    def blob_requested(self, blob_hash):
        pass

    def blob_downloaded(self, blob_hash):
        pass

    def blob_searched_on(self, blob_hash):
        pass

    def blob_paid_for(self, blob_hash, amount):
        pass


class DiskBlobManager(BlobManager):
    """This class stores blobs on the hard disk"""
    def __init__(self, hash_announcer, blob_dir, db_dir):
        BlobManager.__init__(self, hash_announcer)
        self.blob_dir = blob_dir
        self.db_dir = db_dir
        self.db = None
        self.blob_type = BlobFile
        self.blob_creator_type = BlobFileCreator
        self.blobs = {}
        self.blob_hashes_to_delete = {}  # {blob_hash: being_deleted (True/False)}
        self._next_manage_call = None

    def setup(self):
        d = threads.deferToThread(self._open_db)
        d.addCallback(lambda _: self._manage())
        return d

    def stop(self):
        if self._next_manage_call is not None and self._next_manage_call.active():
            self._next_manage_call.cancel()
            self._next_manage_call = None
        self.db = None
        return defer.succeed(True)

    def get_blob(self, blob_hash, upload_allowed, length=None):
        """Return a blob identified by blob_hash, which may be a new blob or a blob that is already on the hard disk"""
        # TODO: if blob.upload_allowed and upload_allowed is False, change upload_allowed in blob and on disk
        if blob_hash in self.blobs:
            return defer.succeed(self.blobs[blob_hash])
        return self._make_new_blob(blob_hash, upload_allowed, length)

    def get_blob_creator(self):
        return self.blob_creator_type(self, self.blob_dir)

    def _make_new_blob(self, blob_hash, upload_allowed, length=None):
        blob = self.blob_type(self.blob_dir, blob_hash, upload_allowed, length)
        self.blobs[blob_hash] = blob
        d = threads.deferToThread(self._completed_blobs, [blob_hash])

        def check_completed(completed_blobs):

            def set_length(length):
                blob.length = length

            if len(completed_blobs) == 1 and completed_blobs[0] == blob_hash:
                blob.verified = True
                inner_d = threads.deferToThread(self._get_blob_length, blob_hash)
                inner_d.addCallback(set_length)
                inner_d.addCallback(lambda _: blob)
            else:
                inner_d = defer.succeed(blob)
            return inner_d

        d.addCallback(check_completed)
        return d

    def blob_completed(self, blob, next_announce_time=None):
        if next_announce_time is None:
            next_announce_time = time.time()
        return threads.deferToThread(self._add_completed_blob, blob.blob_hash, blob.length,
                                     time.time(), next_announce_time)

    def completed_blobs(self, blobs_to_check):
        return threads.deferToThread(self._completed_blobs, blobs_to_check)

    def hashes_to_announce(self):
        next_announce_time = time.time() + self.hash_reannounce_time
        return threads.deferToThread(self._get_blobs_to_announce, next_announce_time)

    def creator_finished(self, blob_creator):
        logging.debug("blob_creator.blob_hash: %s", blob_creator.blob_hash)
        assert blob_creator.blob_hash is not None
        assert blob_creator.blob_hash not in self.blobs
        assert blob_creator.length is not None
        new_blob = self.blob_type(self.blob_dir, blob_creator.blob_hash, True, blob_creator.length)
        new_blob.verified = True
        self.blobs[blob_creator.blob_hash] = new_blob
        if self.hash_announcer is not None:
            self.hash_announcer.immediate_announce([blob_creator.blob_hash])
            next_announce_time = time.time() + self.hash_reannounce_time
            d = self.blob_completed(new_blob, next_announce_time)
        else:
            d = self.blob_completed(new_blob)
        return d

    def delete_blobs(self, blob_hashes):
        for blob_hash in blob_hashes:
            if not blob_hash in self.blob_hashes_to_delete:
                self.blob_hashes_to_delete[blob_hash] = False

    def update_all_last_verified_dates(self, timestamp):
        return threads.deferToThread(self._update_all_last_verified_dates, timestamp)

    def immediate_announce_all_blobs(self):
        d = threads.deferToThread(self._get_all_verified_blob_hashes)
        d.addCallback(self.hash_announcer.immediate_announce)
        return d

    def get_blob_length(self, blob_hash):
        return threads.deferToThread(self._get_blob_length, blob_hash)

    def check_consistency(self):
        return threads.deferToThread(self._check_consistency)

    def _manage(self):
        from twisted.internet import reactor

        d = self._delete_blobs_marked_for_deletion()

        def set_next_manage_call():
            self._next_manage_call = reactor.callLater(1, self._manage)

        d.addCallback(lambda _: set_next_manage_call())

    def _delete_blobs_marked_for_deletion(self):

        def remove_from_list(b_h):
            del self.blob_hashes_to_delete[b_h]
            return b_h

        def set_not_deleting(err, b_h):
            logging.warning("Failed to delete blob %s. Reason: %s", str(b_h), err.getErrorMessage())
            self.blob_hashes_to_delete[b_h] = False
            return err

        def delete_from_db(result):
            b_hs = [r[1] for r in result if r[0] is True]
            if b_hs:
                d = threads.deferToThread(self._delete_blobs_from_db, b_hs)
            else:
                d = defer.succeed(True)

            def log_error(err):
                logging.warning("Failed to delete completed blobs from the db: %s", err.getErrorMessage())

            d.addErrback(log_error)
            return d

        def delete(blob, b_h):
            d = blob.delete()
            d.addCallbacks(lambda _: remove_from_list(b_h), set_not_deleting, errbackArgs=(b_h,))
            return d

        ds = []
        for blob_hash, being_deleted in self.blob_hashes_to_delete.items():
            if being_deleted is False:
                self.blob_hashes_to_delete[blob_hash] = True
                d = self.get_blob(blob_hash, True)
                d.addCallbacks(delete, set_not_deleting, callbackArgs=(blob_hash,), errbackArgs=(blob_hash,))
                ds.append(d)
        dl = defer.DeferredList(ds, consumeErrors=True)
        dl.addCallback(delete_from_db)
        return defer.DeferredList(ds)

    ######### database calls #########

    def _open_db(self):
        self.db = leveldb.LevelDB(os.path.join(self.db_dir, "blobs.db"))

    def _add_completed_blob(self, blob_hash, length, timestamp, next_announce_time=None):
        logging.debug("Adding a completed blob. blob_hash=%s, length=%s", blob_hash, str(length))
        if next_announce_time is None:
            next_announce_time = timestamp
        self.db.Put(blob_hash, json.dumps((length, timestamp, next_announce_time)), sync=True)

    def _completed_blobs(self, blobs_to_check):
        blobs = []
        for b in blobs_to_check:
            if is_valid_blobhash(b):
                try:
                    length, verified_time, next_announce_time = json.loads(self.db.Get(b))
                except KeyError:
                    continue
                file_path = os.path.join(self.blob_dir, b)
                if os.path.isfile(file_path):
                    if verified_time > os.path.getctime(file_path):
                        blobs.append(b)
        return blobs

    def _get_blob_length(self, blob):
        length, verified_time, next_announce_time = json.loads(self.db.Get(blob))
        return length

    def _update_blob_verified_timestamp(self, blob, timestamp):
        length, old_verified_time, next_announce_time = json.loads(self.db.Get(blob))
        self.db.Put(blob, json.dumps((length, timestamp, next_announce_time)), sync=True)

    def _get_blobs_to_announce(self, next_announce_time):
        # TODO: See if the following would be better for handling announce times:
        # TODO:    Have a separate db for them, and read the whole thing into memory
        # TODO:    on startup, and then write changes to db when they happen
        blobs = []
        batch = leveldb.WriteBatch()
        current_time = time.time()
        for blob_hash, blob_info in self.db.RangeIter():
            length, verified_time, announce_time = json.loads(blob_info)
            if announce_time < current_time:
                batch.Put(blob_hash, json.dumps((length, verified_time, next_announce_time)))
                blobs.append(blob_hash)
        self.db.Write(batch, sync=True)
        return blobs

    def _update_all_last_verified_dates(self, timestamp):
        batch = leveldb.WriteBatch()
        for blob_hash, blob_info in self.db.RangeIter():
            length, verified_time, announce_time = json.loads(blob_info)
            batch.Put(blob_hash, json.dumps((length, timestamp, announce_time)))
        self.db.Write(batch, sync=True)

    def _delete_blobs_from_db(self, blob_hashes):
        batch = leveldb.WriteBatch()
        for blob_hash in blob_hashes:
            batch.Delete(blob_hash)
        self.db.Write(batch, sync=True)

    def _check_consistency(self):
        batch = leveldb.WriteBatch()
        current_time = time.time()
        for blob_hash, blob_info in self.db.RangeIter():
            length, verified_time, announce_time = json.loads(blob_info)
            file_path = os.path.join(self.blob_dir, blob_hash)
            if os.path.isfile(file_path):
                if verified_time < os.path.getctime(file_path):
                    h = get_lbry_hash_obj()
                    len_so_far = 0
                    f = open(file_path)
                    while True:
                        data = f.read(2**12)
                        if not data:
                            break
                        h.update(data)
                        len_so_far += len(data)
                    if len_so_far == length and h.hexdigest() == blob_hash:
                        batch.Put(blob_hash, json.dumps((length, current_time, announce_time)))
        self.db.Write(batch, sync=True)

    def _get_all_verified_blob_hashes(self):
        blob_hashes = []
        for blob_hash, blob_info in self.db.RangeIter():
            length, verified_time, announce_time = json.loads(blob_info)
            file_path = os.path.join(self.blob_dir, blob_hash)
            if os.path.isfile(file_path):
                if verified_time > os.path.getctime(file_path):
                    blob_hashes.append(blob_hash)
        return blob_hashes


class TempBlobManager(BlobManager):
    """This class stores blobs in memory"""
    def __init__(self, hash_announcer):
        BlobManager.__init__(self, hash_announcer)
        self.blob_type = TempBlob
        self.blob_creator_type = TempBlobCreator
        self.blobs = {}
        self.blob_next_announces = {}
        self.blob_hashes_to_delete = {}  # {blob_hash: being_deleted (True/False)}
        self._next_manage_call = None

    def setup(self):
        self._manage()
        return defer.succeed(True)

    def stop(self):
        if self._next_manage_call is not None and self._next_manage_call.active():
            self._next_manage_call.cancel()
            self._next_manage_call = None

    def get_blob(self, blob_hash, upload_allowed, length=None):
        if blob_hash in self.blobs:
            return defer.succeed(self.blobs[blob_hash])
        return self._make_new_blob(blob_hash, upload_allowed, length)

    def get_blob_creator(self):
        return self.blob_creator_type(self)

    def _make_new_blob(self, blob_hash, upload_allowed, length=None):
        blob = self.blob_type(blob_hash, upload_allowed, length)
        self.blobs[blob_hash] = blob
        return defer.succeed(blob)

    def blob_completed(self, blob, next_announce_time=None):
        if next_announce_time is None:
            next_announce_time = time.time()
        self.blob_next_announces[blob.blob_hash] = next_announce_time
        return defer.succeed(True)

    def completed_blobs(self, blobs_to_check):
        blobs = [b.blob_hash for b in self.blobs.itervalues() if b.blob_hash in blobs_to_check and b.is_validated()]
        return defer.succeed(blobs)

    def hashes_to_announce(self):
        now = time.time()
        blobs = [blob_hash for blob_hash, announce_time in self.blob_next_announces.iteritems() if announce_time < now]
        next_announce_time = now + self.hash_reannounce_time
        for b in blobs:
            self.blob_next_announces[b] = next_announce_time
        return defer.succeed(blobs)

    def creator_finished(self, blob_creator):
        assert blob_creator.blob_hash is not None
        assert blob_creator.blob_hash not in self.blobs
        assert blob_creator.length is not None
        new_blob = self.blob_type(blob_creator.blob_hash, True, blob_creator.length)
        new_blob.verified = True
        new_blob.data_buffer = blob_creator.data_buffer
        new_blob.length = blob_creator.length
        self.blobs[blob_creator.blob_hash] = new_blob
        if self.hash_announcer is not None:
            self.hash_announcer.immediate_announce([blob_creator.blob_hash])
            next_announce_time = time.time() + self.hash_reannounce_time
            d = self.blob_completed(new_blob, next_announce_time)
        else:
            d = self.blob_completed(new_blob)
        d.addCallback(lambda _: new_blob)
        return d

    def delete_blobs(self, blob_hashes):
        for blob_hash in blob_hashes:
            if not blob_hash in self.blob_hashes_to_delete:
                self.blob_hashes_to_delete[blob_hash] = False

    def get_blob_length(self, blob_hash):
        if blob_hash in self.blobs:
            if self.blobs[blob_hash].length is not None:
                return defer.succeed(self.blobs[blob_hash].length)
        return defer.fail(ValueError("No such blob hash is known"))

    def immediate_announce_all_blobs(self):
        return self.hash_announcer.immediate_announce(self.blobs.iterkeys())

    def _manage(self):
        from twisted.internet import reactor

        d = self._delete_blobs_marked_for_deletion()

        def set_next_manage_call():
            logging.info("Setting the next manage call in %s", str(self))
            self._next_manage_call = reactor.callLater(1, self._manage)

        d.addCallback(lambda _: set_next_manage_call())

    def _delete_blobs_marked_for_deletion(self):

        def remove_from_list(b_h):
            del self.blob_hashes_to_delete[b_h]
            logging.info("Deleted blob %s", blob_hash)
            return b_h

        def set_not_deleting(err, b_h):
            logging.warning("Failed to delete blob %s. Reason: %s", str(b_h), err.getErrorMessage())
            self.blob_hashes_to_delete[b_h] = False
            return b_h

        ds = []
        for blob_hash, being_deleted in self.blob_hashes_to_delete.items():
            if being_deleted is False:
                if blob_hash in self.blobs:
                    self.blob_hashes_to_delete[blob_hash] = True
                    logging.info("Found a blob marked for deletion: %s", blob_hash)
                    blob = self.blobs[blob_hash]
                    d = blob.delete()

                    d.addCallbacks(lambda _: remove_from_list(blob_hash), set_not_deleting,
                                   errbackArgs=(blob_hash,))

                    ds.append(d)
                else:
                    remove_from_list(blob_hash)
                    d = defer.fail(Failure(ValueError("No such blob known")))
                    logging.warning("Blob %s cannot be deleted because it is unknown")
                    ds.append(d)
        return defer.DeferredList(ds)