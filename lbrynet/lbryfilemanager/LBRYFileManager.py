"""
Keep track of which LBRY Files are downloading and store their LBRY File specific metadata
"""

import logging

from twisted.enterprise import adbapi

import os
import sys
from lbrynet.lbryfilemanager.LBRYFileDownloader import ManagedLBRYFileDownloader
from lbrynet.lbryfilemanager.LBRYFileDownloader import ManagedLBRYFileDownloaderFactory
from lbrynet.lbryfile.StreamDescriptor import LBRYFileStreamType
from lbrynet.core.PaymentRateManager import PaymentRateManager
from twisted.internet import defer, task, reactor
from twisted.python.failure import Failure
from lbrynet.cryptstream.client.CryptStreamDownloader import AlreadyStoppedError, CurrentlyStoppingError
from lbrynet.core.sqlite_helpers import rerun_if_locked


log = logging.getLogger(__name__)


class LBRYFileManager(object):
    """
    Keeps track of currently opened LBRY Files, their options, and their LBRY File specific metadata.
    """

    def __init__(self, session, stream_info_manager, sd_identifier):
        self.session = session
        self.stream_info_manager = stream_info_manager
        self.sd_identifier = sd_identifier
        self.lbry_files = []
        self.sql_db = None
        if sys.platform.startswith("darwin"):
            self.download_directory = os.path.join(os.path.expanduser("~"), 'Downloads')
        else:
            self.download_directory = os.getcwd()
        log.debug("Download directory for LBRYFileManager: %s", str(self.download_directory))

    def setup(self):
        d = self._open_db()
        d.addCallback(lambda _: self._add_to_sd_identifier())
        d.addCallback(lambda _: self._start_lbry_files())
        return d

    def get_all_lbry_file_stream_hashes_and_options(self):
        d = self._get_all_lbry_file_stream_hashes()

        def get_options(stream_hashes):
            ds = []

            def get_options_for_stream_hash(stream_hash):
                d = self.get_lbry_file_options(stream_hash)
                d.addCallback(lambda options: (stream_hash, options))
                return d

            for stream_hash in stream_hashes:
                ds.append(get_options_for_stream_hash(stream_hash))
            dl = defer.DeferredList(ds)
            dl.addCallback(lambda results: [r[1] for r in results if r[0]])
            return dl

        d.addCallback(get_options)
        return d

    def save_lbry_file(self, stream_hash, data_payment_rate):
        return self._save_lbry_file(stream_hash, data_payment_rate)

    def get_lbry_file_status(self, stream_hash):
        return self._get_lbry_file_status(stream_hash)

    def get_lbry_file_options(self, stream_hash):
        return self._get_lbry_file_options(stream_hash)

    def delete_lbry_file_options(self, stream_hash):
        return self._delete_lbry_file_options(stream_hash)

    def set_lbry_file_data_payment_rate(self, stream_hash, new_rate):
        return self._set_lbry_file_payment_rate(stream_hash, new_rate)

    def change_lbry_file_status(self, stream_hash, status):
        log.debug("Changing status of %s to %s", stream_hash, status)
        return self._change_file_status(stream_hash, status)

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
        downloader_factory = ManagedLBRYFileDownloaderFactory(self)
        self.sd_identifier.add_stream_downloader_factory(LBRYFileStreamType, downloader_factory)

    def _start_lbry_files(self):

        def set_options_and_restore(stream_hash, options):
            payment_rate_manager = PaymentRateManager(self.session.base_payment_rate_manager)
            d = self.start_lbry_file(stream_hash, payment_rate_manager, blob_data_rate=options[0])
            d.addCallback(lambda downloader: downloader.restore())
            return d

        def log_error(err):
            log.error("An error occurred while starting a lbry file: %s", err.getErrorMessage())

        def start_lbry_files(stream_hashes_and_options):
            for stream_hash, options in stream_hashes_and_options:
                d = set_options_and_restore(stream_hash, options)
                d.addErrback(log_error)
            return True

        d = self.get_all_lbry_file_stream_hashes_and_options()
        d.addCallback(start_lbry_files)
        return d

    def start_lbry_file(self, stream_hash, payment_rate_manager, blob_data_rate=None, upload_allowed=True):
        payment_rate_manager.min_blob_data_payment_rate = blob_data_rate
        lbry_file_downloader = ManagedLBRYFileDownloader(stream_hash, self.session.peer_finder,
                                                         self.session.rate_limiter, self.session.blob_manager,
                                                         self.stream_info_manager, self,
                                                         payment_rate_manager, self.session.wallet,
                                                         self.download_directory,
                                                         upload_allowed)
        self.lbry_files.append(lbry_file_downloader)
        d = lbry_file_downloader.set_stream_info()
        d.addCallback(lambda _: lbry_file_downloader)
        return d

    def add_lbry_file(self, stream_hash, payment_rate_manager, blob_data_rate=None, upload_allowed=True):
        d = self._save_lbry_file(stream_hash, blob_data_rate)
        d.addCallback(lambda _: self.start_lbry_file(stream_hash, payment_rate_manager, blob_data_rate, upload_allowed))
        return d

    def delete_lbry_file(self, stream_hash):
        for l in self.lbry_files:
            if l.stream_hash == stream_hash:
                lbry_file = l
                break
        else:
            return defer.fail(Failure(ValueError("Could not find an LBRY file with the given stream hash, " +
                                                 stream_hash)))

        def wait_for_finished(count=2):
            if count <= 0 or lbry_file.saving_status is False:
                return True
            else:
                return task.deferLater(reactor, 1, wait_for_finished, count=count - 1)

        def ignore_stopped(err):
            err.trap(AlreadyStoppedError, CurrentlyStoppingError)
            return wait_for_finished()

        d = lbry_file.stop()
        d.addErrback(ignore_stopped)

        def remove_from_list():
            self.lbry_files.remove(lbry_file)

        d.addCallback(lambda _: remove_from_list())
        d.addCallback(lambda _: self.delete_lbry_file_options(stream_hash))
        return d

    def toggle_lbry_file_running(self, stream_hash):
        """Toggle whether a stream reader is currently running"""
        for l in self.lbry_files:
            if l.stream_hash == stream_hash:
                return l.toggle_running()
        else:
            return defer.fail(Failure(ValueError("Could not find an LBRY file with the given stream hash, " +
                                                 stream_hash)))

    def get_stream_hash_from_name(self, lbry_file_name):
        for l in self.lbry_files:
            if l.file_name == lbry_file_name:
                return l.stream_hash
        return None

    def stop(self):
        ds = []

        def wait_for_finished(lbry_file, count=2):
            if count <= 0 or lbry_file.saving_status is False:
                return True
            else:
                return task.deferLater(reactor, 1, wait_for_finished, lbry_file, count=count - 1)

        def ignore_stopped(err, lbry_file):
            err.trap(AlreadyStoppedError, CurrentlyStoppingError)
            return wait_for_finished(lbry_file)

        for lbry_file in self.lbry_files:
            d = lbry_file.stop(change_status=False)
            d.addErrback(ignore_stopped, lbry_file)
            ds.append(d)
        dl = defer.DeferredList(ds)

        def close_db():
            self.db = None

        dl.addCallback(lambda _: close_db())
        return dl

    ######### database calls #########

    def _open_db(self):
        # check_same_thread=False is solely to quiet a spurious error that appears to be due
        # to a bug in twisted, where the connection is closed by a different thread than the
        # one that opened it. The individual connections in the pool are not used in multiple
        # threads.
        self.sql_db = adbapi.ConnectionPool("sqlite3", os.path.join(self.session.db_dir, "lbryfile_info.db"),
                                            check_same_thread=False)
        return self.sql_db.runQuery("create table if not exists lbry_file_options (" +
                                    "    blob_data_rate real, " +
                                    "    status text," +
                                    "    stream_hash text,"
                                    "    foreign key(stream_hash) references lbry_files(stream_hash)" +
                                    ")")

    @rerun_if_locked
    def _save_lbry_file(self, stream_hash, data_payment_rate):
        return self.sql_db.runQuery("insert into lbry_file_options values (?, ?, ?)",
                                    (data_payment_rate, ManagedLBRYFileDownloader.STATUS_STOPPED,
                                     stream_hash))

    @rerun_if_locked
    def _get_lbry_file_options(self, stream_hash):
        d = self.sql_db.runQuery("select blob_data_rate from lbry_file_options where stream_hash = ?",
                                 (stream_hash,))
        d.addCallback(lambda result: result[0] if len(result) else (None, ))
        return d

    @rerun_if_locked
    def _delete_lbry_file_options(self, stream_hash):
        return self.sql_db.runQuery("delete from lbry_file_options where stream_hash = ?",
                                    (stream_hash,))

    @rerun_if_locked
    def _set_lbry_file_payment_rate(self, stream_hash, new_rate):
        return self.sql_db.runQuery("update lbry_file_options set blob_data_rate = ? where stream_hash = ?",
                                    (new_rate, stream_hash))

    @rerun_if_locked
    def _get_all_lbry_file_stream_hashes(self):
        d = self.sql_db.runQuery("select stream_hash from lbry_file_options")
        d.addCallback(lambda results: [r[0] for r in results])
        return d

    @rerun_if_locked
    def _change_file_status(self, stream_hash, new_status):
        return self.sql_db.runQuery("update lbry_file_options set status = ? where stream_hash = ?",
                                    (new_status, stream_hash))

    @rerun_if_locked
    def _get_lbry_file_status(self, stream_hash):
        d = self.sql_db.runQuery("select status from lbry_file_options where stream_hash = ?",
                                 (stream_hash,))
        d.addCallback(lambda r: r[0][0] if len(r) else ManagedLBRYFileDownloader.STATUS_STOPPED)
        return d