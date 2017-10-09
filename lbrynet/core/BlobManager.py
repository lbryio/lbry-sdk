import logging
import os
import time
import sqlite3

from twisted.internet import threads, defer, reactor
from twisted.enterprise import adbapi
from lbrynet import conf
from lbrynet.blob.blob_file import BlobFile
from lbrynet.blob.creator import BlobFileCreator
from lbrynet.core.server.DHTHashAnnouncer import DHTHashSupplier
from lbrynet.core.sqlite_helpers import rerun_if_locked

log = logging.getLogger(__name__)


class DiskBlobManager(DHTHashSupplier):
    def __init__(self, hash_announcer, blob_dir, db_dir):

        """
        This class stores blobs on the hard disk,
        blob_dir - directory where blobs are stored
        db_dir - directory where sqlite database of blob information is stored
        """

        DHTHashSupplier.__init__(self, hash_announcer)

        self.announce_head_blobs_only = conf.settings['announce_head_blobs_only']

        self.blob_dir = blob_dir
        self.db_file = os.path.join(db_dir, "blobs.db")
        self.db_conn = adbapi.ConnectionPool('sqlite3', self.db_file, check_same_thread=False)
        self.blob_creator_type = BlobFileCreator
        # TODO: consider using an LRU for blobs as there could potentially
        #       be thousands of blobs loaded up, many stale
        self.blobs = {}
        self.blob_hashes_to_delete = {} # {blob_hash: being_deleted (True/False)}

    @defer.inlineCallbacks
    def setup(self):
        log.info("Starting disk blob manager. blob_dir: %s, db_file: %s", str(self.blob_dir),
                 str(self.db_file))
        yield self._open_db()

    def stop(self):
        log.info("Stopping disk blob manager.")
        self.db_conn.close()
        return defer.succeed(True)

    def get_blob(self, blob_hash, length=None):
        """Return a blob identified by blob_hash, which may be a new blob or a
        blob that is already on the hard disk
        """
        if length is not None and not isinstance(length, int):
            raise Exception("invalid length type: %s (%s)", length, str(type(length)))
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

    def _immediate_announce(self, blob_hashes):
        if self.hash_announcer:
            return self.hash_announcer.immediate_announce(blob_hashes)
        raise Exception("Hash announcer not set")

    @defer.inlineCallbacks
    def blob_completed(self, blob, next_announce_time=None, should_announce=True):
        if next_announce_time is None:
            next_announce_time = self.get_next_announce_time()
        yield self._add_completed_blob(blob.blob_hash, blob.length,
                                       next_announce_time, should_announce)
        # we announce all blobs immediately, if announce_head_blob_only is False
        # otherwise, announce only if marked as should_announce
        if not self.announce_head_blobs_only or should_announce:
            reactor.callLater(0, self._immediate_announce, [blob.blob_hash])

    def completed_blobs(self, blobhashes_to_check):
        return self._completed_blobs(blobhashes_to_check)

    def hashes_to_announce(self):
        return self._get_blobs_to_announce()

    def count_should_announce_blobs(self):
        return self._count_should_announce_blobs()

    def set_should_announce(self, blob_hash, should_announce):
        if blob_hash in self.blobs:
            blob = self.blobs[blob_hash]
            if blob.get_is_verified():
                return self._set_should_announce(blob_hash,
                                                 self.get_next_announce_time(),
                                                 should_announce)
        return defer.succeed(False)

    def get_should_announce(self, blob_hash):
        return self._should_announce(blob_hash)

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
        next_announce_time = self.get_next_announce_time()
        d = self.blob_completed(new_blob, next_announce_time, should_announce)
        return d

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

    @defer.inlineCallbacks
    def get_host_downloaded_from(self, blob_hash):
        query_str = "SELECT host FROM download WHERE blob=? ORDER BY ts DESC LIMIT 1"
        host = yield self.db_conn.runQuery(query_str, (blob_hash,))
        if host:
            result = host[0][0]
        else:
            result = None
        defer.returnValue(result)

    def add_blob_to_upload_history(self, blob_hash, host, rate):
        d = self._add_blob_to_upload_history(blob_hash, host, rate)
        return d

    @defer.inlineCallbacks
    def delete_blobs(self, blob_hashes):
        bh_to_delete_from_db = []
        for blob_hash in blob_hashes:
            try:
                blob = yield self.get_blob(blob_hash)
                yield blob.delete()
                bh_to_delete_from_db.append(blob_hash)
            except Exception as e:
                log.warning("Failed to delete blob file. Reason: %s", e)
        yield self._delete_blobs_from_db(bh_to_delete_from_db)

    ######### database calls #########

    def _open_db(self):
        # check_same_thread=False is solely to quiet a spurious error that appears to be due
        # to a bug in twisted, where the connection is closed by a different thread than the
        # one that opened it. The individual connections in the pool are not used in multiple
        # threads.

        def create_tables(transaction):
            transaction.execute('PRAGMA journal_mode=WAL')
            transaction.execute("create table if not exists blobs (" +
                                "    blob_hash text primary key, " +
                                "    blob_length integer, " +
                                "    last_verified_time real, " +
                                "    next_announce_time real, " +
                                "    should_announce integer)")


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
    def _add_completed_blob(self, blob_hash, length, next_announce_time, should_announce):
        log.debug("Adding a completed blob. blob_hash=%s, length=%s", blob_hash, str(length))
        should_announce = 1 if should_announce else 0
        d = self.db_conn.runQuery("insert into blobs (blob_hash, blob_length, next_announce_time, "
                                  "should_announce) values (?, ?, ?, ?)", (blob_hash, length,
                                                                           next_announce_time,
                                                                           should_announce))
        # TODO: why is this here?
        d.addErrback(lambda err: err.trap(sqlite3.IntegrityError))
        return d

    @rerun_if_locked
    @defer.inlineCallbacks
    def _set_should_announce(self, blob_hash, next_announce_time, should_announce):
        yield self.db_conn.runOperation("update blobs set next_announce_time=?, should_announce=? "
                                        "where blob_hash=?", (next_announce_time, should_announce,
                                                              blob_hash))
        defer.returnValue(True)

    @rerun_if_locked
    @defer.inlineCallbacks
    def _should_announce(self, blob_hash):
        result = yield self.db_conn.runQuery("select should_announce from blobs where blob_hash=?",
                                             (blob_hash,))
        defer.returnValue(result[0][0])

    @rerun_if_locked
    @defer.inlineCallbacks
    def _count_should_announce_blobs(self):
        result = yield self.db_conn.runQuery("select count(*) from blobs where should_announce=1")
        defer.returnValue(result[0][0])

    @defer.inlineCallbacks
    def _completed_blobs(self, blobhashes_to_check):
        """Returns of the blobhashes_to_check, which are valid"""
        blobs = yield defer.DeferredList([self.get_blob(b) for b in blobhashes_to_check])
        blob_hashes = [b.blob_hash for success, b in blobs if success and b.verified]
        defer.returnValue(blob_hashes)

    @rerun_if_locked
    def _update_blob_verified_timestamp(self, blob, timestamp):
        return self.db_conn.runQuery("update blobs set last_verified_time = ? where blob_hash = ?",
                                     (blob, timestamp))

    @rerun_if_locked
    def _get_blobs_to_announce(self):
        def get_and_update(transaction):
            timestamp = time.time()
            if self.announce_head_blobs_only is True:
                r = transaction.execute("select blob_hash from blobs " +
                                    "where next_announce_time < ? and blob_hash is not null "+
                                    "and should_announce = 1",
                                    (timestamp,))
            else:
                r = transaction.execute("select blob_hash from blobs " +
                                    "where next_announce_time < ? and blob_hash is not null",
                                    (timestamp,))

            blobs = [b for b, in r.fetchall()]
            next_announce_time = self.get_next_announce_time(len(blobs))
            transaction.execute(
                "update blobs set next_announce_time = ? where next_announce_time < ?",
                (next_announce_time, timestamp))
            log.debug("Got %s blobs to announce, next announce time is in %s seconds",
                        len(blobs), next_announce_time-time.time())
            return blobs

        return self.db_conn.runInteraction(get_and_update)

    @rerun_if_locked
    def _delete_blobs_from_db(self, blob_hashes):

        def delete_blobs(transaction):
            for b in blob_hashes:
                transaction.execute("delete from blobs where blob_hash = ?", (b,))

        return self.db_conn.runInteraction(delete_blobs)

    @rerun_if_locked
    def _get_all_blob_hashes(self):
        d = self.db_conn.runQuery("select blob_hash from blobs")
        return d

    @rerun_if_locked
    @defer.inlineCallbacks
    def _get_all_should_announce_blob_hashes(self):
        # return a list of blob hashes where should_announce is True
        blob_hashes = yield self.db_conn.runQuery(
            "select blob_hash from blobs where should_announce = 1")
        defer.returnValue([d[0] for d in blob_hashes])

    @rerun_if_locked
    def _get_all_verified_blob_hashes(self):
        d = self._get_all_blob_hashes()

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
