import logging
import os
import time
import sqlite3

from twisted.internet import threads, defer
from twisted.python.failure import Failure
from twisted.enterprise import adbapi
from lbrynet.core.HashBlob import BlobFile, TempBlob, BlobFileCreator, TempBlobCreator
from lbrynet.core.server.DHTHashAnnouncer import DHTHashSupplier
from lbrynet.core.Error import NoSuchBlobError
from lbrynet.core.sqlite_helpers import rerun_if_locked


log = logging.getLogger(__name__)


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

    def completed_blobs(self, blobhashes_to_check):
        pass

    def hashes_to_announce(self):
        pass

    def creator_finished(self, blob_creator):
        pass

    def delete_blob(self, blob_hash):
        pass

    def blob_requested(self, blob_hash):
        pass

    def blob_downloaded(self, blob_hash):
        pass

    def blob_searched_on(self, blob_hash):
        pass

    def blob_paid_for(self, blob_hash, amount):
        pass

    def get_all_verified_blobs(self):
        pass

    def add_blob_to_download_history(self, blob_hash, host, rate):
        pass

    def add_blob_to_upload_history(self, blob_hash, host, rate):
        pass

    def _immediate_announce(self, blob_hashes):
        if self.hash_announcer:
            return self.hash_announcer.immediate_announce(blob_hashes)


