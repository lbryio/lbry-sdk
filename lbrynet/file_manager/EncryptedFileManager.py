"""
Keep track of which LBRY Files are downloading and store their LBRY File specific metadata
"""

import logging
import os

from twisted.internet import defer, task, reactor
from twisted.python.failure import Failure

from lbrynet.reflector.reupload import reflect_stream
from lbrynet.core.PaymentRateManager import NegotiatedPaymentRateManager
from lbrynet.file_manager.EncryptedFileDownloader import ManagedEncryptedFileDownloader
from lbrynet.file_manager.EncryptedFileDownloader import ManagedEncryptedFileDownloaderFactory
from lbrynet.lbry_file.StreamDescriptor import EncryptedFileStreamType
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

    def __init__(self, session, stream_info_manager, sd_identifier, download_directory=None):

        self.auto_re_reflect = conf.settings['auto_re_reflect']
        self.auto_re_reflect_interval = conf.settings['auto_re_reflect_interval']
        self.session = session
        self.stream_info_manager = stream_info_manager
        # TODO: why is sd_identifier part of the file manager?
        self.sd_identifier = sd_identifier
        self.lbry_files = []
        if download_directory:
            self.download_directory = download_directory
        else:
            self.download_directory = os.getcwd()
        self.lbry_file_reflector = task.LoopingCall(self.reflect_lbry_files)
        log.debug("Download directory for EncryptedFileManager: %s", str(self.download_directory))

    @defer.inlineCallbacks
    def setup(self):
        yield self.stream_info_manager.setup()
        yield self._add_to_sd_identifier()
        yield self._start_lbry_files()
        log.info("Started file manager")

    def get_lbry_file_status(self, lbry_file):
        return self._get_lbry_file_status(lbry_file.rowid)

    def set_lbry_file_data_payment_rate(self, lbry_file, new_rate):
        return self._set_lbry_file_payment_rate(lbry_file.rowid, new_rate)

    def change_lbry_file_status(self, lbry_file, status):
        log.debug("Changing status of %s to %s", lbry_file.stream_hash, status)
        return self._change_file_status(lbry_file.rowid, status)

    def get_lbry_file_status_reports(self):
        ds = []

        for lbry_file in self.lbry_files:
            ds.append(lbry_file.status())

        dl = defer.DeferredList(ds)

        def filter_failures(status_reports):
            return [status_report for success, status_report in status_reports if success is True]

        dl.addCallback(filter_failures)
        return dl

    def save_sd_blob_hash_to_stream(self, stream_hash, sd_hash):
        return self.stream_info_manager.save_sd_blob_hash_to_stream(stream_hash, sd_hash)

    def _add_to_sd_identifier(self):
        downloader_factory = ManagedEncryptedFileDownloaderFactory(self)
        self.sd_identifier.add_stream_downloader_factory(
            EncryptedFileStreamType, downloader_factory)

    @defer.inlineCallbacks
    def _start_lbry_files(self):
        files_and_options = yield self._get_all_lbry_files()
        stream_infos = yield self.stream_info_manager._get_all_stream_infos()
        b_prm = self.session.base_payment_rate_manager
        payment_rate_manager = NegotiatedPaymentRateManager(b_prm, self.session.blob_tracker)
        log.info("Trying to start %i files", len(stream_infos))
        for i, (rowid, stream_hash, blob_data_rate, status) in enumerate(files_and_options):
            if len(files_and_options) > 500 and i % 500 == 0:
                log.info("Started %i/%i files", i, len(stream_infos))
            if stream_hash in stream_infos:
                if stream_infos[stream_hash]['suggested_file_name']:
                    file_name = os.path.basename(stream_infos[stream_hash]['suggested_file_name'])
                else:
                    file_name = os.path.basename(stream_infos[stream_hash]['stream_name'])

                lbry_file = ManagedEncryptedFileDownloader(
                    rowid,
                    stream_hash,
                    self.session.peer_finder,
                    self.session.rate_limiter,
                    self.session.blob_manager,
                    self.stream_info_manager,
                    self,
                    payment_rate_manager,
                    self.session.wallet,
                    self.download_directory,
                    file_name=file_name,
                    sd_hash=stream_infos[stream_hash]['sd_hash'],
                    key=stream_infos[stream_hash]['key'],
                    stream_name=stream_infos[stream_hash]['stream_name'],
                    suggested_file_name=stream_infos[stream_hash]['suggested_file_name']
                )
                try:
                    # restore will raise an Exception if status is unknown
                    lbry_file.restore(status)
                except Exception:
                    log.warning("Failed to start %i", rowid)
                    continue
                self.lbry_files.append(lbry_file)
        log.info("Started %i lbry files", len(self.lbry_files))
        if self.auto_re_reflect is True:
            safe_start_looping_call(self.lbry_file_reflector, self.auto_re_reflect_interval)

    @defer.inlineCallbacks
    def start_lbry_file(self, rowid, stream_hash,
                        payment_rate_manager, blob_data_rate=None,
                        download_directory=None, file_name=None):
        if not download_directory:
            download_directory = self.download_directory
        payment_rate_manager.min_blob_data_payment_rate = blob_data_rate
        lbry_file_downloader = ManagedEncryptedFileDownloader(
            rowid,
            stream_hash,
            self.session.peer_finder,
            self.session.rate_limiter,
            self.session.blob_manager,
            self.stream_info_manager,
            self,
            payment_rate_manager,
            self.session.wallet,
            download_directory,
            file_name=file_name
        )
        yield lbry_file_downloader.set_stream_info()
        self.lbry_files.append(lbry_file_downloader)
        defer.returnValue(lbry_file_downloader)

    @defer.inlineCallbacks
    def _stop_lbry_file(self, lbry_file):
        def wait_for_finished(lbry_file, count=2):
            if count or lbry_file.saving_status is not False:
                return task.deferLater(reactor, 1, self._stop_lbry_file, lbry_file, count=count - 1)
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
    def add_lbry_file(self, stream_hash, payment_rate_manager=None, blob_data_rate=None,
                      download_directory=None, file_name=None):
        if not payment_rate_manager:
            payment_rate_manager = self.session.payment_rate_manager
        rowid = yield self._save_lbry_file(stream_hash, blob_data_rate)
        lbry_file = yield self.start_lbry_file(rowid, stream_hash, payment_rate_manager,
                                               blob_data_rate, download_directory,
                                               file_name)
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

        yield self._delete_lbry_file_options(lbry_file.rowid)

        yield lbry_file.delete_data()

        # TODO: delete this
        # get count for stream hash returns the count of the lbry files with the stream hash
        # in the lbry_file_options table, which will soon be removed.

        stream_count = yield self.get_count_for_stream_hash(lbry_file.stream_hash)
        if stream_count == 0:
            yield self.stream_info_manager.delete_stream(lbry_file.stream_hash)
        else:
            msg = ("Can't delete stream info for %s, count is %i\n"
                   "The call that resulted in this warning will\n"
                   "be removed in the database refactor")
            log.warning(msg, lbry_file.stream_hash, stream_count)

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

    def get_count_for_stream_hash(self, stream_hash):
        return self._get_count_for_stream_hash(stream_hash)

    def _get_count_for_stream_hash(self, stream_hash):
        return self.stream_info_manager._get_count_for_stream_hash(stream_hash)

    def _delete_lbry_file_options(self, rowid):
        return self.stream_info_manager._delete_lbry_file_options(rowid)

    def _save_lbry_file(self, stream_hash, data_payment_rate):
        return self.stream_info_manager._save_lbry_file(stream_hash, data_payment_rate)

    def _get_all_lbry_files(self):
        return self.stream_info_manager._get_all_lbry_files()

    def _get_rowid_for_stream_hash(self, stream_hash):
        return self.stream_info_manager._get_rowid_for_stream_hash(stream_hash)

    def _change_file_status(self, rowid, status):
        return self.stream_info_manager._change_file_status(rowid, status)

    def _set_lbry_file_payment_rate(self, rowid, new_rate):
        return self.stream_info_manager._set_lbry_file_payment_rate(rowid, new_rate)

    def _get_lbry_file_status(self, rowid):
        return self.stream_info_manager._get_lbry_file_status(rowid)
