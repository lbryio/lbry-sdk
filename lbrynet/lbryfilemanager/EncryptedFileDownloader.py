"""
Download LBRY Files from LBRYnet and save them to disk.
"""
import random
import logging

from zope.interface import implements
from twisted.internet import defer

from lbrynet.core.client.StreamProgressManager import FullStreamProgressManager
from lbrynet.core.StreamDescriptor import StreamMetadata
from lbrynet.lbryfile.client.EncryptedFileDownloader import EncryptedFileSaver
from lbrynet.lbryfile.client.EncryptedFileDownloader import EncryptedFileDownloader
from lbrynet.lbryfilemanager.EncryptedFileStatusReport import EncryptedFileStatusReport
from lbrynet.interfaces import IStreamDownloaderFactory
from lbrynet.lbryfile.StreamDescriptor import save_sd_info
from lbrynet.reflector import reupload
from lbrynet.conf import settings

log = logging.getLogger(__name__)


class ManagedEncryptedFileDownloader(EncryptedFileSaver):
    STATUS_RUNNING = "running"
    STATUS_STOPPED = "stopped"
    STATUS_FINISHED = "finished"

    def __init__(self, rowid, stream_hash, peer_finder, rate_limiter,
                 blob_manager, stream_info_manager, lbry_file_manager,
                 payment_rate_manager, wallet, download_directory,
                 upload_allowed, file_name=None):
        EncryptedFileSaver.__init__(self, stream_hash, peer_finder,
                                    rate_limiter, blob_manager,
                                    stream_info_manager,
                                    payment_rate_manager, wallet,
                                    download_directory,
                                    upload_allowed, file_name)
        self.sd_hash = None
        self.txid = None
        self.nout = None
        self.uri = None
        self.claim_id = None
        self.rowid = rowid
        self.lbry_file_manager = lbry_file_manager
        self.saving_status = False

    def restore(self):
        d = self.stream_info_manager._get_sd_blob_hashes_for_stream(self.stream_hash)

        def _save_stream_info(sd_hash):
            if sd_hash:
                self.sd_hash = sd_hash[0]
                d = self.wallet.get_claim_metadata_for_sd_hash(self.sd_hash)
                d.addCallback(lambda r: _save_claim(r[0], r[1], r[2]))
                return d
            else:
                return None

        def _save_claim_id(claim_id):
            self.claim_id = claim_id
            return defer.succeed(None)

        def _notify_bad_claim(name, txid, nout):
            err_msg = "Error loading name claim for lbry file: \
                       lbry://%s, tx %s output %i does not contain a valid claim, deleting it"
            log.error(err_msg, name, txid, nout)
            return self.lbry_file_manager.delete_lbry_file(self)

        def _save_claim(name, txid, nout):
            self.uri = name
            self.txid = txid
            self.nout = nout
            d = self.wallet.get_claimid(name, txid, nout)
            d.addCallbacks(_save_claim_id, lambda err: _notify_bad_claim(name, txid, nout))
            return d

        d.addCallback(_save_stream_info)
        d.addCallback(lambda _: self._reupload())
        d.addCallback(lambda _: self.lbry_file_manager.get_lbry_file_status(self))

        def restore_status(status):
            if status == ManagedEncryptedFileDownloader.STATUS_RUNNING:
                return self.start()
            elif status == ManagedEncryptedFileDownloader.STATUS_STOPPED:
                return defer.succeed(False)
            elif status == ManagedEncryptedFileDownloader.STATUS_FINISHED:
                self.completed = True
                return defer.succeed(True)

        d.addCallback(restore_status)
        return d

    def _reupload(self):
        if not settings.reflector_reupload:
            return
        reflector_server = random.choice(settings.reflector_servers)
        return reupload.check_and_restore_availability(self, reflector_server)

    def stop(self, err=None, change_status=True):

        def set_saving_status_done():
            self.saving_status = False

        # EncryptedFileSaver deletes metadata when it's stopped. We don't want that here.
        d = EncryptedFileDownloader.stop(self, err=err)
        if change_status is True:
            self.saving_status = True
            d.addCallback(lambda _: self._save_status())
            d.addCallback(lambda _: set_saving_status_done())
        return d

    def status(self):
        def find_completed_blobhashes(blobs):
            blobhashes = [b[0] for b in blobs if b[0] is not None]

            def get_num_completed(completed_blobs):
                return len(completed_blobs), len(blobhashes)

            inner_d = self.blob_manager.completed_blobs(blobhashes)
            inner_d.addCallback(get_num_completed)
            return inner_d

        def make_full_status(progress):
            num_completed = progress[0]
            num_known = progress[1]
            if self.completed is True:
                s = "completed"
            elif self.stopped is True:
                s = "stopped"
            else:
                s = "running"
            status = EncryptedFileStatusReport(self.file_name, num_completed, num_known, s)
            return status

        d = self.stream_info_manager.get_blobs_for_stream(self.stream_hash)
        d.addCallback(find_completed_blobhashes)
        d.addCallback(make_full_status)
        return d

    def _start(self):

        d = EncryptedFileSaver._start(self)
        d.addCallback(
            lambda _: self.stream_info_manager.get_sd_blob_hashes_for_stream(self.stream_hash))

        def _save_sd_hash(sd_hash):
            if len(sd_hash):
                self.sd_hash = sd_hash[0]
                d = self.wallet.get_claim_metadata_for_sd_hash(self.sd_hash)
            else:
                d = defer.succeed(None)

            return d

        def _save_claim(name, txid, nout):
            self.uri = name
            self.txid = txid
            self.nout = nout
            return defer.succeed(None)

        d.addCallback(_save_sd_hash)
        d.addCallback(lambda r: _save_claim(r[0], r[1], r[2]) if r else None)
        d.addCallback(lambda _: self._save_status())

        return d

    def _get_finished_deferred_callback_value(self):
        if self.completed is True:
            return "Download successful"
        else:
            return "Download stopped"

    def _save_status(self):
        if self.completed is True:
            s = ManagedEncryptedFileDownloader.STATUS_FINISHED
        elif self.stopped is True:
            s = ManagedEncryptedFileDownloader.STATUS_STOPPED
        else:
            s = ManagedEncryptedFileDownloader.STATUS_RUNNING
        return self.lbry_file_manager.change_lbry_file_status(self, s)

    def _get_progress_manager(self, download_manager):
        return FullStreamProgressManager(self._finished_downloading,
                                         self.blob_manager, download_manager)


