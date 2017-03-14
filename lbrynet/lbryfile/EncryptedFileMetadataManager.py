import logging
from twisted.internet import defer
from zope.interface import implements
from lbrynet.interfaces import IEncryptedFileMetadataManager
from lbrynet.core import utils
from lbrynet.core.Storage import MemoryStorage


log = logging.getLogger(__name__)


class EncryptedFileMetadataManager(object):
    """Store and provide access to LBRY file metadata using sqlite"""
    implements(IEncryptedFileMetadataManager)

    def __init__(self, storage=None):
        self.streams = {}
        self.stream_blobs = {}
        self.sd_files = {}
        self._database = storage or MemoryStorage()

    @property
    def storage(self):
        return self._database

    def setup(self):
        return self.storage.open()

    def stop(self):
        return self.storage.close()

    def get_all_streams(self):
        return self.storage.get_all_streams()

    @defer.inlineCallbacks
    def save_stream(self, stream_hash, file_name, key, suggested_file_name, blobs):
        yield self.storage.store_stream(stream_hash, file_name, key, suggested_file_name)
        yield self.storage.add_blobs_to_stream(stream_hash, blobs, ignore_duplicate_error=True)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def get_stream_info(self, stream_hash):
        stream_info = yield self.storage.get_stream_info(stream_hash)
        defer.returnValue(stream_info)

    @defer.inlineCallbacks
    def get_count_for_stream(self, stream_hash):
        result = yield self.storage.get_count_for_stream(stream_hash)
        log.debug("Count for %s: %i", utils.short_hash(stream_hash), result)
        if not result:
            defer.returnValue(0)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def check_if_stream_exists(self, stream_hash):
        stream_exists = yield self.storage.check_if_stream_exists(stream_hash)
        defer.returnValue(stream_exists)

    @defer.inlineCallbacks
    def delete_stream(self, stream_hash):
        yield self.storage.delete_stream(stream_hash)

    @defer.inlineCallbacks
    def get_blobs_for_stream(self, stream_hash):
        blob_infos = yield self.storage.get_blobs_for_stream(stream_hash)
        if not blob_infos:
            blob_infos = []
        defer.returnValue(blob_infos)

    def add_blobs_to_stream(self, stream_hash, blobs):
        return self.storage.add_blobs_to_stream(stream_hash, blobs)

    @defer.inlineCallbacks
    def get_stream_of_blob(self, blob_hash):
        stream_hash = yield self.storage.get_stream_of_blobhash(blob_hash)
        defer.returnValue(stream_hash)

    @defer.inlineCallbacks
    def save_sd_blob_hash_to_stream(self, stream_hash, sd_blob_hash):
        yield self.storage.save_sd_blob_hash_to_stream(stream_hash, sd_blob_hash)
        defer.returnValue(None)

    @defer.inlineCallbacks
    def get_sd_blob_hashes_for_stream(self, stream_hash):
        sd_hashes = yield self.storage.get_sd_hash_for_stream(stream_hash)
        defer.returnValue(sd_hashes)
