import logging
import sqlite3
import os
from twisted.internet import defer
from twisted.python.failure import Failure
from twisted.enterprise import adbapi
from lbrynet.core.Error import DuplicateStreamHashError, NoSuchStreamHashError
from lbrynet.core.sqlite_helpers import rerun_if_locked


log = logging.getLogger(__name__)


class DBLBRYFileMetadataManager(object):
    """Store and provide access to LBRY file metadata using sqlite"""

    def __init__(self, db_dir):
        self.db_dir = db_dir
        self.stream_info_db = None
        self.stream_blob_db = None
        self.stream_desc_db = None

    def setup(self):
        return self._open_db()

    def stop(self):
        self.db_conn = None
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

    def get_blobs_for_stream(self, stream_hash, start_blob=None, end_blob=None, count=None, reverse=False):
        log.debug("Getting blobs for a stream. Count is %s", str(count))

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

    def _open_db(self):
        # check_same_thread=False is solely to quiet a spurious error that appears to be due
        # to a bug in twisted, where the connection is closed by a different thread than the
        # one that opened it. The individual connections in the pool are not used in multiple
        # threads.
        self.db_conn = adbapi.ConnectionPool("sqlite3", (os.path.join(self.db_dir, "lbryfile_info.db")),
                                             check_same_thread=False)

        def create_tables(transaction):
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

        return self.db_conn.runInteraction(create_tables)

    @rerun_if_locked
    def _delete_stream(self, stream_hash):
        d = self.db_conn.runQuery("select stream_hash from lbry_files where stream_hash = ?", (stream_hash,))
        d.addCallback(lambda result: result[0][0] if len(result) else Failure(NoSuchStreamHashError(stream_hash)))

        def do_delete(transaction, s_h):
            transaction.execute("delete from lbry_files where stream_hash = ?", (s_h,))
            transaction.execute("delete from lbry_file_blobs where stream_hash = ?", (s_h,))
            transaction.execute("delete from lbry_file_descriptors where stream_hash = ?", (s_h,))

        d.addCallback(lambda s_h: self.db_conn.runInteraction(do_delete, s_h))
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
        d = self.db_conn.runQuery("select key, stream_name, suggested_file_name from lbry_files where stream_hash = ?",
                                  (stream_hash,))
        d.addCallback(lambda result: result[0] if len(result) else Failure(NoSuchStreamHashError(stream_hash)))
        return d

    @rerun_if_locked
    def _check_if_stream_exists(self, stream_hash):
        d = self.db_conn.runQuery("select stream_hash from lbry_files where stream_hash = ?", (stream_hash,))
        d.addCallback(lambda r: True if len(r) else False)
        return d

    @rerun_if_locked
    def _get_blob_num_by_hash(self, stream_hash, blob_hash):
        d = self.db_conn.runQuery("select position from lbry_file_blobs where stream_hash = ? and blob_hash = ?",
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
        log.info("Saving sd blob hash %s to stream hash %s", str(sd_blob_hash), str(stream_hash))
        d = self.db_conn.runQuery("insert into lbry_file_descriptors values (?, ?)",
                                  (sd_blob_hash, stream_hash))

        def ignore_duplicate(err):
            err.trap(sqlite3.IntegrityError)
            log.info("sd blob hash already known")

        d.addErrback(ignore_duplicate)
        return d

    @rerun_if_locked
    def _get_sd_blob_hashes_for_stream(self, stream_hash):
        log.debug("Looking up sd blob hashes for stream hash %s", str(stream_hash))
        d = self.db_conn.runQuery("select sd_blob_hash from lbry_file_descriptors where stream_hash = ?",
                                  (stream_hash,))
        d.addCallback(lambda results: [r[0] for r in results])
        return d


class TempLBRYFileMetadataManager(object):
    def __init__(self):
        self.streams = {}
        self.stream_blobs = {}
        self.sd_files = {}

    def setup(self):
        return defer.succeed(True)

    def stop(self):
        return defer.succeed(True)

    def get_all_streams(self):
        return defer.succeed(self.streams.keys())

    def save_stream(self, stream_hash, file_name, key, suggested_file_name, blobs):
        self.streams[stream_hash] = {'suggested_file_name': suggested_file_name,
                                     'stream_name': file_name,
                                     'key': key}
        d = self.add_blobs_to_stream(stream_hash, blobs)
        d.addCallback(lambda _: stream_hash)
        return d

    def get_stream_info(self, stream_hash):
        if stream_hash in self.streams:
            stream_info = self.streams[stream_hash]
            return defer.succeed([stream_info['key'], stream_info['stream_name'],
                                  stream_info['suggested_file_name']])
        return defer.succeed(None)

    def delete_stream(self, stream_hash):
        if stream_hash in self.streams:
            del self.streams[stream_hash]
            for (s_h, b_h) in self.stream_blobs.keys():
                if s_h == stream_hash:
                    del self.stream_blobs[(s_h, b_h)]
        return defer.succeed(True)

    def add_blobs_to_stream(self, stream_hash, blobs):
        assert stream_hash in self.streams, "Can't add blobs to a stream that isn't known"
        for blob in blobs:
            info = {}
            info['blob_num'] = blob.blob_num
            info['length'] = blob.length
            info['iv'] = blob.iv
            self.stream_blobs[(stream_hash, blob.blob_hash)] = info
        return defer.succeed(True)

    def get_blobs_for_stream(self, stream_hash, start_blob=None, end_blob=None, count=None, reverse=False):

        if start_blob is not None:
            start_num = self._get_blob_num_by_hash(stream_hash, start_blob)
        else:
            start_num = None
        if end_blob is not None:
            end_num = self._get_blob_num_by_hash(stream_hash, end_blob)
        else:
            end_num = None
        return self._get_further_blob_infos(stream_hash, start_num, end_num, count, reverse)

    def get_stream_of_blob(self, blob_hash):
        for (s_h, b_h) in self.stream_blobs.iterkeys():
            if b_h == blob_hash:
                return defer.succeed(s_h)
        return defer.succeed(None)

    def _get_further_blob_infos(self, stream_hash, start_num, end_num, count=None, reverse=False):
        blob_infos = []
        for (s_h, b_h), info in self.stream_blobs.iteritems():
            if stream_hash == s_h:
                position = info['blob_num']
                length = info['length']
                iv = info['iv']
                if (start_num is None) or (position > start_num):
                    if (end_num is None) or (position < end_num):
                        blob_infos.append((b_h, position, iv, length))
        blob_infos.sort(key=lambda i: i[1], reverse=reverse)
        if count is not None:
            blob_infos = blob_infos[:count]
        return defer.succeed(blob_infos)

    def _get_blob_num_by_hash(self, stream_hash, blob_hash):
        if (stream_hash, blob_hash) in self.stream_blobs:
            return defer.succeed(self.stream_blobs[(stream_hash, blob_hash)]['blob_num'])

    def save_sd_blob_hash_to_stream(self, stream_hash, sd_blob_hash):
        self.sd_files[sd_blob_hash] = stream_hash
        return defer.succeed(True)

    def get_sd_blob_hashes_for_stream(self, stream_hash):
        return defer.succeed([sd_hash for sd_hash, s_h in self.sd_files.iteritems() if stream_hash == s_h])