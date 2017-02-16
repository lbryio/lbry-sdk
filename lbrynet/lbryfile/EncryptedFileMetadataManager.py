import logging
import sqlite3
import os
from twisted.internet import defer
from twisted.enterprise import adbapi
from zope.interface import implements
from lbrynet.interfaces import IEncryptedFileMetadataManager
from lbrynet.core.Error import DuplicateStreamHashError, NoSuchStreamHash
from lbrynet.core.sqlite_helpers import rerun_if_locked


log = logging.getLogger(__name__)


class EncryptedFileMetadataManager(object):
    implements(IEncryptedFileMetadataManager)

    def __init__(self):
        self.streams = {}
        self.stream_blobs = {}
        self.sd_files = {}

    @defer.inlineCallbacks
    def setup(self):
        yield self._setup()

    @defer.inlineCallbacks
    def stop(self):
        yield self._stop()
        log.info("Stopped %s", self)

    @defer.inlineCallbacks
    def get_all_streams(self):
        stream_hashes = yield self._get_all_streams()
        defer.returnValue(stream_hashes)

    @defer.inlineCallbacks
    def save_stream(self, stream_hash, file_name, key, suggested_file_name, blobs):
        yield self._store_stream(stream_hash, file_name, key, suggested_file_name)
        yield self.add_blobs_to_stream(stream_hash, blobs)

    @defer.inlineCallbacks
    def get_stream_info(self, stream_hash):
        stream_info = yield self._get_stream_info(stream_hash)
        defer.returnValue(stream_info)

    @defer.inlineCallbacks
    def check_if_stream_exists(self, stream_hash):
        stream_exists = yield self._check_if_stream_exists(stream_hash)
        defer.returnValue(stream_exists)

    @defer.inlineCallbacks
    def delete_stream(self, stream_hash):
        yield self._delete_stream(stream_hash)

    @defer.inlineCallbacks
    def add_blobs_to_stream(self, stream_hash, blobs):
        yield self._add_blobs_to_stream(stream_hash, blobs, ignore_duplicate_error=True)

    @defer.inlineCallbacks
    def get_blobs_for_stream(self, stream_hash, start_blob=None,
                             end_blob=None, count=None, reverse=False):
        log.debug("Getting blobs for stream %s. Count is %s", stream_hash, count)
        if start_blob is not None:
            start_blob = yield self._get_blob_num_by_hash(stream_hash, start_blob)
        if end_blob is not None:
            end_blob = yield self._get_blob_num_by_hash(stream_hash, end_blob)
        blob_infos = yield self._get_further_blob_infos(stream_hash, start_blob,
                                                        end_blob, count, reverse)
        defer.returnValue(blob_infos)

    @defer.inlineCallbacks
    def get_stream_of_blob(self, blob_hash):
        stream_hash = yield self._get_stream_of_blobhash(blob_hash)
        defer.returnValue(stream_hash)

    @defer.inlineCallbacks
    def save_sd_blob_hash_to_stream(self, stream_hash, sd_blob_hash):
        yield self._save_sd_blob_hash_to_stream(stream_hash, sd_blob_hash)

    @defer.inlineCallbacks
    def get_sd_blob_hashes_for_stream(self, stream_hash):
        sd_hashes = yield self._get_sd_blob_hashes_for_stream(stream_hash)
        defer.returnValue(sd_hashes)

    # # # # # # # # # # # # # # # #
    # functions to be overridden  #
    # # # # # # # # # # # # # # # #

    def _delete_stream(self, stream_hash):
        if stream_hash in self.streams:
            del self.streams[stream_hash]
            for (s_h, b_h) in self.stream_blobs.keys():
                if s_h == stream_hash:
                    del self.stream_blobs[(s_h, b_h)]

    def _store_stream(self, stream_hash, name, key, suggested_file_name):
        self.streams[stream_hash] = {
            'suggested_file_name': suggested_file_name,
            'stream_name': name,
            'key': key
        }

    def _get_all_streams(self):
        return self.streams.keys()

    def _get_stream_info(self, stream_hash):
        if stream_hash in self.streams:
            stream_info = self.streams[stream_hash]
            return [stream_info['key'],
                      stream_info['stream_name'],
                      stream_info['suggested_file_name']]

    def _check_if_stream_exists(self, stream_hash):
        return stream_hash in self.streams

    def _get_blob_num_by_hash(self, stream_hash, blob_hash):
        if (stream_hash, blob_hash) in self.stream_blobs:
            return self.stream_blobs[(stream_hash, blob_hash)]['blob_num']

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
        return blob_infos

    def _add_blobs_to_stream(self, stream_hash, blob_infos, ignore_duplicate_error=False):
        assert stream_hash in self.streams, "Can't add blobs to a stream that isn't known"
        for blob in blob_infos:
            info = {}
            info['blob_num'] = blob.blob_num
            info['length'] = blob.length
            info['iv'] = blob.iv
            self.stream_blobs[(stream_hash, blob.blob_hash)] = info

    def _get_stream_of_blobhash(self, blob_hash):
        for (stream_hash, stream_blob_hash) in self.stream_blobs.iterkeys():
            if stream_blob_hash == blob_hash:
                return stream_hash

    def _save_sd_blob_hash_to_stream(self, stream_hash, sd_blob_hash):
        self.sd_files[sd_blob_hash] = stream_hash

    def _get_sd_blob_hashes_for_stream(self, stream_hash):
        return [sd_hash for sd_hash, s_h in self.sd_files.iteritems() if stream_hash == s_h]

    def _setup(self):
        return True

    def _stop(self):
        return True