# TODO: Having different managers for different blobs breaks the
#       abstraction of a HashBlob. Why should the management of blobs
#       care what kind of Blob it has?
class DiskBlobManager(BlobManager):
    """This class stores blobs on the hard disk"""
    def __init__(self, hash_announcer, blob_dir, db_dir):
        BlobManager.__init__(self, hash_announcer)
        self.blob_dir = blob_dir
        self.db_file = os.path.join(db_dir, "blobs.db")
        self.db_conn = None
        self.blob_type = BlobFile
        self.blob_creator_type = BlobFileCreator
        # TODO: consider using an LRU for blobs as there could potentially
        #       be thousands of blobs loaded up, many stale
        self.blobs = {}
        self.blob_hashes_to_delete = {} # {blob_hash: being_deleted (True/False)}
        self._next_manage_call = None

    def setup(self):
        log.info("Setting up the DiskBlobManager. blob_dir: %s, db_file: %s", str(self.blob_dir),
                 str(self.db_file))
        d = self._open_db()
        d.addCallback(lambda _: self._manage())
        return d

    def stop(self):
        log.info("Stopping the DiskBlobManager")
        if self._next_manage_call is not None and self._next_manage_call.active():
            self._next_manage_call.cancel()
            self._next_manage_call = None
        self.db_conn = None
        return defer.succeed(True)

    def get_blob(self, blob_hash, upload_allowed, length=None):
        """Return a blob identified by blob_hash, which may be a new blob or a
        blob that is already on the hard disk
        """
        # TODO: if blob.upload_allowed and upload_allowed is False,
        # change upload_allowed in blob and on disk
        if blob_hash in self.blobs:
            return defer.succeed(self.blobs[blob_hash])
        return self._make_new_blob(blob_hash, upload_allowed, length)

    def get_blob_creator(self):
        return self.blob_creator_type(self, self.blob_dir)

    def _make_new_blob(self, blob_hash, upload_allowed, length=None):
        log.debug('Making a new blob for %s', blob_hash)
        blob = self.blob_type(self.blob_dir, blob_hash, upload_allowed, length)
        self.blobs[blob_hash] = blob
        return defer.succeed(blob)

    def blob_completed(self, blob, next_announce_time=None):
        if next_announce_time is None:
            next_announce_time = time.time() + self.hash_reannounce_time
        d = self._add_completed_blob(blob.blob_hash, blob.length, next_announce_time)
        d.addCallback(lambda _: self._immediate_announce([blob.blob_hash]))
        return d

    def completed_blobs(self, blobhashes_to_check):
        return self._completed_blobs(blobhashes_to_check)

    def hashes_to_announce(self):
        next_announce_time = time.time() + self.hash_reannounce_time
        return self._get_blobs_to_announce(next_announce_time)

    def creator_finished(self, blob_creator):
        log.debug("blob_creator.blob_hash: %s", blob_creator.blob_hash)
        assert blob_creator.blob_hash is not None
        assert blob_creator.blob_hash not in self.blobs
        assert blob_creator.length is not None
        new_blob = self.blob_type(self.blob_dir, blob_creator.blob_hash, True, blob_creator.length)
        self.blobs[blob_creator.blob_hash] = new_blob
        self._immediate_announce([blob_creator.blob_hash])
        next_announce_time = time.time() + self.hash_reannounce_time
        d = self.blob_completed(new_blob, next_announce_time)
        return d

    def delete_blobs(self, blob_hashes):
        for blob_hash in blob_hashes:
            if not blob_hash in self.blob_hashes_to_delete:
                self.blob_hashes_to_delete[blob_hash] = False

    def immediate_announce_all_blobs(self):
        d = self._get_all_verified_blob_hashes()
        d.addCallback(self._immediate_announce)
        return d

    def get_all_verified_blobs(self):
        d = self._get_all_verified_blob_hashes()
        d.addCallback(self.completed_blobs)
        return d

    def add_blob_to_download_history(self, blob_hash, host, rate):
        d = self._add_blob_to_download_history(blob_hash, host, rate)
        return d

    def add_blob_to_upload_history(self, blob_hash, host, rate):
        d = self._add_blob_to_upload_history(blob_hash, host, rate)
        return d

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
            log.warning("Failed to delete blob %s. Reason: %s", str(b_h), err.getErrorMessage())
            self.blob_hashes_to_delete[b_h] = False
            return err

        def delete_from_db(result):
            b_hs = [r[1] for r in result if r[0] is True]
            if b_hs:
                d = self._delete_blobs_from_db(b_hs)
            else:
                d = defer.succeed(True)

            def log_error(err):
                log.warning(
                    "Failed to delete completed blobs from the db: %s", err.getErrorMessage())

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
                d = self.get_blob(blob_hash)
                d.addCallbacks(
                    delete, set_not_deleting,
                    callbackArgs=(blob_hash,), errbackArgs=(blob_hash,))
                ds.append(d)
        dl = defer.DeferredList(ds, consumeErrors=True)
        dl.addCallback(delete_from_db)
        return defer.DeferredList(ds)

    ######### database calls #########

    def _open_db(self):
        # check_same_thread=False is solely to quiet a spurious error that appears to be due
        # to a bug in twisted, where the connection is closed by a different thread than the
        # one that opened it. The individual connections in the pool are not used in multiple
        # threads.
        self.db_conn = adbapi.ConnectionPool('sqlite3', self.db_file, check_same_thread=False)

        def create_tables(transaction):
            transaction.execute("create table if not exists blobs (" +
                                "    blob_hash text primary key, " +
                                "    blob_length integer, " +
                                "    last_verified_time real, " +
                                "    next_announce_time real)")

            transaction.execute("create table if not exists download (" +
                                "    id integer primary key autoincrement, " +
                                "    blob text, " +
                                "    host text, " +
                                "    rate float, " +
                                "    ts integer)")

            transaction.execute("create table if not exists upload (" +
                                "    id integer primary key autoincrement, " +
                                "    blob text, " +
                                "    host text, " +
                                "    rate float, " +
                                "    ts integer)")

        return self.db_conn.runInteraction(create_tables)

    @rerun_if_locked
    def _add_completed_blob(self, blob_hash, length, next_announce_time):
        log.debug("Adding a completed blob. blob_hash=%s, length=%s", blob_hash, str(length))
        d = self.db_conn.runQuery(
            "insert into blobs (blob_hash, blob_length, next_announce_time) values (?, ?, ?)",
            (blob_hash, length, next_announce_time)
        )
        d.addErrback(lambda err: err.trap(sqlite3.IntegrityError))
        return d

    @defer.inlineCallbacks
    def _completed_blobs(self, blobhashes_to_check):
        """Returns of the blobhashes_to_check, which are valid"""
        blobs = yield defer.DeferredList([self.get_blob(b, True) for b in blobhashes_to_check])
        blob_hashes = [b.blob_hash for success, b in blobs if success and b.verified]
        defer.returnValue(blob_hashes)

    @rerun_if_locked
    def _update_blob_verified_timestamp(self, blob, timestamp):
        return self.db_conn.runQuery("update blobs set last_verified_time = ? where blob_hash = ?",
                                     (blob, timestamp))

    @rerun_if_locked
    def _get_blobs_to_announce(self, next_announce_time):

        def get_and_update(transaction):
            timestamp = time.time()
            r = transaction.execute("select blob_hash from blobs " +
                                    "where next_announce_time < ? and blob_hash is not null",
                                    (timestamp,))
            blobs = [b for b, in r.fetchall()]
            transaction.execute(
                "update blobs set next_announce_time = ? where next_announce_time < ?",
                (next_announce_time, timestamp))
            return blobs

        return self.db_conn.runInteraction(get_and_update)

    @rerun_if_locked
    def _delete_blobs_from_db(self, blob_hashes):

        def delete_blobs(transaction):
            for b in blob_hashes:
                transaction.execute("delete from blobs where blob_hash = ?", (b,))

        return self.db_conn.runInteraction(delete_blobs)

    @rerun_if_locked
    def _get_all_verified_blob_hashes(self):
        d = self.db_conn.runQuery("select blob_hash from blobs")

        def get_verified_blobs(blobs):
            verified_blobs = []
            for blob_hash, in blobs:
                file_path = os.path.join(self.blob_dir, blob_hash)
                if os.path.isfile(file_path):
                    verified_blobs.append(blob_hash)
            return verified_blobs

        d.addCallback(lambda blobs: threads.deferToThread(get_verified_blobs, blobs))
        return d

    @rerun_if_locked
    def _add_blob_to_download_history(self, blob_hash, host, rate):
        ts = int(time.time())
        d = self.db_conn.runQuery(
            "insert into download values (null, ?, ?, ?, ?) ",
            (blob_hash, str(host), float(rate), ts))
        return d

    @rerun_if_locked
    def _add_blob_to_upload_history(self, blob_hash, host, rate):
        ts = int(time.time())
        d = self.db_conn.runQuery(
            "insert into upload values (null, ?, ?, ?, ?) ",
            (blob_hash, str(host), float(rate), ts))
        return d


