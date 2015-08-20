import logging
import leveldb
import json
import os
from twisted.internet import threads, defer
from lbrynet.core.Error import DuplicateStreamHashError


class DBLBRYFileMetadataManager(object):
    """Store and provide access to LBRY file metadata using leveldb files"""

    def __init__(self, db_dir):
        self.db_dir = db_dir
        self.stream_info_db = None
        self.stream_blob_db = None
        self.stream_desc_db = None

    def setup(self):
        return threads.deferToThread(self._open_db)

    def stop(self):
        self.stream_info_db = None
        self.stream_blob_db = None
        self.stream_desc_db = None
        return defer.succeed(True)

    def get_all_streams(self):
        return threads.deferToThread(self._get_all_streams)

    def save_stream(self, stream_hash, file_name, key, suggested_file_name, blobs):
        d = threads.deferToThread(self._store_stream, stream_hash, file_name, key, suggested_file_name)
        d.addCallback(lambda _: self.add_blobs_to_stream(stream_hash, blobs))
        return d

    def get_stream_info(self, stream_hash):
        return threads.deferToThread(self._get_stream_info, stream_hash)

    def check_if_stream_exists(self, stream_hash):
        return threads.deferToThread(self._check_if_stream_exists, stream_hash)

    def delete_stream(self, stream_hash):
        return threads.deferToThread(self._delete_stream, stream_hash)

    def add_blobs_to_stream(self, stream_hash, blobs):

        def add_blobs():
            self._add_blobs_to_stream(stream_hash, blobs, ignore_duplicate_error=True)

        return threads.deferToThread(add_blobs)

    def get_blobs_for_stream(self, stream_hash, start_blob=None, end_blob=None, count=None, reverse=False):
        logging.info("Getting blobs for a stream. Count is %s", str(count))

        def get_positions_of_start_and_end():
            if start_blob is not None:
                start_num = self._get_blob_num_by_hash(stream_hash, start_blob)
            else:
                start_num = None
            if end_blob is not None:
                end_num = self._get_blob_num_by_hash(stream_hash, end_blob)
            else:
                end_num = None
            return start_num, end_num

        def get_blob_infos(nums):
            start_num, end_num = nums
            return threads.deferToThread(self._get_further_blob_infos, stream_hash, start_num, end_num,
                                         count, reverse)

        d = threads.deferToThread(get_positions_of_start_and_end)
        d.addCallback(get_blob_infos)
        return d

    def get_stream_of_blob(self, blob_hash):
        return threads.deferToThread(self._get_stream_of_blobhash, blob_hash)

    def save_sd_blob_hash_to_stream(self, stream_hash, sd_blob_hash):
        return threads.deferToThread(self._save_sd_blob_hash_to_stream, stream_hash, sd_blob_hash)

    def get_sd_blob_hashes_for_stream(self, stream_hash):
        return threads.deferToThread(self._get_sd_blob_hashes_for_stream, stream_hash)

    def _open_db(self):
        self.stream_info_db = leveldb.LevelDB(os.path.join(self.db_dir, "lbryfile_info.db"))
        self.stream_blob_db = leveldb.LevelDB(os.path.join(self.db_dir, "lbryfile_blob.db"))
        self.stream_desc_db = leveldb.LevelDB(os.path.join(self.db_dir, "lbryfile_desc.db"))

    def _delete_stream(self, stream_hash):
        desc_batch = leveldb.WriteBatch()
        for sd_blob_hash, s_h in self.stream_desc_db.RangeIter():
            if stream_hash == s_h:
                desc_batch.Delete(sd_blob_hash)
        self.stream_desc_db.Write(desc_batch, sync=True)

        blob_batch = leveldb.WriteBatch()
        for blob_hash_stream_hash, blob_info in self.stream_blob_db.RangeIter():
            b_h, s_h = json.loads(blob_hash_stream_hash)
            if stream_hash == s_h:
                blob_batch.Delete(blob_hash_stream_hash)
        self.stream_blob_db.Write(blob_batch, sync=True)

        stream_batch = leveldb.WriteBatch()
        for s_h, stream_info in self.stream_info_db.RangeIter():
            if stream_hash == s_h:
                stream_batch.Delete(s_h)
        self.stream_info_db.Write(stream_batch, sync=True)

    def _store_stream(self, stream_hash, name, key, suggested_file_name):
        try:
            self.stream_info_db.Get(stream_hash)
            raise DuplicateStreamHashError("Stream hash %s already exists" % stream_hash)
        except KeyError:
            pass
        self.stream_info_db.Put(stream_hash, json.dumps((key, name, suggested_file_name)), sync=True)

    def _get_all_streams(self):
        return [stream_hash for stream_hash, stream_info in self.stream_info_db.RangeIter()]

    def _get_stream_info(self, stream_hash):
        return json.loads(self.stream_info_db.Get(stream_hash))[:3]

    def _check_if_stream_exists(self, stream_hash):
        try:
            self.stream_info_db.Get(stream_hash)
            return True
        except KeyError:
            return False

    def _get_blob_num_by_hash(self, stream_hash, blob_hash):
        blob_hash_stream_hash = json.dumps((blob_hash, stream_hash))
        return json.loads(self.stream_blob_db.Get(blob_hash_stream_hash))[0]

    def _get_further_blob_infos(self, stream_hash, start_num, end_num, count=None, reverse=False):
        blob_infos = []
        for blob_hash_stream_hash, blob_info in self.stream_blob_db.RangeIter():
            b_h, s_h = json.loads(blob_hash_stream_hash)
            if stream_hash == s_h:
                position, iv, length = json.loads(blob_info)
                if (start_num is None) or (position > start_num):
                    if (end_num is None) or (position < end_num):
                        blob_infos.append((b_h, position, iv, length))
        blob_infos.sort(key=lambda i: i[1], reverse=reverse)
        if count is not None:
            blob_infos = blob_infos[:count]
        return blob_infos

    def _add_blobs_to_stream(self, stream_hash, blob_infos, ignore_duplicate_error=False):
        batch = leveldb.WriteBatch()
        for blob_info in blob_infos:
            blob_hash_stream_hash = json.dumps((blob_info.blob_hash, stream_hash))
            try:
                self.stream_blob_db.Get(blob_hash_stream_hash)
                if ignore_duplicate_error is False:
                    raise KeyError()  # TODO: change this to DuplicateStreamBlobError?
                continue
            except KeyError:
                pass
            batch.Put(blob_hash_stream_hash,
                      json.dumps((blob_info.blob_num,
                                  blob_info.iv,
                                  blob_info.length)))
        self.stream_blob_db.Write(batch, sync=True)

    def _get_stream_of_blobhash(self, blob_hash):
        for blob_hash_stream_hash, blob_info in self.stream_blob_db.RangeIter():
            b_h, s_h = json.loads(blob_hash_stream_hash)
            if blob_hash == b_h:
                return s_h
        return None

    def _save_sd_blob_hash_to_stream(self, stream_hash, sd_blob_hash):
        self.stream_desc_db.Put(sd_blob_hash, stream_hash)

    def _get_sd_blob_hashes_for_stream(self, stream_hash):
        return [sd_blob_hash for sd_blob_hash, s_h in self.stream_desc_db.RangeIter() if stream_hash == s_h]


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