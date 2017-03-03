import logging
import sqlite3
from twisted.internet import defer
from zope.interface import implements
from lbrynet.interfaces import IEncryptedFileMetadataManager
from lbrynet.core.Error import DuplicateStreamHashError, NoSuchStreamHash
from lbrynet.core import utils
from lbrynet.core.sqlite_helpers import rerun_if_locked
from lbrynet.core.Storage import MemoryStorage
from lbrynet.lbryfilemanager.EncryptedFileDownloader import ManagedEncryptedFileDownloader


log = logging.getLogger(__name__)


class EncryptedFileMetadataManager(object):
    implements(IEncryptedFileMetadataManager)

    def __init__(self):
        self.streams = {}
        self.stream_blobs = {}
        self.sd_files = {}
        self._database = MemoryStorage()

    @property
    def storage(self):
        return self._database

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
    def get_count_for_stream(self, stream_hash):
        result = yield self._get_count_for_stream(stream_hash)
        log.debug("Count for %s: %s", utils.short_hash(stream_hash), result or 0)
        if not result:
            defer.returnValue(0)
        defer.returnValue(result)

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
    def get_blobs_for_stream(self, stream_hash, start_blob=None, end_blob=None, count=None,
                             reverse=False):
        if start_blob is not None:
            start_blob = yield self._get_blob_num_by_hash(stream_hash, start_blob)
        if end_blob is not None:
            end_blob = yield self._get_blob_num_by_hash(stream_hash, end_blob)
        blob_infos = yield self._get_further_blob_infos(stream_hash, start_blob,
                                                        end_blob, count, reverse)
        if not blob_infos:
            blob_infos = []
        defer.returnValue(blob_infos)

    @defer.inlineCallbacks
    def get_stream_of_blob(self, blob_hash):
        stream_hash = yield self._get_stream_of_blobhash(blob_hash)
        defer.returnValue(stream_hash)

    @defer.inlineCallbacks
    def save_sd_blob_hash_to_stream(self, stream_hash, sd_blob_hash):
        yield self._save_sd_blob_hash_to_stream(stream_hash, sd_blob_hash)
        defer.returnValue(None)

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

    @defer.inlineCallbacks
    def _get_count_for_stream(self, stream_hash):
        blobs = yield self.get_blobs_for_stream(stream_hash)
        defer.returnValue(len(blobs))

    def _setup(self):
        return True

    def _stop(self):
        return True


