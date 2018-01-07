"""
Download LBRY Files from LBRYnet and save them to disk.
"""
import logging

from zope.interface import implements
from twisted.internet import defer

from lbrynet.core.client.StreamProgressManager import FullStreamProgressManager
from lbrynet.core.utils import short_hash
from lbrynet.core.StreamDescriptor import StreamMetadata
from lbrynet.lbry_file.client.EncryptedFileDownloader import EncryptedFileSaver
from lbrynet.lbry_file.client.EncryptedFileDownloader import EncryptedFileDownloader
from lbrynet.file_manager.EncryptedFileStatusReport import EncryptedFileStatusReport
from lbrynet.interfaces import IStreamDownloaderFactory
from lbrynet.lbry_file.StreamDescriptor import save_sd_info

log = logging.getLogger(__name__)


def log_status(sd_hash, status):
    if status == ManagedEncryptedFileDownloader.STATUS_RUNNING:
        status_string = "running"
    elif status == ManagedEncryptedFileDownloader.STATUS_STOPPED:
        status_string = "stopped"
    elif status == ManagedEncryptedFileDownloader.STATUS_FINISHED:
        status_string = "finished"
    else:
        status_string = "unknown"
    log.debug("stream %s is %s", short_hash(sd_hash), status_string)


class ManagedEncryptedFileDownloader(EncryptedFileSaver):
    STATUS_RUNNING = "running"
    STATUS_STOPPED = "stopped"
    STATUS_FINISHED = "finished"

    def __init__(self, rowid, stream_hash, peer_finder, rate_limiter, blob_manager,
                 stream_info_manager, lbry_file_manager, payment_rate_manager, wallet,
                 download_directory, sd_hash=None, key=None, stream_name=None,
                 suggested_file_name=None):
        EncryptedFileSaver.__init__(self, stream_hash, peer_finder,
                                    rate_limiter, blob_manager,
                                    stream_info_manager,
                                    payment_rate_manager, wallet,
                                    download_directory, key, stream_name, suggested_file_name)
        self.sd_hash = sd_hash
        self.rowid = rowid
        self.lbry_file_manager = lbry_file_manager
        self._saving_status = False

    @property
    def saving_status(self):
        return self._saving_status

    def restore(self, status):
        if status == ManagedEncryptedFileDownloader.STATUS_RUNNING:
            # start returns self.finished_deferred
            # which fires when we've finished downloading the file
            # and we don't want to wait for the entire download
            self.start()
        elif status == ManagedEncryptedFileDownloader.STATUS_STOPPED:
            pass
        elif status == ManagedEncryptedFileDownloader.STATUS_FINISHED:
            self.completed = True
        else:
            raise Exception("Unknown status for stream %s: %s" % (self.stream_hash, status))

    @defer.inlineCallbacks
    def stop(self, err=None, change_status=True):
        log.debug('Stopping download for stream %s', short_hash(self.stream_hash))
        # EncryptedFileSaver deletes metadata when it's stopped. We don't want that here.
        yield EncryptedFileDownloader.stop(self, err=err)
        if change_status is True:
            status = yield self._save_status()
        defer.returnValue(status)

    @defer.inlineCallbacks
    def status(self):
        blobs = yield self.stream_info_manager.get_blobs_for_stream(self.stream_hash)
        blob_hashes = [b[0] for b in blobs if b[0] is not None]
        completed_blobs = yield self.blob_manager.completed_blobs(blob_hashes)
        num_blobs_completed = len(completed_blobs)
        num_blobs_known = len(blob_hashes)

        if self.completed:
            status = "completed"
        elif self.stopped:
            status = "stopped"
        else:
            status = "running"
        defer.returnValue(EncryptedFileStatusReport(self.file_name, num_blobs_completed,
                                                    num_blobs_known, status))

    @defer.inlineCallbacks
    def _start(self):
        yield EncryptedFileSaver._start(self)
        status = yield self._save_status()
        log_status(self.sd_hash, status)
        defer.returnValue(status)

    def _get_finished_deferred_callback_value(self):
        if self.completed is True:
            return "Download successful"
        else:
            return "Download stopped"

    @defer.inlineCallbacks
    def _save_status(self):
        self._saving_status = True
        if self.completed is True:
            status = ManagedEncryptedFileDownloader.STATUS_FINISHED
        elif self.stopped is True:
            status = ManagedEncryptedFileDownloader.STATUS_STOPPED
        else:
            status = ManagedEncryptedFileDownloader.STATUS_RUNNING
        status = yield self.lbry_file_manager.change_lbry_file_status(self, status)
        self._saving_status = False
        defer.returnValue(status)

    def save_status(self):
        return self._save_status()

    def _get_progress_manager(self, download_manager):
        return FullStreamProgressManager(self._finished_downloading,
                                         self.blob_manager, download_manager)


class ManagedEncryptedFileDownloaderFactory(object):
    implements(IStreamDownloaderFactory)

    def __init__(self, lbry_file_manager):
        self.lbry_file_manager = lbry_file_manager

    def can_download(self, sd_validator):
        # TODO: add a sd_validator for non live streams, use it
        return True

    @defer.inlineCallbacks
    def make_downloader(self, metadata, options, payment_rate_manager, download_directory=None):
        assert len(options) == 1
        data_rate = options[0]
        stream_hash = yield save_sd_info(self.lbry_file_manager.stream_info_manager,
                                         metadata.validator.raw_info)
        if metadata.metadata_source == StreamMetadata.FROM_BLOB:
            yield self.lbry_file_manager.save_sd_blob_hash_to_stream(stream_hash,
                                                                     metadata.source_blob_hash)
        lbry_file = yield self.lbry_file_manager.add_lbry_file(stream_hash,
                                                               metadata.source_blob_hash,
                                                               payment_rate_manager,
                                                               data_rate,
                                                               download_directory)
        defer.returnValue(lbry_file)

    @staticmethod
    def get_description():
        return "Save the file to disk"
