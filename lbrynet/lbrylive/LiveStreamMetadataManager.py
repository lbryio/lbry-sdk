import time
import logging
import leveldb
import json
import os
from twisted.internet import threads, defer
from lbrynet.core.server.DHTHashAnnouncer import DHTHashSupplier
from lbrynet.core.Error import DuplicateStreamHashError


class DBLiveStreamMetadataManager(DHTHashSupplier):
    """This class stores all stream info in a leveldb database stored in the same directory as the blobfiles"""

    def __init__(self, db_dir, hash_announcer):
        DHTHashSupplier.__init__(self, hash_announcer)
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

    def save_stream(self, stream_hash, pub_key, file_name, key, blobs):
        next_announce_time = time.time() + self.hash_reannounce_time
        d = threads.deferToThread(self._store_stream, stream_hash, pub_key, file_name, key,
                                  next_announce_time=next_announce_time)

        def save_blobs():
            return self.add_blobs_to_stream(stream_hash, blobs)

        def announce_have_stream():
            if self.hash_announcer is not None:
                self.hash_announcer.immediate_announce([stream_hash])
            return stream_hash

        d.addCallback(lambda _: save_blobs())
        d.addCallback(lambda _: announce_have_stream())
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

    def hashes_to_announce(self):
        next_announce_time = time.time() + self.hash_reannounce_time
        return threads.deferToThread(self._get_streams_to_announce, next_announce_time)

    ######### database calls #########

    def _open_db(self):
        self.stream_info_db = leveldb.LevelDB(os.path.join(self.db_dir, "stream_info.db"))
        self.stream_blob_db = leveldb.LevelDB(os.path.join(self.db_dir, "stream_blob.db"))
        self.stream_desc_db = leveldb.LevelDB(os.path.join(self.db_dir, "stream_desc.db"))

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

    def _store_stream(self, stream_hash, public_key, name, key, next_announce_time=None):
        try:
            self.stream_info_db.Get(stream_hash)
            raise DuplicateStreamHashError("Stream hash %s already exists" % stream_hash)
        except KeyError:
            pass
        self.stream_info_db.Put(stream_hash, json.dumps((public_key, key, name, next_announce_time)), sync=True)

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

    def _get_streams_to_announce(self, next_announce_time):
        # TODO: See if the following would be better for handling announce times:
        # TODO:    Have a separate db for them, and read the whole thing into memory
        # TODO:    on startup, and then write changes to db when they happen
        stream_hashes = []
        batch = leveldb.WriteBatch()
        current_time = time.time()
        for stream_hash, stream_info in self.stream_info_db.RangeIter():
            public_key, key, name, announce_time = json.loads(stream_info)
            if announce_time < current_time:
                batch.Put(stream_hash, json.dumps((public_key, key, name, next_announce_time)))
                stream_hashes.append(stream_hash)
        self.stream_info_db.Write(batch, sync=True)
        return stream_hashes

    def _get_blob_num_by_hash(self, stream_hash, blob_hash):
        blob_hash_stream_hash = json.dumps((blob_hash, stream_hash))
        return json.loads(self.stream_blob_db.Get(blob_hash_stream_hash))[0]

    def _get_further_blob_infos(self, stream_hash, start_num, end_num, count=None, reverse=False):
        blob_infos = []
        for blob_hash_stream_hash, blob_info in self.stream_blob_db.RangeIter():
            b_h, s_h = json.loads(blob_hash_stream_hash)
            if stream_hash == s_h:
                position, revision, iv, length, signature = json.loads(blob_info)
                if (start_num is None) or (position > start_num):
                    if (end_num is None) or (position < end_num):
                        blob_infos.append((b_h, position, revision, iv, length, signature))
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
                                  blob_info.revision,
                                  blob_info.iv,
                                  blob_info.length,
                                  blob_info.signature)))
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


class TempLiveStreamMetadataManager(DHTHashSupplier):

    def __init__(self, hash_announcer):
        DHTHashSupplier.__init__(self, hash_announcer)
        self.streams = {}
        self.stream_blobs = {}
        self.stream_desc = {}

    def setup(self):
        return defer.succeed(True)

    def stop(self):
        return defer.succeed(True)

    def get_all_streams(self):
        return defer.succeed(self.streams.keys())

    def save_stream(self, stream_hash, pub_key, file_name, key, blobs):
        next_announce_time = time.time() + self.hash_reannounce_time
        self.streams[stream_hash] = {'public_key': pub_key, 'stream_name': file_name,
                                     'key': key, 'next_announce_time': next_announce_time}
        d = self.add_blobs_to_stream(stream_hash, blobs)

        def announce_have_stream():
            if self.hash_announcer is not None:
                self.hash_announcer.immediate_announce([stream_hash])
            return stream_hash

        d.addCallback(lambda _: announce_have_stream())
        return d

    def get_stream_info(self, stream_hash):
        if stream_hash in self.streams:
            stream_info = self.streams[stream_hash]
            return defer.succeed([stream_info['public_key'], stream_info['key'], stream_info['stream_name']])
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
            info['revision'] = blob.revision
            info['signature'] = blob.signature
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
                revision = info['revision']
                signature = info['signature']
                if (start_num is None) or (position > start_num):
                    if (end_num is None) or (position < end_num):
                        blob_infos.append((b_h, position, revision, iv, length, signature))
        blob_infos.sort(key=lambda i: i[1], reverse=reverse)
        if count is not None:
            blob_infos = blob_infos[:count]
        return defer.succeed(blob_infos)

    def _get_blob_num_by_hash(self, stream_hash, blob_hash):
        if (stream_hash, blob_hash) in self.stream_blobs:
            return self.stream_blobs[(stream_hash, blob_hash)]['blob_num']

    def save_sd_blob_hash_to_stream(self, stream_hash, sd_blob_hash):
        self.stream_desc[sd_blob_hash] = stream_hash
        return defer.succeed(True)

    def get_sd_blob_hashes_for_stream(self, stream_hash):
        return defer.succeed([sd_hash for sd_hash, s_h in self.stream_desc.iteritems() if s_h == stream_hash])

    def hashes_to_announce(self):
        next_announce_time = time.time() + self.hash_reannounce_time
        stream_hashes = []
        current_time = time.time()
        for stream_hash, stream_info in self.streams.iteritems():
            announce_time = stream_info['announce_time']
            if announce_time < current_time:
                self.streams[stream_hash]['announce_time'] = next_announce_time
                stream_hashes.append(stream_hash)
        return stream_hashes