import logging
import os

from twisted.enterprise import adbapi
from twisted.internet import defer, task, reactor

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


@defer.inlineCallbacks
def wait_for_finished(lbry_file, count=2):
    if count and lbry_file.saving_status is not False:
        yield task.deferLater(reactor, 1, wait_for_finished, lbry_file, count=count - 1)
    defer.returnValue(True)


class EncryptedFileManager(object):
    """
    Keeps track of currently opened LBRY Files, their options, and
    their LBRY File specific metadata using sqlite
    """

    def __init__(self, session, stream_info_manager, sd_identifier, download_directory=None):
        """
        :param session: Session
        :param stream_info_manager: IEncryptedFileMetadataManager
        :param sd_identifier: StreamDescriptorIdentifier
        :param download_directory: str, path to download directory
        """

        self.session = session
        self.stream_info_manager = stream_info_manager
        # TODO: why is sd_identifier part of the file manager?
        self.sd_identifier = sd_identifier
        self.lbry_files = []
        self.download_directory = download_directory or os.getcwd()
        self.sql_db = None
        self.db_path = os.path.join(self.session.db_dir, "lbryfile_info.db")
        self.lbry_file_reflector = task.LoopingCall(self.reflect_lbry_files)
        log.debug("Download directory for EncryptedFileManager: %s", str(self.download_directory))

    @defer.inlineCallbacks
    def setup(self):
        yield self._setup()
        downloader_factory = ManagedEncryptedFileDownloaderFactory(self)
        yield self.sd_identifier.add_stream_downloader_factory(EncryptedFileStreamType,
                                                               downloader_factory)
        yield self.start_lbry_files()
        safe_start_looping_call(self.lbry_file_reflector)

    @defer.inlineCallbacks
    def stop(self):
        safe_stop_looping_call(self.lbry_file_reflector)
        yield self.stop_lbry_files()
        yield self._stop()
        log.info("Stopped %s", self)

    @defer.inlineCallbacks
    def get_lbry_file_status(self, lbry_file):
        status = yield self._get_lbry_file_status(lbry_file.rowid)
        defer.returnValue(status)

    @defer.inlineCallbacks
    def set_lbry_file_data_payment_rate(self, lbry_file, new_rate):
        yield self._set_lbry_file_payment_rate(lbry_file.rowid, new_rate)

    @defer.inlineCallbacks
    def change_lbry_file_status(self, lbry_file, status):
        log.debug("Changing status of %s to %s", lbry_file.stream_hash, status)
        yield self._change_file_status(lbry_file.rowid, status)

    @defer.inlineCallbacks
    def get_lbry_file_status_reports(self):
        statuses = []
        for lbry_file in self.lbry_files:
            status = yield lbry_file.status()
            statuses.append(status)
        defer.returnValue(statuses)

    @defer.inlineCallbacks
    def save_sd_blob_hash_to_stream(self, stream_hash, sd_hash):
        yield self.stream_info_manager.save_sd_blob_hash_to_stream(stream_hash, sd_hash)

    @defer.inlineCallbacks
    def add_lbry_file(self, stream_hash, payment_rate_manager, blob_data_rate=None,
                      download_directory=None, file_name=None):
        rowid = yield self._save_lbry_file(stream_hash, blob_data_rate)
        lbry_file = yield self.start_lbry_file(rowid, stream_hash, payment_rate_manager,
                                               blob_data_rate, download_directory,
                                               file_name)
        defer.returnValue(lbry_file)

    @defer.inlineCallbacks
    def delete_lbry_file(self, lbry_file):
        if lbry_file not in self.lbry_files:
            raise ValueError("Could not find that LBRY file")
        try:
            yield lbry_file.stop()
        except CurrentlyStoppingError:
            yield wait_for_finished(lbry_file)
        except AlreadyStoppedError:
            pass
        finally:
            self.lbry_files.remove(lbry_file)
            yield self._delete_lbry_file_options(lbry_file.rowid)

    @defer.inlineCallbacks
    def toggle_lbry_file_running(self, lbry_file):
        """Toggle whether a stream reader is currently running"""

        if lbry_file not in self.lbry_files:
            raise ValueError("Could not find that LBRY file")
        yield lbry_file.toggle_running()

    @defer.inlineCallbacks
    def reflect_lbry_files(self):
        dl = []
        for lbry_file in self.lbry_files:
            dl.append(reflect_stream(lbry_file))
        yield defer.DeferredList(dl)

    @defer.inlineCallbacks
    def get_count_for_stream_hash(self, stream_hash):
        stream_count = yield self._get_count_for_stream_hash(stream_hash)
        defer.returnValue(stream_count)

    @defer.inlineCallbacks
    def check_stream_is_managed(self, stream_hash):
        rowid = yield self._get_rowid_for_stream_hash(stream_hash)
        if rowid is not None:
            defer.returnValue(True)
        rate = self.session.base_payment_rate_manager.min_blob_data_payment_rate
        key, stream_name, file_name = yield self.stream_info_manager.get_stream_info(stream_hash)
        log.warning("Trying to fix missing lbry file for %s", stream_name.decode('hex'))
        yield self._save_lbry_file(stream_hash, rate)

    @defer.inlineCallbacks
    def check_streams_are_managed(self):
        """
        check that all the streams in the stream_info_manager are also
        tracked by lbry_file_manager and fix any streams that aren't.
        """

        stream_hashes = yield self.stream_info_manager.get_all_streams()
        log.debug("Checking %s streams", len(stream_hashes))
        dl = []
        for stream_hash in stream_hashes:
            dl.append(self.check_stream_is_managed(stream_hash))
        yield defer.DeferredList(dl)

    @defer.inlineCallbacks
    def set_options_and_restore(self, rowid, stream_hash, options):
        try:
            b_prm = self.session.base_payment_rate_manager
            payment_rate_manager = NegotiatedPaymentRateManager(
                b_prm, self.session.blob_tracker)
            downloader = yield self.start_lbry_file(
                rowid, stream_hash, payment_rate_manager, blob_data_rate=options)
            yield downloader.restore()
        except Exception as err:
            log.exception('An error occurred while starting a lbry file (%s, %s, %s)',
                          rowid, stream_hash, options)

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
    def start_lbry_files(self):
        yield self.check_streams_are_managed()
        files_and_options = yield self._get_all_lbry_files()
        dl = []
        for rowid, stream_hash, options in files_and_options:
            dl.append(self.set_options_and_restore(rowid, stream_hash, options))
        yield defer.DeferredList(dl)
        log.info("Started %i lbry files", len(self.lbry_files))

    @defer.inlineCallbacks
    def stop_lbry_file(self, lbry_file):
        try:
            yield lbry_file.stop(change_status=False)
        except CurrentlyStoppingError:
            yield wait_for_finished(lbry_file)
        except AlreadyStoppedError:
            pass
        finally:
            defer.returnValue(None)

    @defer.inlineCallbacks
    def stop_lbry_files(self):
        log.info("Stopping %i lbry files", len(self.lbry_files))
        lbry_files = self.lbry_files
        dl = []
        for lbry_file in lbry_files:
            dl.append(self.stop_lbry_file(lbry_file))
        yield defer.DeferredList(dl)

    # # # # # # # # # # # #
    # database functions  #
    # # # # # # # # # # # #

    @defer.inlineCallbacks
    def _setup(self):
        # check_same_thread=False is solely to quiet a spurious error that appears to be due
        # to a bug in twisted, where the connection is closed by a different thread than the
        # one that opened it. The individual connections in the pool are not used in multiple
        # threads.
        self.sql_db = adbapi.ConnectionPool("sqlite3", self.db_path, check_same_thread=False)
        create_tables_query = (
            "create table if not exists lbry_file_options ("
            "    blob_data_rate real, "
            "    status text,"
            "    stream_hash text,"
            "    foreign key(stream_hash) references lbry_files(stream_hash)"
            ")")
        yield self.sql_db.runQuery(create_tables_query)
        defer.returnValue(None)

    @defer.inlineCallbacks
    def _stop(self):
        yield self.sql_db.close()
        self.sql_db = None

    @rerun_if_locked
    def _save_lbry_file(self, stream_hash, data_payment_rate):
        def do_save(db_transaction):
            row = (data_payment_rate, ManagedEncryptedFileDownloader.STATUS_STOPPED, stream_hash)
            db_transaction.execute("insert into lbry_file_options values (?, ?, ?)", row)
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
    @defer.inlineCallbacks
    def _get_lbry_file_status(self, rowid):
        query_string = "select status from lbry_file_options where rowid = ?"
        query_results = yield self.sql_db.runQuery(query_string, (rowid,))
        status = None
        if query_results:
            status = query_results[0][0]
        defer.returnValue(status)

    @rerun_if_locked
    @defer.inlineCallbacks
    def _get_count_for_stream_hash(self, stream_hash):
        query_string = "select count(*) from lbry_file_options where stream_hash = ?"
        query_results = yield self.sql_db.runQuery(query_string, (stream_hash,))
        result = 0
        if query_results:
            result = query_results[0][0]
        defer.returnValue(result)

    @rerun_if_locked
    @defer.inlineCallbacks
    def _get_rowid_for_stream_hash(self, stream_hash):
        query_string = "select rowid from lbry_file_options where stream_hash = ?"
        query_results = yield self.sql_db.runQuery(query_string, (stream_hash,))
        result = None
        if query_results:
            result = query_results[0][0]
        defer.returnValue(result)
