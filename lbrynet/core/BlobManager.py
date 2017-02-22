import logging
import os
import time
import sqlite3

from twisted.internet import defer
from zope.interface import implements
from lbrynet.interfaces import IBlobManager
from lbrynet.core.HashBlob import BlobFile, TempBlob, BlobFileCreator, TempBlobCreator
from lbrynet.core.server.DHTHashAnnouncer import DHTHashSupplier
from lbrynet.core.Error import NoSuchBlobError
from lbrynet.core.sqlite_helpers import rerun_if_locked

log = logging.getLogger(__name__)


class TempBlobManager(DHTHashSupplier):
    implements(IBlobManager)

    def __init__(self, hash_announcer):
        DHTHashSupplier.__init__(self, hash_announcer)
        self.blob_type = TempBlob
        self.blob_creator_type = TempBlobCreator
        self.blobs = {}
        self.blob_next_announces = {}
        self.blob_hashes_to_delete = {}  # {blob_hash: being_deleted (True/False)}
        self._next_manage_call = None

    @defer.inlineCallbacks
    def setup(self):
        yield self._setup()
        yield self._manage()

    def stop(self):
        if self._next_manage_call is not None and self._next_manage_call.active():
            self._next_manage_call.cancel()
            self._next_manage_call = None
        return self._stop()

    def get_blob(self, blob_hash, length=None):
        assert length is None or isinstance(length, int)
        blob = self.blobs.get(blob_hash, False)
        if blob:
            return defer.succeed(blob)
        creator = self.get_blob_creator()
        self._make_new_blob(creator, blob_hash, length)
        return defer.succeed(self.blobs[blob_hash])

    def get_blob_creator(self):
        return self._get_blob_creator()

    @defer.inlineCallbacks
    def blob_completed(self, blob, next_announce_time=None):
        log.info("Blob %s completed", blob)
        if next_announce_time is None:
            next_announce_time = self.get_next_announce_time()
        yield self._add_completed_blob(blob.blob_hash, blob.length, next_announce_time)
        self.blobs[blob.blob_hash]._verified = True
        defer.returnValue(True)

    @defer.inlineCallbacks
    def completed_blobs(self, blob_hashes_to_check):
        blobs = yield defer.DeferredList([self.get_blob(b) for b in blob_hashes_to_check])
        blob_hashes = [b.blob_hash for success, b in blobs if success and b.verified]
        defer.returnValue(blob_hashes)

    @defer.inlineCallbacks
    def hashes_to_announce(self):
        hashes_to_announce = yield self._get_blobs_to_announce()
        defer.returnValue(hashes_to_announce)

    @defer.inlineCallbacks
    def creator_finished(self, blob_creator):
        log.info("%s finished", blob_creator)
        assert blob_creator.blob_hash is not None
        assert blob_creator.blob_hash not in self.blobs
        assert blob_creator.length is not None
        self._make_new_blob(blob_creator, blob_creator.blob_hash,
                                          blob_creator.length)
        self._immediate_announce([blob_creator.blob_hash])
        next_announce_time = self.get_next_announce_time()
        yield self.blob_completed(self.blobs[blob_creator.blob_hash], next_announce_time)
        defer.returnValue(None)

    @defer.inlineCallbacks
    def delete_blob(self, blob_hash):
        if not blob_hash in self.blob_hashes_to_delete:
            self.blob_hashes_to_delete[blob_hash] = False

    @defer.inlineCallbacks
    def delete_blobs(self, blob_hashes):
        dl = [self.delete_blob(blob_hash for blob_hash in blob_hashes)]
        yield defer.DeferredList(dl)

    @defer.inlineCallbacks
    def get_all_verified_blobs(self):
        blob_hashes = yield self._get_all_verified_blob_hashes()
        yield self.completed_blobs(blob_hashes)

    @defer.inlineCallbacks
    def add_blob_to_download_history(self, blob_hash, host, rate):
        yield self._add_blob_to_download_history(blob_hash, host, rate)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def add_blob_to_upload_history(self, blob_hash, host, rate):
        yield self._add_blob_to_upload_history(blob_hash, host, rate)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def immediate_announce_all_blobs(self):
        verified_hashes = yield self._get_all_verified_blob_hashes()
        yield self._immediate_announce(verified_hashes)

    # # # # # # # # # # # #
    # Internal functions  #
    # # # # # # # # # # # #

    @defer.inlineCallbacks
    def _manage(self):
        from twisted.internet import reactor
        yield self._delete_blobs_marked_for_deletion()
        log.debug("Setting the next manage call in %s", str(self))
        self._next_manage_call = reactor.callLater(1, self._manage)
        defer.returnValue(None)

    @defer.inlineCallbacks
    def _immediate_announce(self, blob_hashes):
        if self.hash_announcer:
            yield self.hash_announcer.immediate_announce(blob_hashes)
        defer.returnValue(None)

    @defer.inlineCallbacks
    def _delete_blob(self, blob_hash):
        if blob_hash in self.blobs:
            self.blob_hashes_to_delete[blob_hash] = True
            log.debug("Found a blob marked for deletion: %s", blob_hash)
            blob = self.blobs[blob_hash]
        else:
            log.warning("Blob %s cannot be deleted because it is unknown", blob_hash)
            raise NoSuchBlobError(blob_hash)
        try:
            yield blob.delete()
            del self.blob_hashes_to_delete[blob_hash]
            yield self._delete_blob_from_storage(blob_hash)
            log.info("Deleted blob %s", blob_hash)
        except Exception as err:
            log.warning("Failed to delete blob %s. Reason: %s",
                        str(blob_hash), str(type(err)))
            self.blob_hashes_to_delete[blob_hash] = False

    @defer.inlineCallbacks
    def _delete_blobs_marked_for_deletion(self):
        dl = []
        for blob_hash, being_deleted in self.blob_hashes_to_delete.items():
            if being_deleted is False:
                dl.append(self._delete_blob(blob_hash))
        yield defer.DeferredList(dl, consumeErrors=True)

    def _make_new_blob(self, creator, blob_hash, length=None):
        log.info("Make new blob: %s %s", blob_hash, length)
        assert blob_hash not in self.blobs
        blob = self._new_blob(creator, blob_hash, length)
        self.blobs[blob_hash] = blob

    # # # # # # # # # # # # # # # # # #
    # Overridden functions start here #
    # # # # # # # # # # # # # # # # # #

    def _setup(self):
        return defer.succeed(None)

    def _stop(self):
        return defer.succeed(None)

    # TODO: change this; its breaks the encapsulation of the
    #       blob. Maybe better would be to have the blob_creator
    #       produce a blob.

    def _new_blob(self, creator, blob_hash, length=None):
        new_blob = self.blob_type(blob_hash, length)
        new_blob.data_buffer = creator.data_buffer
        return new_blob

    def _get_blob_creator(self):
        return self.blob_creator_type(self)

    def _add_completed_blob(self, blob_hash, length, next_announce_time=None):
        if next_announce_time is None:
            next_announce_time = time.time()
        self.blob_next_announces[blob_hash] = next_announce_time
        return defer.succeed(None)

    def _get_blobs_to_announce(self):
        now = time.time()
        blobs = [
            blob_hash for blob_hash, announce_time in self.blob_next_announces.iteritems()
            if announce_time < now
            ]
        next_announce_time = self.get_next_announce_time(len(blobs))
        for b in blobs:
            self.blob_next_announces[b] = next_announce_time
        return defer.succeed(blobs)

    def _delete_blob_from_storage(self, blob_hash):
        assert blob_hash in self.blobs, NoSuchBlobError(blob_hash)
        del self.blobs[blob_hash]
        return defer.succeed(None)

    @defer.inlineCallbacks
    def _get_all_verified_blob_hashes(self):
        blobs = yield self.completed_blobs(self.blobs)
        blob_hashes = [blob.blob_hash for blob in blobs]
        defer.returnValue(blob_hashes)

    def _add_blob_to_download_history(self, blob_hash, host, rate):
        return defer.succeed(None)

    def _add_blob_to_upload_history(self, blob_hash, host, rate):
        return defer.succeed(None)


