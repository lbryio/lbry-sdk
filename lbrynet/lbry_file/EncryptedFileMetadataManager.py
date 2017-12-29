import os
import logging
import sqlite3
import binascii
from twisted.internet import defer
from twisted.python.failure import Failure
from twisted.enterprise import adbapi
from lbrynet.core.Error import DuplicateStreamHashError, NoSuchStreamHash, NoSuchSDHash
from lbrynet.core.sqlite_helpers import rerun_if_locked
from lbrynet.file_manager.EncryptedFileDownloader import ManagedEncryptedFileDownloader

log = logging.getLogger(__name__)


class DBEncryptedFileMetadataManager(object):
    """Store and provide access to LBRY file metadata using sqlite"""

    def __init__(self, db_dir, file_name=None):
        self.db_dir = db_dir
        self._db_file_name = file_name or "lbryfile_info.db"
        self.db_conn = adbapi.ConnectionPool("sqlite3", os.path.join(self.db_dir,
                                                                     self._db_file_name),
                                             check_same_thread=False)

    def setup(self):
        return self._open_db()

    def stop(self):
        self.db_conn.close()
        return defer.succeed(True)

    def get_all_streams(self):
        return self._get_all_streams()

    def save_stream(self, stream_hash, file_name, key, suggested_file_name, blobs):
        d = self._store_stream(stream_hash, file_name, key, suggested_file_name)
        d.addCallback(lambda _: self.add_blobs_to_stream(stream_hash, blobs))
        return d

    def get_stream_info(self, stream_hash):
        return self._get_stream_info(stream_hash)

    def check_if_stream_exists(self, stream_hash):
        return self._check_if_stream_exists(stream_hash)

    def delete_stream(self, stream_hash):
        return self._delete_stream(stream_hash)

    def add_blobs_to_stream(self, stream_hash, blobs):
        return self._add_blobs_to_stream(stream_hash, blobs, ignore_duplicate_error=True)

    def get_blobs_for_stream(self, stream_hash, start_blob=None,
                             end_blob=None, count=None, reverse=False):
        log.debug("Getting blobs for stream %s. Count is %s", stream_hash, count)

        def get_positions_of_start_and_end():
            if start_blob is not None:
                d1 = self._get_blob_num_by_hash(stream_hash, start_blob)
            else:
                d1 = defer.succeed(None)
            if end_blob is not None:
                d2 = self._get_blob_num_by_hash(stream_hash, end_blob)
            else:
                d2 = defer.succeed(None)

            dl = defer.DeferredList([d1, d2])

            def get_positions(results):
                start_num = None
                end_num = None
                if results[0][0] is True:
                    start_num = results[0][1]
                if results[1][0] is True:
                    end_num = results[1][1]
                return start_num, end_num

            dl.addCallback(get_positions)
            return dl

        def get_blob_infos(nums):
            start_num, end_num = nums
            return self._get_further_blob_infos(stream_hash, start_num, end_num,
                                                count, reverse)

        d = get_positions_of_start_and_end()
        d.addCallback(get_blob_infos)
        return d

    def get_stream_of_blob(self, blob_hash):
        return self._get_stream_of_blobhash(blob_hash)

    def save_sd_blob_hash_to_stream(self, stream_hash, sd_blob_hash):
        return self._save_sd_blob_hash_to_stream(stream_hash, sd_blob_hash)

    def get_sd_blob_hashes_for_stream(self, stream_hash):
        return self._get_sd_blob_hashes_for_stream(stream_hash)

    def get_stream_hash_for_sd_hash(self, sd_hash):
        return self._get_stream_hash_for_sd_blob_hash(sd_hash)

    @staticmethod
    def _create_tables(transaction):
        transaction.execute("create table if not exists lbry_files (" +
                            "    stream_hash text primary key, " +
                            "    key text, " +
                            "    stream_name text, " +
                            "    suggested_file_name text" +
                            ")")
        transaction.execute("create table if not exists lbry_file_blobs (" +
                            "    blob_hash text, " +
                            "    stream_hash text, " +
                            "    position integer, " +
                            "    iv text, " +
                            "    length integer, " +
                            "    foreign key(stream_hash) references lbry_files(stream_hash)" +
                            ")")
        transaction.execute("create table if not exists lbry_file_descriptors (" +
                            "    sd_blob_hash TEXT PRIMARY KEY, " +
                            "    stream_hash TEXT, " +
                            "    foreign key(stream_hash) references lbry_files(stream_hash)" +
                            ")")
        transaction.execute("create table if not exists lbry_file_options (" +
                            "    blob_data_rate real, " +
                            "    status text," +
                            "    stream_hash text,"
                            "    foreign key(stream_hash) references lbry_files(stream_hash)" +
                            ")")
        transaction.execute("create table if not exists lbry_file_metadata (" +
                            "    lbry_file integer primary key, " +
                            "    txid text, " +
                            "    n integer, " +
                            "    foreign key(lbry_file) references lbry_files(rowid)"
                            ")")

    def _open_db(self):
        # check_same_thread=False is solely to quiet a spurious error that appears to be due
        # to a bug in twisted, where the connection is closed by a different thread than the
        # one that opened it. The individual connections in the pool are not used in multiple
        # threads.
        return self.db_conn.runInteraction(self._create_tables)

    @rerun_if_locked
    @defer.inlineCallbacks
    def get_file_outpoint(self, rowid):
        result = yield self.db_conn.runQuery("select txid, n from lbry_file_metadata "
                                             "where lbry_file=?", (rowid, ))
        response = None
        if result:
            txid, nout = result[0]
            if txid is not None and nout is not None:
                response = "%s:%i" % (txid, nout)
        defer.returnValue(response)

    @rerun_if_locked
    @defer.inlineCallbacks
    def save_outpoint_to_file(self, rowid, txid, nout):
        existing_outpoint = yield self.get_file_outpoint(rowid)
        if not existing_outpoint:
            yield self.db_conn.runOperation("insert into lbry_file_metadata values "
                                            "(?, ?, ?)", (rowid, txid, nout))

    @rerun_if_locked
    def _delete_stream(self, stream_hash):
        d = self.db_conn.runQuery(
            "select rowid, stream_hash from lbry_files where stream_hash = ?", (stream_hash,))
        d.addCallback(
            lambda result: result[0] if result else Failure(NoSuchStreamHash(stream_hash)))

        def do_delete(transaction, row_id, s_h):
            transaction.execute("delete from lbry_files where stream_hash = ?", (s_h,))
            transaction.execute("delete from lbry_file_blobs where stream_hash = ?", (s_h,))
            transaction.execute("delete from lbry_file_descriptors where stream_hash = ?", (s_h,))
            transaction.execute("delete from lbry_file_metadata where lbry_file = ?", (row_id,))

        d.addCallback(lambda (row_id, s_h): self.db_conn.runInteraction(do_delete, row_id, s_h))
        return d

    @rerun_if_locked
    def _store_stream(self, stream_hash, name, key, suggested_file_name):
        d = self.db_conn.runQuery("insert into lbry_files values (?, ?, ?, ?)",
                                  (stream_hash, key, name, suggested_file_name))

        def check_duplicate(err):
            if err.check(sqlite3.IntegrityError):
                raise DuplicateStreamHashError(stream_hash)
            return err

        d.addErrback(check_duplicate)
        return d

    @rerun_if_locked
    def _get_all_streams(self):
        d = self.db_conn.runQuery("select stream_hash from lbry_files")
        d.addCallback(lambda results: [r[0] for r in results])
        return d

    @rerun_if_locked
    def _get_stream_info(self, stream_hash):
        def get_result(res):
            if res:
                return res[0]
            else:
                raise NoSuchStreamHash(stream_hash)

        d = self.db_conn.runQuery(
            "select key, stream_name, suggested_file_name from lbry_files where stream_hash = ?",
            (stream_hash,))
        d.addCallback(get_result)
        return d

    @rerun_if_locked
    @defer.inlineCallbacks
    def _get_all_stream_infos(self):
        file_results = yield self.db_conn.runQuery("select rowid, * from lbry_files")
        descriptor_results = yield self.db_conn.runQuery("select stream_hash, sd_blob_hash "
                                                         "from lbry_file_descriptors")
        response = {}
        for (stream_hash, sd_hash) in descriptor_results:
            if stream_hash in response:
                log.warning("Duplicate stream %s (sd: %s)", stream_hash, sd_hash[:16])
                continue
            response[stream_hash] = {
                'sd_hash': sd_hash
            }
        for (rowid, stream_hash, key, stream_name, suggested_file_name) in file_results:
            if stream_hash not in response:
                log.warning("Missing sd hash for %s", stream_hash)
                continue
            response[stream_hash]['rowid'] = rowid
            response[stream_hash]['key'] = binascii.unhexlify(key)
            response[stream_hash]['stream_name'] = binascii.unhexlify(stream_name)
            response[stream_hash]['suggested_file_name'] = binascii.unhexlify(suggested_file_name)
        defer.returnValue(response)

    @rerun_if_locked
    def _check_if_stream_exists(self, stream_hash):
        d = self.db_conn.runQuery(
            "select stream_hash from lbry_files where stream_hash = ?", (stream_hash,))
        d.addCallback(lambda r: True if len(r) else False)
        return d

    @rerun_if_locked
    def _get_blob_num_by_hash(self, stream_hash, blob_hash):
        d = self.db_conn.runQuery(
            "select position from lbry_file_blobs where stream_hash = ? and blob_hash = ?",
            (stream_hash, blob_hash))
        d.addCallback(lambda r: r[0][0] if len(r) else None)
        return d

    @rerun_if_locked
    def _get_further_blob_infos(self, stream_hash, start_num, end_num, count=None, reverse=False):
        params = []
        q_string = "select * from ("
        q_string += "  select blob_hash, position, iv, length from lbry_file_blobs "
        q_string += "    where stream_hash = ? "
        params.append(stream_hash)
        if start_num is not None:
            q_string += "    and position > ? "
            params.append(start_num)
        if end_num is not None:
            q_string += "    and position < ? "
            params.append(end_num)
        q_string += "    order by position "
        if reverse is True:
            q_string += "   DESC "
        if count is not None:
            q_string += "    limit ? "
            params.append(count)
        q_string += ") order by position"
        # Order by position is done twice so that it always returns them from lowest position to
        # greatest, but the limit by clause can select the 'count' greatest or 'count' least
        return self.db_conn.runQuery(q_string, tuple(params))

    @rerun_if_locked
    def _add_blobs_to_stream(self, stream_hash, blob_infos, ignore_duplicate_error=False):

        def add_blobs(transaction):
            for blob_info in blob_infos:
                try:
                    transaction.execute("insert into lbry_file_blobs values (?, ?, ?, ?, ?)",
                                        (blob_info.blob_hash, stream_hash, blob_info.blob_num,
                                         blob_info.iv, blob_info.length))
                except sqlite3.IntegrityError:
                    if ignore_duplicate_error is False:
                        raise

        return self.db_conn.runInteraction(add_blobs)

    @rerun_if_locked
    def _get_stream_of_blobhash(self, blob_hash):
        d = self.db_conn.runQuery("select stream_hash from lbry_file_blobs where blob_hash = ?",
                                  (blob_hash,))
        d.addCallback(lambda r: r[0][0] if len(r) else None)
        return d

    @rerun_if_locked
    def _save_sd_blob_hash_to_stream(self, stream_hash, sd_blob_hash):
        d = self.db_conn.runOperation("insert or ignore into lbry_file_descriptors values (?, ?)",
                                      (sd_blob_hash, stream_hash))
        d.addCallback(lambda _: log.info("Saved sd blob hash %s to stream hash %s",
                                         str(sd_blob_hash), str(stream_hash)))
        return d

    @rerun_if_locked
    def _get_sd_blob_hashes_for_stream(self, stream_hash):
        log.debug("Looking up sd blob hashes for stream hash %s", str(stream_hash))
        d = self.db_conn.runQuery(
            "select sd_blob_hash from lbry_file_descriptors where stream_hash = ?",
            (stream_hash,))
        d.addCallback(lambda results: [r[0] for r in results])
        return d

    @rerun_if_locked
    def _get_stream_hash_for_sd_blob_hash(self, sd_blob_hash):
        def _handle_result(result):
            if not result:
                raise NoSuchSDHash(sd_blob_hash)
            return result[0][0]

        log.debug("Looking up sd blob hashes for sd blob hash %s", str(sd_blob_hash))
        d = self.db_conn.runQuery(
            "select stream_hash from lbry_file_descriptors where sd_blob_hash = ?",
            (sd_blob_hash,))
        d.addCallback(_handle_result)
        return d

    # used by lbry file manager
    @rerun_if_locked
    def _save_lbry_file(self, stream_hash, data_payment_rate):
        def do_save(db_transaction):
            row = (data_payment_rate, ManagedEncryptedFileDownloader.STATUS_STOPPED, stream_hash)
            db_transaction.execute("insert into lbry_file_options values (?, ?, ?)", row)
            return db_transaction.lastrowid
        return self.db_conn.runInteraction(do_save)

    @rerun_if_locked
    def _delete_lbry_file_options(self, rowid):
        return self.db_conn.runQuery("delete from lbry_file_options where rowid = ?",
                                    (rowid,))

    @rerun_if_locked
    def _set_lbry_file_payment_rate(self, rowid, new_rate):
        return self.db_conn.runQuery(
            "update lbry_file_options set blob_data_rate = ? where rowid = ?",
            (new_rate, rowid))

    @rerun_if_locked
    def _get_all_lbry_files(self):
        d = self.db_conn.runQuery("select rowid, stream_hash, blob_data_rate, status "
                                  "from lbry_file_options")
        return d

    @rerun_if_locked
    def _change_file_status(self, rowid, new_status):
        d = self.db_conn.runQuery("update lbry_file_options set status = ? where rowid = ?",
                                    (new_status, rowid))
        d.addCallback(lambda _: new_status)
        return d

    @rerun_if_locked
    def _get_lbry_file_status(self, rowid):
        d = self.db_conn.runQuery("select status from lbry_file_options where rowid = ?",
                                 (rowid,))
        d.addCallback(lambda r: (r[0][0] if len(r) else None))
        return d

    @rerun_if_locked
    def _get_count_for_stream_hash(self, stream_hash):
        d = self.db_conn.runQuery("select count(*) from lbry_file_options where stream_hash = ?",
                                     (stream_hash,))
        d.addCallback(lambda r: (r[0][0] if r else 0))
        return d

    @rerun_if_locked
    def _get_rowid_for_stream_hash(self, stream_hash):
        d = self.db_conn.runQuery("select rowid from lbry_file_options where stream_hash = ?",
                                     (stream_hash,))
        d.addCallback(lambda r: (r[0][0] if len(r) else None))
        return d
