import logging

from twisted.internet import defer
from zope.interface import implements
from lbrynet.interfaces import IBlobManager
from lbrynet.core.HashBlob import BlobFile, TempBlob, BlobFileCreator, TempBlobCreator
from lbrynet.core.server.DHTHashAnnouncer import DHTHashSupplier
from lbrynet.core.Error import NoSuchBlobError
from lbrynet.core import Storage

log = logging.getLogger(__name__)


class BlobManager(DHTHashSupplier):
    implements(IBlobManager)

    def __init__(self, hash_announcer, blob_dir=None, storage=None):
        DHTHashSupplier.__init__(self, hash_announcer)
        self.blob_dir = blob_dir
        self.storage = storage or Storage.MemoryStorage()
        if self.blob_dir:
            self.blob_type = BlobFile
            self.blob_creator_type = BlobFileCreator
        else:
            self.blob_type = TempBlob
            self.blob_creator_type = TempBlobCreator
        self.blobs = {}
        self.blob_next_announces = {}
        self.blob_hashes_to_delete = {}  # {blob_hash: being_deleted (True/False)}
        self._next_manage_call = None

    @defer.inlineCallbacks
    def setup(self):
        yield self.storage.open()
        yield self._manage()

    def stop(self):
        if self._next_manage_call is not None and self._next_manage_call.active():
            self._next_manage_call.cancel()
            self._next_manage_call = None
        return self.storage.close()

    def get_blob(self, blob_hash, length=None):
        assert length is None or isinstance(length, int)
        blob = self.blobs.get(blob_hash, False)
        if blob:
            return defer.succeed(blob)
        creator = self.get_blob_creator()
        self._make_new_blob(creator, blob_hash, length)
        return defer.succeed(self.blobs[blob_hash])

    def get_blob_creator(self):
        return self.blob_creator_type(self, self.blob_dir)

    @defer.inlineCallbacks
    def blob_completed(self, blob, next_announce_time=None):
        if next_announce_time is None:
            next_announce_time = self.get_next_announce_time()
        yield self.storage.add_completed_blob(blob.blob_hash, blob.length, next_announce_time)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def completed_blobs(self, blob_hashes_to_check):
        blobs = yield defer.DeferredList([self.get_blob(b) for b in blob_hashes_to_check])
        blob_hashes = [b.blob_hash for success, b in blobs if success and b.verified]
        defer.returnValue(blob_hashes)

    @defer.inlineCallbacks
    def hashes_to_announce(self):
        hashes_to_announce = yield self.storage.get_blobs_to_announce()
        next_announce_time = self.get_next_announce_time(len(hashes_to_announce))
        yield self.storage.update_next_blob_announce(hashes_to_announce, next_announce_time)
        defer.returnValue(hashes_to_announce)

    @defer.inlineCallbacks
    def creator_finished(self, blob_creator):
        log.debug("creator %s finished (%s)", blob_creator.blob_hash, str(type(blob_creator)))
        assert blob_creator.blob_hash is not None
        assert blob_creator.blob_hash not in self.blobs
        assert blob_creator.length is not None
        self._make_new_blob(blob_creator, blob_creator.blob_hash,
                                          blob_creator.length)
        self._immediate_announce([blob_creator.blob_hash])
        next_announce_time = self.get_next_announce_time()
        yield self.blob_completed(self.blobs[blob_creator.blob_hash], next_announce_time)
        defer.returnValue(None)

    def delete_blob(self, blob_hash):
        if not blob_hash in self.blob_hashes_to_delete:
            self.blob_hashes_to_delete[blob_hash] = False
        return defer.succeed(None)

    @defer.inlineCallbacks
    def delete_blobs(self, blob_hashes):
        for blob_hash in blob_hashes:
            yield self.delete_blob(blob_hash)
        yield self._delete_blobs_marked_for_deletion()

    @defer.inlineCallbacks
    def get_all_verified_blobs(self):
        blob_hashes = yield self.storage.get_all_verified_blob_hashes(self.blob_dir)
        blobs = yield self.completed_blobs(blob_hashes)
        defer.returnValue(blobs)

    @defer.inlineCallbacks
    def add_blob_to_download_history(self, blob_hash, host, rate):
        yield self.storage.add_blob_to_download_history(blob_hash, host, rate)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def add_blob_to_upload_history(self, blob_hash, host, rate):
        yield self.storage.add_blob_to_upload_history(blob_hash, host, rate)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def immediate_announce_all_blobs(self):
        verified_hashes = yield self.storage.get_all_verified_blob_hashes(self.blob_dir)
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
            yield self.storage.delete_blob(blob_hash)
            log.debug("Deleted blob %s", blob_hash)
        except Exception as err:
            log.warning("Failed to delete blob %s. Reason: %s",
                        str(blob_hash), str(type(err)))
            self.blob_hashes_to_delete[blob_hash] = False
        defer.returnValue(None)

    @defer.inlineCallbacks
    def _delete_blobs_marked_for_deletion(self):
        for blob_hash, being_deleted in self.blob_hashes_to_delete.items():
            if being_deleted is False:
                yield self._delete_blob(blob_hash)

    def _make_new_blob(self, creator, blob_hash, length=None):
        log.debug("Make new blob: %s %s", blob_hash, length)
        assert blob_hash not in self.blobs
        blob = self._new_blob(creator, blob_hash, length)
        self.blobs[blob_hash] = blob

    # TODO: change this; its breaks the encapsulation of the
    #       blob. Maybe better would be to have the blob_creator
    #       produce a blob.

    def _new_blob(self, creator, blob_hash, length=None):
        if self.blob_type is BlobFile:
            new_blob = self.blob_type(self.blob_dir, blob_hash, length)
        else:
            new_blob = self.blob_type(blob_hash, length)
            new_blob.data_buffer = creator.data_buffer
        return new_blob
