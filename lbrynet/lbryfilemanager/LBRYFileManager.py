"""
Keep track of which LBRY Files are downloading and store their LBRY File specific metadata
"""

import logging
import os

from twisted.enterprise import adbapi
from twisted.internet import defer, task, reactor
from twisted.python.failure import Failure

from lbrynet.lbryfilemanager.LBRYFileDownloader import ManagedLBRYFileDownloader
from lbrynet.lbryfilemanager.LBRYFileDownloader import ManagedLBRYFileDownloaderFactory
from lbrynet.lbryfile.StreamDescriptor import LBRYFileStreamType
from lbrynet.core.PaymentRateManager import PaymentRateManager
from lbrynet.cryptstream.client.CryptStreamDownloader import AlreadyStoppedError, CurrentlyStoppingError
from lbrynet.core.sqlite_helpers import rerun_if_locked


log = logging.getLogger(__name__)


class LBRYFileManager(object):
    """
    Keeps track of currently opened LBRY Files, their options, and their LBRY File specific metadata.
    """

    def __init__(self, session, stream_info_manager, sd_identifier, download_directory=None):
        self.session = session
        self.stream_info_manager = stream_info_manager
        self.sd_identifier = sd_identifier
        self.lbry_files = []
        self.sql_db = None
        if download_directory:
            self.download_directory = download_directory
        else:
            self.download_directory = os.getcwd()
        log.debug("Download directory for LBRYFileManager: %s", str(self.download_directory))

    def setup(self):
        d = self._open_db()
        d.addCallback(lambda _: self._add_to_sd_identifier())
        d.addCallback(lambda _: self._start_lbry_files())
        return d

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

    def _add_to_sd_identifier(self):
        downloader_factory = ManagedLBRYFileDownloaderFactory(self)
        self.sd_identifier.add_stream_downloader_factory(LBRYFileStreamType, downloader_factory)

    def _start_lbry_files(self):

        def set_options_and_restore(rowid, stream_hash, options):
            payment_rate_manager = PaymentRateManager(self.session.base_payment_rate_manager)
            d = self.start_lbry_file(rowid, stream_hash, payment_rate_manager,
                                     blob_data_rate=options)
            d.addCallback(lambda downloader: downloader.restore())
            return d

        def log_error(err):
            log.error("An error occurred while starting a lbry file: %s", err.getErrorMessage())

        def start_lbry_files(lbry_files_and_options):
            for rowid, stream_hash, options in lbry_files_and_options:
                d = set_options_and_restore(rowid, stream_hash, options)
                d.addErrback(log_error)
            return True

        d = self._get_all_lbry_files()
        d.addCallback(start_lbry_files)
        return d

    def start_lbry_file(self, rowid, stream_hash, payment_rate_manager, blob_data_rate=None, upload_allowed=True,
                                                                        download_directory=None, file_name=None):
        if not download_directory:
            download_directory = self.download_directory
        payment_rate_manager.min_blob_data_payment_rate = blob_data_rate
        lbry_file_downloader = ManagedLBRYFileDownloader(rowid, stream_hash,
                                                         self.session.peer_finder,
                                                         self.session.rate_limiter,
                                                         self.session.blob_manager,
                                                         self.stream_info_manager, self,
                                                         payment_rate_manager, self.session.wallet,
                                                         download_directory,
                                                         upload_allowed,
                                                         file_name=file_name)
        self.lbry_files.append(lbry_file_downloader)
        d = lbry_file_downloader.set_stream_info()
        d.addCallback(lambda _: lbry_file_downloader)
        return d

    def add_lbry_file(self, stream_hash, payment_rate_manager, blob_data_rate=None, upload_allowed=True,
                                                                download_directory=None, file_name=None):
        d = self._save_lbry_file(stream_hash, blob_data_rate)
        d.addCallback(lambda rowid: self.start_lbry_file(rowid, stream_hash, payment_rate_manager,
                                                         blob_data_rate, upload_allowed, download_directory, file_name))
        return d

    def delete_lbry_file(self, lbry_file):
        for l in self.lbry_files:
            if l == lbry_file:
                lbry_file = l
                break
        else:
            return defer.fail(Failure(ValueError("Could not find that LBRY file")))

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
        d.addCallback(lambda _: self._delete_lbry_file_options(lbry_file.rowid))
        return d

    def toggle_lbry_file_running(self, lbry_file):
        """Toggle whether a stream reader is currently running"""
        for l in self.lbry_files:
            if l == lbry_file:
                return l.toggle_running()
        else:
            return defer.fail(Failure(ValueError("Could not find that LBRY file")))

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

    def get_count_for_stream_hash(self, stream_hash):
        return self._get_count_for_stream_hash(stream_hash)

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
        def do_save(db_transaction):
            db_transaction.execute("insert into lbry_file_options values (?, ?, ?)",
                                  (data_payment_rate, ManagedLBRYFileDownloader.STATUS_STOPPED,
                                   stream_hash))
            return db_transaction.lastrowid
        return self.sql_db.runInteraction(do_save)

    @rerun_if_locked
    def _delete_lbry_file_options(self, rowid):
        return self.sql_db.runQuery("delete from lbry_file_options where rowid = ?",
                                    (rowid,))

    @rerun_if_locked
    def _set_lbry_file_payment_rate(self, rowid, new_rate):
        return self.sql_db.runQuery("update lbry_file_options set blob_data_rate = ? where rowid = ?",
                                    (new_rate, rowid))

    @rerun_if_locked
    def _get_all_lbry_files(self):
        d = self.sql_db.runQuery("select rowid, stream_hash, blob_data_rate from lbry_file_options")
        return d

    @rerun_if_locked
    def _change_file_status(self, rowid, new_status):
        return self.sql_db.runQuery("update lbry_file_options set status = ? where rowid = ?",
                                    (new_status, rowid))

    @rerun_if_locked
    def _get_lbry_file_status(self, rowid):
        d = self.sql_db.runQuery("select status from lbry_file_options where rowid = ?",
                                 (rowid,))
        d.addCallback(lambda r: r[0][0] if len(r) else ManagedLBRYFileDownloader.STATUS_STOPPED)
        return d

    @rerun_if_locked
    def _get_count_for_stream_hash(self, stream_hash):
        return self.sql_db.runQuery("select count(*) from lbry_file_options where stream_hash = ?",
                                     (stream_hash,))