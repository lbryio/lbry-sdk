"""
Download LBRY Files from LBRYnet and save them to disk.
"""

from zope.interface import implements
from lbrynet.core.client.StreamProgressManager import FullStreamProgressManager
from lbrynet.core.StreamDescriptor import StreamMetadata
from lbrynet.lbryfile.client.LBRYFileDownloader import LBRYFileSaver, LBRYFileDownloader
from lbrynet.lbryfilemanager.LBRYFileStatusReport import LBRYFileStatusReport
from lbrynet.interfaces import IStreamDownloaderFactory
from lbrynet.lbryfile.StreamDescriptor import save_sd_info
from twisted.internet import defer


class ManagedLBRYFileDownloader(LBRYFileSaver):

    STATUS_RUNNING = "running"
    STATUS_STOPPED = "stopped"
    STATUS_FINISHED = "finished"

    def __init__(self, rowid, stream_hash, peer_finder, rate_limiter, blob_manager, stream_info_manager,
                 lbry_file_manager, payment_rate_manager, wallet, download_directory, upload_allowed,
                 file_name=None):
        LBRYFileSaver.__init__(self, stream_hash, peer_finder, rate_limiter, blob_manager,
                               stream_info_manager, payment_rate_manager, wallet, download_directory,
                               upload_allowed, file_name)
        self.sd_hash = None
        self.rowid = rowid
        self.lbry_file_manager = lbry_file_manager
        self.saving_status = False

    def restore(self):
        d = self.stream_info_manager._get_sd_blob_hashes_for_stream(self.stream_hash)

        def _save_sd_hash(sd_hash):
            if len(sd_hash):
                self.sd_hash = sd_hash[0]
            return defer.succeed(None)

        d.addCallback(_save_sd_hash)

        d.addCallback(lambda _: self.lbry_file_manager.get_lbry_file_status(self))

        def restore_status(status):
            if status == ManagedLBRYFileDownloader.STATUS_RUNNING:
                return self.start()
            elif status == ManagedLBRYFileDownloader.STATUS_STOPPED:
                return defer.succeed(False)
            elif status == ManagedLBRYFileDownloader.STATUS_FINISHED:
                self.completed = True
                return defer.succeed(True)

        d.addCallback(restore_status)
        return d

    def stop(self, err=None, change_status=True):

        def set_saving_status_done():
            self.saving_status = False

        d = LBRYFileDownloader.stop(self, err=err)  # LBRYFileSaver deletes metadata when it's stopped. We don't want that here.
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
            status = LBRYFileStatusReport(self.file_name, num_completed, num_known, s)
            return status

        d = self.stream_info_manager.get_blobs_for_stream(self.stream_hash)
        d.addCallback(find_completed_blobhashes)
        d.addCallback(make_full_status)
        return d

    def _start(self):

        d = LBRYFileSaver._start(self)

        d.addCallback(lambda _: self.stream_info_manager._get_sd_blob_hashes_for_stream(self.stream_hash))

        def _save_sd_hash(sd_hash):
            self.sd_hash = sd_hash[0]
            return defer.succeed(None)

        d.addCallback(_save_sd_hash)

        d.addCallback(lambda _: self._save_status())

        return d

    def _get_finished_deferred_callback_value(self):
        if self.completed is True:
            return "Download successful"
        else:
            return "Download stopped"

    def _save_status(self):
        if self.completed is True:
            s = ManagedLBRYFileDownloader.STATUS_FINISHED
        elif self.stopped is True:
            s = ManagedLBRYFileDownloader.STATUS_STOPPED
        else:
            s = ManagedLBRYFileDownloader.STATUS_RUNNING
        return self.lbry_file_manager.change_lbry_file_status(self, s)

    def _get_progress_manager(self, download_manager):
        return FullStreamProgressManager(self._finished_downloading, self.blob_manager, download_manager)


class ManagedLBRYFileDownloaderFactory(object):
    implements(IStreamDownloaderFactory)

    def __init__(self, lbry_file_manager):
        self.lbry_file_manager = lbry_file_manager

    def can_download(self, sd_validator):
        return True

    def make_downloader(self, metadata, options, payment_rate_manager, download_directory=None, file_name=None):
        data_rate = options[0]
        upload_allowed = options[1]

        def save_source_if_blob(stream_hash):
            if metadata.metadata_source == StreamMetadata.FROM_BLOB:
                d = self.lbry_file_manager.stream_info_manager.save_sd_blob_hash_to_stream(stream_hash,
                                                                                           metadata.source_blob_hash)
            else:
                d = defer.succeed(True)
            d.addCallback(lambda _: stream_hash)
            return d

        d = save_sd_info(self.lbry_file_manager.stream_info_manager, metadata.validator.raw_info)
        d.addCallback(save_source_if_blob)
        d.addCallback(lambda stream_hash: self.lbry_file_manager.add_lbry_file(stream_hash,
                                                                               payment_rate_manager,
                                                                               data_rate,
                                                                               upload_allowed,
                                                                               download_directory=download_directory,
                                                                               file_name=file_name))
        return d

    @staticmethod
    def get_description():
        return "Save the file to disk"