class DiskBlobManager(TempBlobManager):
    """This class stores blobs on the hard disk"""
    def __init__(self, hash_announcer, blob_dir, storage):
        TempBlobManager.__init__(self, hash_announcer)
        self.blob_dir = blob_dir
        self.storage = storage
        self.blob_type = BlobFile
        self.blob_creator_type = BlobFileCreator

    def _get_blob_creator(self):
        return self.blob_creator_type(self, self.blob_dir)

    def _new_blob(self, creator, blob_hash, length=None):
        new_blob = self.blob_type(self.blob_dir, blob_hash, length)
        return new_blob

    @defer.inlineCallbacks
    def _stop(self):
        yield self.storage.close()

    @defer.inlineCallbacks
    def _setup(self):
        yield self.storage.open()

    @rerun_if_locked
    @defer.inlineCallbacks
    def _get_blob_id(self, blob_hash):
        get_id_query = "SELECT id FROM blobs WHERE blob_hash=?"
        add_blob_query = "INSERT INTO blobs VALUES (NULL, ?)"
        add_managed_blob_query = ("INSERT INTO managed_blobs VALUES "
                                  "(NULL, ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL)")
        result = yield self.storage.query(get_id_query, (blob_hash, ))
        if len(result):
            blob_id = result[0][0]
        else:
            try:
                yield self.storage.query(add_blob_query, (blob_hash,))
            except sqlite3.IntegrityError:
                raise
            result = yield self.storage.query(get_id_query, (blob_hash,))
            blob_id = result[0][0]
            try:
                yield self.storage.query(add_managed_blob_query, (blob_id,))
            except sqlite3.DatabaseError:
                raise
        defer.returnValue(blob_id)

    @rerun_if_locked
    @defer.inlineCallbacks
    def _add_completed_blob(self, blob_hash, length, next_announce_time):
        blob_id = yield self._get_blob_id(blob_hash)
        query = "UPDATE managed_blobs SET blob_length=?, next_announce_time=? WHERE blob_id=?"
        try:
            yield self.storage.query(query, (length, next_announce_time, blob_id))
        except sqlite3.IntegrityError:
            pass
        yield self._update_blob_verified_timestamp(blob_hash, time.time())
        defer.returnValue(None)

    @rerun_if_locked
    @defer.inlineCallbacks
    def _update_blob_verified_timestamp(self, blob_hash, timestamp):
        blob_id = yield self._get_blob_id(blob_hash)
        query = "UPDATE managed_blobs set last_verified_time=? where blob_id=?"
        yield self.storage.query(query, (timestamp, blob_id))

    @rerun_if_locked
    @defer.inlineCallbacks
    def _get_blobs_to_announce(self):
        timestamp = int(time.time())
        query = ("SELECT blob_hash FROM blobs "
                     "INNER JOIN managed_blobs mb "
                         "ON mb.blob_id=blobs.id AND "
                             "mb.next_announce_time<? AND "
                             "blobs.blob_hash IS NOT NULL")
        blob_hashes = yield self.storage.query(query, (timestamp, ))
        blob_hashes = [r[0] for r in blob_hashes]
        next_announce_time = self.get_next_announce_time(len(blob_hashes))
        update_query = ("UPDATE managed_blobs SET next_announce_time=? where next_announce_time<?")
        yield self.storage.query(update_query, (next_announce_time, timestamp))
        defer.returnValue(blob_hashes)

    @rerun_if_locked
    @defer.inlineCallbacks
    def _delete_blobs_from_db(self, blob_hashes):
        dl = []
        for blob_hash in blob_hashes:
            blob_id = self._get_blob_id(blob_hash)
            dl.append(self.storage.query("DELETE FROM blobs where blob_id=?", (blob_id,)))
        yield defer.DeferredList(dl)

    @rerun_if_locked
    def _get_all_verified_blob_hashes(self):
        blob_hashes = yield self.storage.query("SELECT blob_hash FROM blobs")
        verified_blobs = []
        for blob_hash, in blob_hashes:
            file_path = os.path.join(self.blob_dir, blob_hash)
            if os.path.isfile(file_path):
                verified_blobs.append(blob_hash)
            yield self._update_blob_verified_timestamp(blob_hash, time.time())
        defer.returnValue(verified_blobs)

    @rerun_if_locked
    @defer.inlineCallbacks
    def _add_blob_to_download_history(self, blob_hash, host, rate):
        ts = int(time.time())
        blob_id = yield self._get_blob_id(blob_hash)
        query = "INSERT INTO blob_transfer_history VALUES (NULL, ?, ?, ?, ?, ?) "
        yield self.storage.query(query, (blob_id, str(host), True, float(rate), ts))

    @rerun_if_locked
    @defer.inlineCallbacks
    def _add_blob_to_upload_history(self, blob_hash, host, rate):
        ts = int(time.time())
        blob_id = yield self._get_blob_id(blob_hash)
        query = "INSERT INTO blob_transfer_history VALUES (NULL, ?, ?, ?, ?, ?) "
        yield self.storage.query(query, (blob_id, str(host), False, float(rate), ts))