class DBEncryptedFileMetadataManager(EncryptedFileMetadataManager):
    """Store and provide access to LBRY file metadata using sqlite"""

    def __init__(self, database):
        EncryptedFileMetadataManager.__init__(self)
        self._database = database

    @defer.inlineCallbacks
    def _stop(self):
        yield self.storage.close()
        defer.returnValue(True)

    @defer.inlineCallbacks
    def _setup(self):
        yield self.storage.open()

    @defer.inlineCallbacks
    def _delete_stream(self, stream_hash):
        query = "DELETE FROM files WHERE stream_hash=?"
        yield self.storage.query(query, (stream_hash))

    @defer.inlineCallbacks
    def _store_stream(self, stream_hash, file_name, decryption_key, published_file_name):
        query = ("INSERT INTO files VALUES (NULL, ?, NULL, ?, NULL, ?, ?, NULL)")
        try:
            yield self.storage.query(query, (ManagedEncryptedFileDownloader.STATUS_STREAM_PENDING,
                                             stream_hash,
                                             decryption_key,
                                             published_file_name))
        except sqlite3.IntegrityError:
            raise DuplicateStreamHashError(stream_hash)
        defer.returnValue(None)

    @defer.inlineCallbacks
    def _get_all_streams(self):
        results = yield self.storage.query("SELECT stream_hash FROM files "
                                                "WHERE stream_hash IS NOT NULL")
        defer.returnValue([r[0] for r in results])

    @defer.inlineCallbacks
    def _get_stream_info(self, stream_hash):
        query = ("SELECT decryption_key, published_file_name, published_file_name FROM files "
                 "WHERE stream_hash=?")
        result = yield self.storage.query(query, (stream_hash,))
        if result:
            defer.returnValue(result[0])
        else:
            raise NoSuchStreamHash(stream_hash)

    @defer.inlineCallbacks
    def _check_if_stream_exists(self, stream_hash):
        query = "SELECT stream_hash FROM files WHERE stream_hash=?"
        results = yield self.storage.query(query, (stream_hash,))
        if results:
            defer.returnValue(True)
        else:
            defer.returnValue(False)

    @defer.inlineCallbacks
    def _get_blob_num_by_hash(self, stream_hash, blob_hash):
        query = ("SELECT b.position FROM blobs b "
                 "INNER JOIN files f ON f.stream_hash=?"
                 "WHERE b.blob_hash=?")
        results = yield self.storage.query(query, (stream_hash, blob_hash))
        result = None
        if results:
            result = results[0][0]
        defer.returnValue(result)

    @defer.inlineCallbacks
    def _get_count_for_stream(self, stream_hash):
        query = ("SELECT count(*) FROM managed_blobs "
                 "INNER JOIN files f ON f.stream_hash=? AND f.id=managed_blobs.file_id")
        blob_count = yield self.storage.query(query, (stream_hash,))
        if blob_count:
            result = blob_count[0][0]
        else:
            result = 0
        defer.returnValue(result)

    @defer.inlineCallbacks
    def _get_further_blob_infos(self, stream_hash, start_num, end_num, count=None, reverse=False):
        if count is None:
            blob_count = yield self.get_count_for_stream(stream_hash)
        else:
            blob_count = count
        if start_num is None:
            start_num = 0
        if end_num is None:
            end_num = blob_count + 1

        query = ("SELECT blob_id, stream_position, iv, blob_length FROM managed_blobs "
                    "INNER JOIN files f ON "
                        "f.stream_hash=? AND f.id=managed_blobs.file_id "
                 "WHERE stream_position>=? AND stream_position<? "
                 "ORDER BY stream_position LIMIT ?")

        result = yield self.storage.query(query, (stream_hash, start_num, end_num, blob_count))
        results = []

        for blob_id, stream_position, iv, blob_length in result:
            blob_query = "SELECT blob_hash FROM blobs WHERE id=?"
            blob_hash_result = yield self.storage.query(blob_query, (blob_id, ))
            if blob_hash_result:
                blob_hash = blob_hash_result[0][0]
            else:
                blob_hash = None
            results.append((blob_hash, stream_position, iv, blob_length))
        defer.returnValue(results)

    @defer.inlineCallbacks
    def _add_empty_blob(self, stream_hash, blob_hash, stream_position, iv, length=0):
        file_id_result = yield self.storage.query("SELECT id FROM files WHERE stream_hash=?",
                                            (stream_hash, ))
        file_id = file_id_result[0][0]
        query = ("SELECT id FROM managed_blobs WHERE file_id=? AND blob_id IS NULL "
                 "OR blob_id=(SELECT id FROM blobs WHERE blob_hash=?)")
        check_exists = yield self.storage.query(query, (file_id, blob_hash))
        if not check_exists:
            if blob_hash:
                blob_id = "(SELECT id FROM blobs WHERE blob_hash=?)"
                args = (blob_hash, file_id, stream_position, iv, length)
            else:
                blob_id = "NULL"
                args = (file_id, stream_position, iv, length)
            empty_blob_query = ("INSERT INTO managed_blobs VALUES "
                                "(NULL, %s, ?, ?, ?, ?, NULL, NULL, NULL)" % blob_id)
            yield self.storage.query(empty_blob_query, args)
        defer.returnValue(None)

    @defer.inlineCallbacks
    def _add_blobs_to_stream(self, stream_hash, blobs, ignore_duplicate_error=False):
        add_blob_info_query = ("UPDATE managed_blobs SET "
                                   "file_id=(SELECT id FROM files WHERE stream_hash=?), "
                                   "stream_position=?, "
                                   "iv=?, "
                                   "blob_length=? "
                               "WHERE blob_id=(SELECT id FROM blobs WHERE blob_hash=?)")
        for blob in blobs:
            try:
                yield self._add_empty_blob(stream_hash, blob.blob_hash, blob.blob_num,
                                           blob.iv, blob.length)
            except Exception as err:
                log.exception(err)
                raise
            if blob.blob_hash:
                yield self.storage.query(add_blob_info_query, (stream_hash, blob.blob_num,
                                                               blob.iv, blob.length,
                                                               blob.blob_hash))

        defer.returnValue(True)

    @defer.inlineCallbacks
    def _get_stream_of_blobhash(self, blob_hash):
        query = ("SELECT f.stream_hash FROM files f "
                 "INNER JOIN managed_blobs mb ON mb.file_id=f.id "
                 "INNER JOIN blobs b ON mb.blob_id=b.id "
                 "WHERE b.blob_hash=? ")
        results = yield self.storage.query(query, (blob_hash,))
        result = None
        if results:
            result = results[0]
        defer.returnValue(result)

    @defer.inlineCallbacks
    def _save_sd_blob_hash_to_stream(self, stream_hash, sd_blob_hash):
        query = ("UPDATE files SET "
                 "sd_blob_id=(SELECT id FROM blobs WHERE blob_hash=?) "
                 "WHERE stream_hash=?")
        yield self.storage.query(query, (sd_blob_hash, stream_hash))
        query = ("UPDATE managed_blobs SET "
                 "file_id=(SELECT id FROM files WHERE stream_hash=?) "
                 "WHERE blob_id=(SELECT id FROM blobs WHERE blob_hash=?)")
        yield self.storage.query(query, (stream_hash, sd_blob_hash))
        defer.returnValue(None)

    @defer.inlineCallbacks
    def _get_sd_blob_hashes_for_stream(self, stream_hash):
        query = ("SELECT blob_hash FROM blobs WHERE "
                 "id=(SELECT sd_blob_id FROM files WHERE stream_hash=?)")
        results = yield self.storage.query(query, (stream_hash,))
        defer.returnValue([r[0] for r in results])