class ManagedEncryptedFileDownloaderFactory(object):
    implements(IStreamDownloaderFactory)

    def __init__(self, lbry_file_manager):
        self.lbry_file_manager = lbry_file_manager

    def can_download(self, sd_validator):
        return True

    def make_downloader(self, metadata, options, payment_rate_manager,
                        download_directory=None, file_name=None):
        data_rate = options[0]
        upload_allowed = options[1]

        def save_source_if_blob(stream_hash):
            if metadata.metadata_source == StreamMetadata.FROM_BLOB:
                # TODO: should never have to dig this deep into a another classes
                #       members. lbry_file_manager should have a
                #       save_sd_blob_hash_to_stream method
                d = self.lbry_file_manager.stream_info_manager.save_sd_blob_hash_to_stream(
                    stream_hash, metadata.source_blob_hash)
            else:
                d = defer.succeed(True)
            d.addCallback(lambda _: stream_hash)
            return d

        d = save_sd_info(self.lbry_file_manager.stream_info_manager, metadata.validator.raw_info)
        d.addCallback(save_source_if_blob)
        d.addCallback(lambda stream_hash: self.lbry_file_manager.add_lbry_file(
            stream_hash,
            payment_rate_manager,
            data_rate,
            upload_allowed,
            download_directory=download_directory,
            file_name=file_name))
        return d

    @staticmethod
    def get_description():
        return "Save the file to disk"
