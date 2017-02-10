"""
Keep track of which LBRY Files are downloading and store their LBRY File specific metadata
"""

import logging
import os

from twisted.enterprise import adbapi
from twisted.internet import defer, task, reactor
from twisted.python.failure import Failure

from lbrynet.reflector.reupload import reflect_stream
from lbrynet.core.PaymentRateManager import NegotiatedPaymentRateManager
from lbrynet.lbryfilemanager.EncryptedFileDownloader import ManagedEncryptedFileDownloader
from lbrynet.lbryfilemanager.EncryptedFileDownloader import ManagedEncryptedFileDownloaderFactory
from lbrynet.lbryfile.StreamDescriptor import EncryptedFileStreamType
from lbrynet.cryptstream.client.CryptStreamDownloader import AlreadyStoppedError
from lbrynet.cryptstream.client.CryptStreamDownloader import CurrentlyStoppingError
from lbrynet.core.sqlite_helpers import rerun_if_locked


log = logging.getLogger(__name__)


def safe_start_looping_call(looping_call, seconds=3600):
    if not looping_call.running:
        looping_call.start(seconds)


def safe_stop_looping_call(looping_call):
    if looping_call.running:
        looping_call.stop()


class EncryptedFileManager(object):
    """Keeps track of currently opened LBRY Files, their options, and
    their LBRY File specific metadata.

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
        self.lbry_file_reflector = task.LoopingCall(self.reflect_lbry_files)
        log.debug("Download directory for EncryptedFileManager: %s", str(self.download_directory))

    @defer.inlineCallbacks
    def setup(self):
        yield self._open_db()
        yield self._add_to_sd_identifier()
        yield self._start_lbry_files()
        safe_start_looping_call(self.lbry_file_reflector)

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
    def _check_stream_is_managed(self, stream_hash):
        # check that all the streams in the stream_info_manager are also
        # tracked by lbry_file_manager and fix any streams that aren't.
        rowid = yield self._get_rowid_for_stream_hash(stream_hash)
        if rowid is not None:
            defer.returnValue(True)
        rate = self.session.base_payment_rate_manager.min_blob_data_payment_rate
        key, stream_name, file_name = yield self.stream_info_manager.get_stream_info(stream_hash)
        log.warning("Trying to fix missing lbry file for %s", stream_name.decode('hex'))
        yield self._save_lbry_file(stream_hash, rate)

    @defer.inlineCallbacks
    def _check_stream_info_manager(self):
        def _iter_streams(stream_hashes):
            for stream_hash in stream_hashes:
                yield self._check_stream_is_managed(stream_hash)

        stream_hashes = yield self.stream_info_manager.get_all_streams()
        log.debug("Checking %s streams", len(stream_hashes))
        yield defer.DeferredList(list(_iter_streams(stream_hashes)))

    @defer.inlineCallbacks
    def _restore_lbry_file(self, lbry_file):
        try:
            yield lbry_file.restore()
        except Exception as err:
            log.error("Failed to start stream: %s, error: %s", lbry_file.stream_hash, err)
            self.lbry_files.remove(lbry_file)
            # TODO: delete stream without claim instead of just removing from manager?

    @defer.inlineCallbacks
    def _start_lbry_files(self):
        b_prm = self.session.base_payment_rate_manager
        payment_rate_manager = NegotiatedPaymentRateManager(b_prm, self.session.blob_tracker)
        yield self._check_stream_info_manager()
        lbry_files_and_options = yield self._get_all_lbry_files()
        for rowid, stream_hash, options in lbry_files_and_options:
            lbry_file = yield self.start_lbry_file(rowid, stream_hash, payment_rate_manager,
                                                   blob_data_rate=options)
            d = self._restore_lbry_file(lbry_file)
            log.debug("Started %s", lbry_file)
        log.info("Started %i lbry files", len(self.lbry_files))
        defer.returnValue(True)

    @defer.inlineCallbacks
    def start_lbry_file(self, rowid, stream_hash,
                        payment_rate_manager, blob_data_rate=None, upload_allowed=True,
                        download_directory=None, file_name=None):
        if not download_directory:
            download_directory = self.download_directory
        payment_rate_manager.min_blob_data_payment_rate = blob_data_rate
        lbry_file = ManagedEncryptedFileDownloader(rowid, stream_hash, self.session.peer_finder,
                                                   self.session.rate_limiter,
                                                   self.session.blob_manager,
                                                   self.stream_info_manager,
                                                   self, payment_rate_manager, self.session.wallet,
                                                   download_directory, upload_allowed,
                                                   file_name=file_name)
        yield lbry_file.set_stream_info()
        self.lbry_files.append(lbry_file)
        defer.returnValue(lbry_file)

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
    def add_lbry_file(self, stream_hash, payment_rate_manager, blob_data_rate=None,
                      upload_allowed=True, download_directory=None, file_name=None):
        rowid = yield self._save_lbry_file(stream_hash, blob_data_rate)
        lbry_file = yield self.start_lbry_file(rowid, stream_hash, payment_rate_manager,
                                               blob_data_rate, upload_allowed, download_directory,
                                               file_name)
        defer.returnValue(lbry_file)

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

    def _reflect_lbry_files(self):
        for lbry_file in self.lbry_files:
            yield reflect_stream(lbry_file)

    @defer.inlineCallbacks
    def reflect_lbry_files(self):
        yield defer.DeferredList(list(self._reflect_lbry_files()))

    @defer.inlineCallbacks
    def stop(self):
        safe_stop_looping_call(self.lbry_file_reflector)
        yield defer.DeferredList(list(self._stop_lbry_files()))
        yield self.sql_db.close()
        self.sql_db = None
        log.info("Stopped %s", self)
        defer.returnValue(True)

    def get_count_for_stream_hash(self, stream_hash):
        return self._get_count_for_stream_hash(stream_hash)

    ######### database calls #########

    def _open_db(self):
        # check_same_thread=False is solely to quiet a spurious error that appears to be due
        # to a bug in twisted, where the connection is closed by a different thread than the
        # one that opened it. The individual connections in the pool are not used in multiple
        # threads.
        self.sql_db = adbapi.ConnectionPool(
            "sqlite3",
            os.path.join(self.session.db_dir, "lbryfile_info.db"),
            check_same_thread=False
        )
        return self.sql_db.runQuery(
            "create table if not exists lbry_file_options (" +
            "    blob_data_rate real, " +
            "    status text," +
            "    stream_hash text,"
            "    foreign key(stream_hash) references lbry_files(stream_hash)" +
            ")"
        )

    @rerun_if_locked
    def _save_lbry_file(self, stream_hash, data_payment_rate):
        def do_save(db_transaction):
            db_transaction.execute("insert into lbry_file_options values (?, ?, ?)",
                                  (data_payment_rate, ManagedEncryptedFileDownloader.STATUS_STOPPED,
                                   stream_hash))
            return db_transaction.lastrowid
        return self.sql_db.runInteraction(do_save)

    @rerun_if_locked
    def _delete_lbry_file_options(self, rowid):
        return self.sql_db.runQuery("delete from lbry_file_options where rowid = ?",
                                    (rowid,))

    @rerun_if_locked
    def _set_lbry_file_payment_rate(self, rowid, new_rate):
        return self.sql_db.runQuery(
            "update lbry_file_options set blob_data_rate = ? where rowid = ?",
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
        d.addCallback(lambda r: (r[0][0] if len(r) else None))
        return d

    @rerun_if_locked
    def _get_count_for_stream_hash(self, stream_hash):
        d = self.sql_db.runQuery("select count(*) from lbry_file_options where stream_hash = ?",
                                     (stream_hash,))
        d.addCallback(lambda r: (r[0][0] if r else 0))
        return d

    @rerun_if_locked
    def _get_rowid_for_stream_hash(self, stream_hash):
        d = self.sql_db.runQuery("select rowid from lbry_file_options where stream_hash = ?",
                                     (stream_hash,))
        d.addCallback(lambda r: (r[0][0] if len(r) else None))
        return d