# TODO: Having different managers for different blobs breaks the
#       abstraction of a HashBlob. Why should the management of blobs
#       care what kind of Blob it has?
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

    def completed_blobs(self, blobhashes_to_check):
        blobs = [
            b.blob_hash for b in self.blobs.itervalues()
            if b.blob_hash in blobhashes_to_check and b.is_validated()
        ]
        return defer.succeed(blobs)

    def get_all_verified_blobs(self):
        d = self.completed_blobs(self.blobs)
        return d

    def hashes_to_announce(self):
        now = time.time()
        blobs = [
            blob_hash for blob_hash, announce_time in self.blob_next_announces.iteritems()
            if announce_time < now
        ]
        next_announce_time = now + self.hash_reannounce_time
        for b in blobs:
            self.blob_next_announces[b] = next_announce_time
        return defer.succeed(blobs)

    def creator_finished(self, blob_creator):
        assert blob_creator.blob_hash is not None
        assert blob_creator.blob_hash not in self.blobs
        assert blob_creator.length is not None
        new_blob = self.blob_type(blob_creator.blob_hash, True, blob_creator.length)
        # TODO: change this; its breaks the encapsulation of the
        #       blob. Maybe better would be to have the blob_creator
        #       produce a blob.
        new_blob.data_buffer = blob_creator.data_buffer
        new_blob._verified = True
        self.blobs[blob_creator.blob_hash] = new_blob
        self._immediate_announce([blob_creator.blob_hash])
        next_announce_time = time.time() + self.hash_reannounce_time
        d = self.blob_completed(new_blob, next_announce_time)
        d.addCallback(lambda _: new_blob)
        return d

    def delete_blobs(self, blob_hashes):
        for blob_hash in blob_hashes:
            if not blob_hash in self.blob_hashes_to_delete:
                self.blob_hashes_to_delete[blob_hash] = False

    def immediate_announce_all_blobs(self):
        if self.hash_announcer:
            return self.hash_announcer.immediate_announce(self.blobs.iterkeys())

    def _manage(self):
        from twisted.internet import reactor

        d = self._delete_blobs_marked_for_deletion()

        def set_next_manage_call():
            log.info("Setting the next manage call in %s", str(self))
            self._next_manage_call = reactor.callLater(1, self._manage)

        d.addCallback(lambda _: set_next_manage_call())

    def _delete_blobs_marked_for_deletion(self):
        def remove_from_list(b_h):
            del self.blob_hashes_to_delete[b_h]
            log.info("Deleted blob %s", blob_hash)
            return b_h

        def set_not_deleting(err, b_h):
            log.warning("Failed to delete blob %s. Reason: %s", str(b_h), err.getErrorMessage())
            self.blob_hashes_to_delete[b_h] = False
            return b_h

        ds = []
        for blob_hash, being_deleted in self.blob_hashes_to_delete.items():
            if being_deleted is False:
                if blob_hash in self.blobs:
                    self.blob_hashes_to_delete[blob_hash] = True
                    log.info("Found a blob marked for deletion: %s", blob_hash)
                    blob = self.blobs[blob_hash]
                    d = blob.delete()

                    d.addCallbacks(lambda _: remove_from_list(blob_hash), set_not_deleting,
                                   errbackArgs=(blob_hash,))

                    ds.append(d)
                else:
                    remove_from_list(blob_hash)
                    d = defer.fail(Failure(NoSuchBlobError(blob_hash)))
                    log.warning("Blob %s cannot be deleted because it is unknown")
                    ds.append(d)
        return defer.DeferredList(ds)
