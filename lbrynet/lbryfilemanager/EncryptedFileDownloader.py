"""
Download LBRY Files from LBRYnet and save them to disk.
"""
import logging

from zope.interface import implements
from twisted.internet import defer

from lbrynet.core.client.StreamProgressManager import FullStreamProgressManager
from lbrynet.core.utils import short_hash, get_sd_hash
from lbrynet.core.StreamDescriptor import StreamMetadata
from lbrynet.lbryfile.client.EncryptedFileDownloader import EncryptedFileSaver
from lbrynet.lbryfile.client.EncryptedFileDownloader import EncryptedFileDownloader
from lbrynet.lbryfilemanager.EncryptedFileStatusReport import EncryptedFileStatusReport
from lbrynet.interfaces import IStreamDownloaderFactory
from lbrynet.lbryfile.StreamDescriptor import save_sd_info

log = logging.getLogger(__name__)


class CLAIM_STATUS(object):
    INIT = "INIT"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    INVALID_METADATA = "INVALID_METADATA"
    MISSING_METADATA = "MISSING_METADATA"


def log_status(name, sd_hash, status):
    if status == ManagedEncryptedFileDownloader.STATUS_RUNNING:
        status_string = "running"
    elif status == ManagedEncryptedFileDownloader.STATUS_STOPPED:
        status_string = "stopped"
    elif status == ManagedEncryptedFileDownloader.STATUS_FINISHED:
        status_string = "finished"
    elif status == ManagedEncryptedFileDownloader.STATUS_STREAM_PENDING:
        status_string = "pending"
    else:
        status_string = "unknown"
    log.info("lbry://%s (%s) is %s",
             name,
             "unknown sd hash" if not sd_hash else short_hash(sd_hash),
             status_string)


class ManagedEncryptedFileDownloader(EncryptedFileSaver):
    STATUS_RUNNING = "running"
    STATUS_STOPPED = "stopped"
    STATUS_FINISHED = "finished"
    STATUS_STREAM_PENDING = "pending"

    def __init__(self, rowid, stream_hash, peer_finder, rate_limiter, blob_manager,
                 stream_info_manager, lbry_file_manager, payment_rate_manager, wallet,
                 download_directory, file_name=None):
        EncryptedFileSaver.__init__(self, stream_hash, peer_finder, rate_limiter, blob_manager,
                                    stream_info_manager, payment_rate_manager, wallet,
                                    download_directory, file_name)
        self.is_pending = True
        self.sd_hash = None
        self.txid = None
        self.nout = None
        self.outpoint = None
        self.name = None
        self.claim_id = None
        self.rowid = rowid
        self.lbry_file_manager = lbry_file_manager
        self._saving_status = False

    @property
    def saving_status(self):
        return self._saving_status

    @defer.inlineCallbacks
    def restore(self):
        yield self.load_file_attributes()

        status = yield self.lbry_file_manager.get_lbry_file_status(self)
        log_status(self.name, self.sd_hash, status)

        if status == ManagedEncryptedFileDownloader.STATUS_RUNNING:
            # start returns self.finished_deferred
            # which fires when we've finished downloading the file
            # and we don't want to wait for the entire download
            self.start()
        elif status == ManagedEncryptedFileDownloader.STATUS_STOPPED:
            defer.returnValue(False)
        elif status == ManagedEncryptedFileDownloader.STATUS_FINISHED:
            self.completed = True
            defer.returnValue(True)
        elif status == ManagedEncryptedFileDownloader.STATUS_STREAM_PENDING:
            self.is_pending = True
            defer.returnValue(True)
        else:
            raise Exception("Unknown status for stream %s: %s" % (self.stream_hash, status))

    @defer.inlineCallbacks
    def stop(self, err=None, change_status=True):
        log.info('Stopping download for %s', short_hash(self.sd_hash))
        # EncryptedFileSaver deletes metadata when it's stopped. We don't want that here.
        yield EncryptedFileDownloader.stop(self, err=err)
        if change_status is True:
            status = yield self.save_status()
        defer.returnValue(status)

    @defer.inlineCallbacks
    def status(self):
        blobs = yield self.stream_info_manager.get_blobs_for_stream(self.stream_hash)
        blob_hashes = [b[0] for b in blobs if b[0] is not None]
        completed_blobs = yield self.blob_manager.completed_blobs(blob_hashes)
        num_blobs_completed = len(completed_blobs)
        num_blobs_known = len(blob_hashes)
        status_code = yield self.lbry_file_manager.get_lbry_file_status(self)
        defer.returnValue(EncryptedFileStatusReport(self.file_name, num_blobs_completed,
                                                    num_blobs_known, status_code))

    @defer.inlineCallbacks
    def load_file_attributes(self):
        self.outpoint = yield self.lbry_file_manager.get_claim_metadata_for_file(self)
        if self.outpoint:
            self.txid, self.nout = self.outpoint.as_tuple
            self.claim_id = yield self.lbry_file_manager.get_claim_id_for_file(self)
            self.name = yield self.lbry_file_manager.get_lbry_name_for_file(self)
        else:
            log.warning("No claim information exists for %s", self)
            self.txid, self.nout, self.claim_id, self.name = None, None, None, None
        self.sd_hash = yield self.lbry_file_manager.get_sd_hash_for_file(self)
        claim_status = yield self.lbry_file_manager.get_claim_status_for_file(self)
        if claim_status == CLAIM_STATUS.MISSING_METADATA:
            try:
                claim_info = yield self.wallet.get_claim_info(self.name, self.txid, self.nout)
                metadata = claim_info['value']
                self.sd_hash = get_sd_hash(metadata)
                yield self.stream_info_manager.save_sd_blob_hash_to_stream(self.stream_hash,
                                                                           self.sd_hash)
            except Exception as err:
                log.warning("Failed to load claim info for %s: %s", self, err)

    @defer.inlineCallbacks
    def set_claim(self, name, txid, nout):
        yield self.wallet.get_claim_info(name, txid, nout)
        self.name, self.txid, self.nout = name, txid, nout
        yield self.lbry_file_manager.save_claim_to_file(self)
        self.claim_id = yield self.lbry_file_manager.get_claim_id_for_file(self)

    @defer.inlineCallbacks
    def _start(self):
        yield EncryptedFileSaver._start(self)
        yield self.load_file_attributes()
        status = yield self.save_status()
        log_status(self.name, self.sd_hash, status)
        defer.returnValue(status)

    def _get_finished_deferred_callback_value(self):
        if self.completed is True:
            return "Download successful"
        else:
            return "Download stopped"

    @defer.inlineCallbacks
    def save_status(self):
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
    def make_downloader(self, metadata, options, payment_rate_manager, download_directory=None,
                        file_name=None):
        assert len(options) == 1
        data_rate = options[0]
        stream_hash = yield save_sd_info(self.lbry_file_manager.stream_info_manager,
                                         metadata.validator.raw_info)
        if metadata.metadata_source == StreamMetadata.FROM_BLOB:
            yield self.lbry_file_manager.save_sd_blob_hash_to_stream(stream_hash,
                                                                     metadata.source_blob_hash)
        lbry_file = yield self.lbry_file_manager.add_lbry_file(stream_hash, payment_rate_manager,
                                                               data_rate,
                                                               download_directory, file_name)
        defer.returnValue(lbry_file)

    @staticmethod
    def get_description():
        return "Save the file to disk"