class DBEncryptedFileMetadataManager(EncryptedFileMetadataManager):
    """Store and provide access to LBRY file metadata using sqlite"""

    def __init__(self, db_dir):
        EncryptedFileMetadataManager.__init__(self)
        self.db_dir = db_dir
        self.db_path = os.path.join(self.db_dir, "lbryfile_info.db")
        self.db_conn = None
        self.stream_info_db = None
        self.stream_blob_db = None
        self.stream_desc_db = None

    @defer.inlineCallbacks
    def _stop(self):
        if self.db_conn:
            yield self.db_conn.close()
        self.db_conn = None
        defer.returnValue(True)

    @defer.inlineCallbacks
    def _setup(self):
        # check_same_thread=False is solely to quiet a spurious error that appears to be due
        # to a bug in twisted, where the connection is closed by a different thread than the
        # one that opened it. The individual connections in the pool are not used in multiple
        # threads.
        self.db_conn = adbapi.ConnectionPool("sqlite3", self.db_path, check_same_thread=False)

        create_tables_queries = [
            "create table if not exists lbry_files (" +
            "    stream_hash text primary key, " +
            "    key text, " +
            "    stream_name text, " +
            "    suggested_file_name text" +
            ")",
            "create table if not exists lbry_file_blobs (" +
            "    blob_hash text, " +
            "    stream_hash text, " +
            "    position integer, " +
            "    iv text, " +
            "    length integer, " +
            "    foreign key(stream_hash) references lbry_files(stream_hash)" +
            ")",
            "create table if not exists lbry_file_descriptors (" +
            "    sd_blob_hash TEXT PRIMARY KEY, " +
            "    stream_hash TEXT, " +
            "    foreign key(stream_hash) references lbry_files(stream_hash)" +
            ")"
        ]

        for create_table_query in create_tables_queries:
            yield self.db_conn.runQuery(create_table_query)
        defer.returnValue(None)

    @rerun_if_locked
    @defer.inlineCallbacks
    def _delete_stream(self, stream_hash):
        select_stream_hash_query = "select stream_hash from lbry_files where stream_hash = ?"
        result = yield self.db_conn.runQuery(select_stream_hash_query, (stream_hash,))
        if result:
            yield self.db_conn.runQuery("delete from lbry_files where stream_hash = ?",
                                        (stream_hash,))
            yield self.db_conn.runQuery("delete from lbry_files where stream_hash = ?",
                                        (stream_hash,))
            yield self.db_conn.runQuery("delete from lbry_file_descriptors where stream_hash = ?",
                                        (stream_hash,))
        else:
            raise NoSuchStreamHash(stream_hash)
        defer.returnValue(None)

    @rerun_if_locked
    @defer.inlineCallbacks
    def _store_stream(self, stream_hash, name, key, suggested_file_name):
        try:
            yield self.db_conn.runQuery("insert into lbry_files values (?, ?, ?, ?)",
                                  (stream_hash, key, name, suggested_file_name))
        except sqlite3.IntegrityError:
            raise DuplicateStreamHashError(stream_hash)
        defer.returnValue(None)

    @rerun_if_locked
    @defer.inlineCallbacks
    def _get_all_streams(self):
        results = yield self.db_conn.runQuery("select stream_hash from lbry_files")
        defer.returnValue([r[0] for r in results])

    @rerun_if_locked
    @defer.inlineCallbacks
    def _get_stream_info(self, stream_hash):
        query = "select key, stream_name, suggested_file_name from lbry_files where stream_hash = ?"
        result = yield self.db_conn.runQuery(query, (stream_hash,))
        if result:
            defer.returnValue(result[0])
        else:
            raise NoSuchStreamHash(stream_hash)

    @rerun_if_locked
    @defer.inlineCallbacks
    def _check_if_stream_exists(self, stream_hash):
        query = "select stream_hash from lbry_files where stream_hash = ?"
        results = yield self.db_conn.runQuery(query, (stream_hash,))
        if results:
            defer.returnValue(True)
        else:
            defer.returnValue(False)

    @rerun_if_locked
    @defer.inlineCallbacks
    def _get_blob_num_by_hash(self, stream_hash, blob_hash):
        query = "select position from lbry_file_blobs where stream_hash = ? and blob_hash = ?"
        results = yield self.db_conn.runQuery(query, (stream_hash, blob_hash))
        result = None
        if results:
            result = results[0][0]
        defer.returnValue(result)

    @rerun_if_locked
    @defer.inlineCallbacks
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
        result = yield self.db_conn.runQuery(q_string, tuple(params))
        defer.returnValue(result)

    @rerun_if_locked
    @defer.inlineCallbacks
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

        result = yield self.db_conn.runInteraction(add_blobs)
        defer.returnValue(result)

    @rerun_if_locked
    @defer.inlineCallbacks
    def _get_stream_of_blobhash(self, blob_hash):
        query = "select stream_hash from lbry_file_blobs where blob_hash = ?"
        results = yield self.db_conn.runQuery(query, (blob_hash,))
        result = None
        if results:
            result = results[0][0]
        defer.returnValue(result)

    @rerun_if_locked
    @defer.inlineCallbacks
    def _save_sd_blob_hash_to_stream(self, stream_hash, sd_blob_hash):
        try:
            yield self.db_conn.runQuery("insert into lbry_file_descriptors values (?, ?)",
                                  (sd_blob_hash, stream_hash))
        except sqlite3.IntegrityError:
            log.warning("sd blob hash already known")
        defer.returnValue(None)

    @rerun_if_locked
    @defer.inlineCallbacks
    def _get_sd_blob_hashes_for_stream(self, stream_hash):
        query = "select sd_blob_hash from lbry_file_descriptors where stream_hash = ?"
        results = yield self.db_conn.runQuery(query, (stream_hash,))
        defer.returnValue([r[0] for r in results])
