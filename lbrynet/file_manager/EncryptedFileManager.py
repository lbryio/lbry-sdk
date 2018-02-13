"""
Keep track of which LBRY Files are downloading and store their LBRY File specific metadata
"""
import os
import logging

from twisted.internet import defer, task, reactor
from twisted.python.failure import Failure

from lbrynet.reflector.reupload import reflect_stream
from lbrynet.core.PaymentRateManager import NegotiatedPaymentRateManager
from lbrynet.file_manager.EncryptedFileDownloader import ManagedEncryptedFileDownloader
from lbrynet.file_manager.EncryptedFileDownloader import ManagedEncryptedFileDownloaderFactory
from lbrynet.core.StreamDescriptor import EncryptedFileStreamType, get_sd_info
from lbrynet.cryptstream.client.CryptStreamDownloader import AlreadyStoppedError
from lbrynet.cryptstream.client.CryptStreamDownloader import CurrentlyStoppingError
from lbrynet.core.utils import safe_start_looping_call, safe_stop_looping_call
from lbrynet import conf


log = logging.getLogger(__name__)


class EncryptedFileManager(object):
    """
    Keeps track of currently opened LBRY Files, their options, and
    their LBRY File specific metadata.
    """
    # when reflecting files, reflect up to this many files at a time
    CONCURRENT_REFLECTS = 5

    def __init__(self, session, sd_identifier):

        self.auto_re_reflect = conf.settings['reflect_uploads']
        self.auto_re_reflect_interval = conf.settings['auto_re_reflect_interval']
        self.session = session
        self.storage = session.storage
        # TODO: why is sd_identifier part of the file manager?
        self.sd_identifier = sd_identifier
        assert sd_identifier
        self.lbry_files = []
        self.lbry_file_reflector = task.LoopingCall(self.reflect_lbry_files)

    @defer.inlineCallbacks
    def setup(self):
        yield self._add_to_sd_identifier()
        yield self._start_lbry_files()
        log.info("Started file manager")

    def get_lbry_file_status(self, lbry_file):
        return self.session.storage.get_lbry_file_status(lbry_file.rowid)

    def set_lbry_file_data_payment_rate(self, lbry_file, new_rate):
        return self.session.storage(lbry_file.rowid, new_rate)

    def change_lbry_file_status(self, lbry_file, status):
        log.debug("Changing status of %s to %s", lbry_file.stream_hash, status)
        return self.session.storage.change_file_status(lbry_file.rowid, status)

    def get_lbry_file_status_reports(self):
        ds = []

        for lbry_file in self.lbry_files:
            ds.append(lbry_file.status())

        dl = defer.DeferredList(ds)

        def filter_failures(status_reports):
            return [status_report for success, status_report in status_reports if success is True]

        dl.addCallback(filter_failures)
        return dl

    def _add_to_sd_identifier(self):
        downloader_factory = ManagedEncryptedFileDownloaderFactory(self)
        self.sd_identifier.add_stream_downloader_factory(
            EncryptedFileStreamType, downloader_factory)

    def _get_lbry_file(self, rowid, stream_hash, payment_rate_manager, sd_hash, key,
                       stream_name, file_name, download_directory, suggested_file_name):
        return ManagedEncryptedFileDownloader(
            rowid,
            stream_hash,
            self.session.peer_finder,
            self.session.rate_limiter,
            self.session.blob_manager,
            self.session.storage,
            self,
            payment_rate_manager,
            self.session.wallet,
            download_directory,
            file_name,
            stream_name=stream_name,
            sd_hash=sd_hash,
            key=key,
            suggested_file_name=suggested_file_name
        )

    @defer.inlineCallbacks
    def _start_lbry_files(self):
        files = yield self.session.storage.get_all_lbry_files()
        b_prm = self.session.base_payment_rate_manager
        payment_rate_manager = NegotiatedPaymentRateManager(b_prm, self.session.blob_tracker)

        log.info("Trying to start %i files", len(files))
        for i, file_info in enumerate(files):
            if len(files) > 500 and i % 500 == 0:
                log.info("Started %i/%i files", i, len(files))

            lbry_file = self._get_lbry_file(
                file_info['row_id'], file_info['stream_hash'], payment_rate_manager, file_info['sd_hash'],
                file_info['key'], file_info['stream_name'], file_info['file_name'], file_info['download_directory'],
                file_info['suggested_file_name']
            )
            yield lbry_file.get_claim_info()
            try:
                # restore will raise an Exception if status is unknown
                lbry_file.restore(file_info['status'])
                self.lbry_files.append(lbry_file)
            except Exception:
                log.warning("Failed to start %i", file_info['rowid'])
                continue
        log.info("Started %i lbry files", len(self.lbry_files))
        if self.auto_re_reflect is True:
            safe_start_looping_call(self.lbry_file_reflector, self.auto_re_reflect_interval)

    @defer.inlineCallbacks
    def _stop_lbry_file(self, lbry_file):
        def wait_for_finished(lbry_file, count=2):
            if count or lbry_file.saving_status is not False:
                return task.deferLater(reactor, 1, self._stop_lbry_file, lbry_file,
                                       count=count - 1)
        try:
            yield lbry_file.stop(change_status=False)
            self.lbry_files.remove(lbry_file)
        except CurrentlyStoppingError:
            yield wait_for_finished(lbry_file)
        except AlreadyStoppedError:
            pass
        finally:
            defer.returnValue(None)

    def _stop_lbry_files(self):
        log.info("Stopping %i lbry files", len(self.lbry_files))
        lbry_files = self.lbry_files
        for lbry_file in lbry_files:
            yield self._stop_lbry_file(lbry_file)

    @defer.inlineCallbacks
    def add_published_file(self, stream_hash, sd_hash, download_directory, payment_rate_manager, blob_data_rate):
        status = ManagedEncryptedFileDownloader.STATUS_FINISHED
        stream_metadata = yield get_sd_info(self.session.storage, stream_hash, include_blobs=False)
        key = stream_metadata['key']
        stream_name = stream_metadata['stream_name']
        file_name = stream_metadata['suggested_file_name']
        rowid = yield self.storage.save_published_file(
            stream_hash, file_name, download_directory, blob_data_rate, status
        )
        lbry_file = self._get_lbry_file(
            rowid, stream_hash, payment_rate_manager, sd_hash, key, stream_name, file_name, download_directory,
            stream_metadata['suggested_file_name']
        )
        lbry_file.restore(status)
        self.lbry_files.append(lbry_file)
        defer.returnValue(lbry_file)

    @defer.inlineCallbacks
    def add_downloaded_file(self, stream_hash, sd_hash, download_directory, payment_rate_manager=None,
                            blob_data_rate=None, status=None, file_name=None):
        status = status or ManagedEncryptedFileDownloader.STATUS_STOPPED
        payment_rate_manager = payment_rate_manager or self.session.payment_rate_manager
        blob_data_rate = blob_data_rate or payment_rate_manager.min_blob_data_payment_rate
        stream_metadata = yield get_sd_info(self.session.storage, stream_hash, include_blobs=False)
        key = stream_metadata['key']
        stream_name = stream_metadata['stream_name']
        file_name = file_name or stream_metadata['suggested_file_name']

        # when we save the file we'll atomic touch the nearest file to the suggested file name
        # that doesn't yet exist in the download directory
        rowid = yield self.storage.save_downloaded_file(
            stream_hash, os.path.basename(file_name.decode('hex')).encode('hex'), download_directory, blob_data_rate
        )
        file_name = yield self.session.storage.get_filename_for_rowid(rowid)
        lbry_file = self._get_lbry_file(
            rowid, stream_hash, payment_rate_manager, sd_hash, key, stream_name, file_name, download_directory,
            stream_metadata['suggested_file_name']
        )
        lbry_file.get_claim_info(include_supports=False)
        lbry_file.restore(status)
        self.lbry_files.append(lbry_file)
        defer.returnValue(lbry_file)

    @defer.inlineCallbacks
    def delete_lbry_file(self, lbry_file, delete_file=False):
        if lbry_file not in self.lbry_files:
            raise ValueError("Could not find that LBRY file")

        def wait_for_finished(count=2):
            if count <= 0 or lbry_file.saving_status is False:
                return True
            else:
                return task.deferLater(reactor, 1, wait_for_finished, count=count - 1)

        full_path = os.path.join(lbry_file.download_directory, lbry_file.file_name)

        try:
            yield lbry_file.stop()
        except (AlreadyStoppedError, CurrentlyStoppingError):
            yield wait_for_finished()

        self.lbry_files.remove(lbry_file)

        yield lbry_file.delete_data()
        yield self.session.storage.delete_stream(lbry_file.stream_hash)

        if delete_file and os.path.isfile(full_path):
            os.remove(full_path)

        defer.returnValue(True)

    def toggle_lbry_file_running(self, lbry_file):
        """Toggle whether a stream reader is currently running"""
        for l in self.lbry_files:
            if l == lbry_file:
                return l.toggle_running()
        return defer.fail(Failure(ValueError("Could not find that LBRY file")))

    @defer.inlineCallbacks
    def reflect_lbry_files(self):
        sem = defer.DeferredSemaphore(self.CONCURRENT_REFLECTS)
        ds = []
        for lbry_file in self.lbry_files:
            ds.append(sem.run(reflect_stream, lbry_file))
        yield defer.DeferredList(ds)

    @defer.inlineCallbacks
    def stop(self):
        safe_stop_looping_call(self.lbry_file_reflector)
        yield defer.DeferredList(list(self._stop_lbry_files()))
        log.info("Stopped encrypted file manager")
        defer.returnValue(True)
