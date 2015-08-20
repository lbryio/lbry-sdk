"""
Keep track of which LBRY Files are downloading and store their LBRY File specific metadata
"""

import logging
import json

import leveldb

from lbrynet.lbryfile.StreamDescriptor import LBRYFileStreamDescriptorValidator
import os
from lbrynet.lbryfilemanager.LBRYFileDownloader import ManagedLBRYFileDownloader
from lbrynet.lbryfilemanager.LBRYFileDownloader import ManagedLBRYFileDownloaderFactory
from lbrynet.lbryfile.StreamDescriptor import LBRYFileStreamType
from lbrynet.core.PaymentRateManager import PaymentRateManager
from twisted.internet import threads, defer, task, reactor
from twisted.python.failure import Failure
from lbrynet.cryptstream.client.CryptStreamDownloader import AlreadyStoppedError, CurrentlyStoppingError


class LBRYFileManager(object):
    """
    Keeps track of currently opened LBRY Files, their options, and their LBRY File specific metadata.
    """
    SETTING = "s"
    LBRYFILE_STATUS = "t"
    LBRYFILE_OPTIONS = "o"

    def __init__(self, session, stream_info_manager, sd_identifier):
        self.session = session
        self.stream_info_manager = stream_info_manager
        self.sd_identifier = sd_identifier
        self.lbry_files = []
        self.db = None
        self.download_directory = os.getcwd()

    def setup(self):
        d = threads.deferToThread(self._open_db)
        d.addCallback(lambda _: self._add_to_sd_identifier())
        d.addCallback(lambda _: self._start_lbry_files())
        return d

    def get_all_lbry_file_stream_hashes_and_options(self):
        d = threads.deferToThread(self._get_all_lbry_file_stream_hashes)

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

    def get_lbry_file_status(self, stream_hash):
        return threads.deferToThread(self._get_lbry_file_status, stream_hash)

    def save_lbry_file_options(self, stream_hash, blob_data_rate):
        return threads.deferToThread(self._save_lbry_file_options, stream_hash, blob_data_rate)

    def get_lbry_file_options(self, stream_hash):
        return threads.deferToThread(self._get_lbry_file_options, stream_hash)

    def delete_lbry_file_options(self, stream_hash):
        return threads.deferToThread(self._delete_lbry_file_options, stream_hash)

    def set_lbry_file_data_payment_rate(self, stream_hash, new_rate):
        return threads.deferToThread(self._set_lbry_file_payment_rate, stream_hash, new_rate)

    def change_lbry_file_status(self, stream_hash, status):
        logging.debug("Changing status of %s to %s", stream_hash, status)
        return threads.deferToThread(self._change_file_status, stream_hash, status)

    def delete_lbry_file_status(self, stream_hash):
        return threads.deferToThread(self._delete_lbry_file_status, stream_hash)

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
        self.sd_identifier.add_stream_info_validator(LBRYFileStreamType, LBRYFileStreamDescriptorValidator)
        self.sd_identifier.add_stream_downloader_factory(LBRYFileStreamType, downloader_factory)

    def _start_lbry_files(self):

        def set_options_and_restore(stream_hash, options):
            payment_rate_manager = PaymentRateManager(self.session.base_payment_rate_manager)
            d = self.add_lbry_file(stream_hash, payment_rate_manager, blob_data_rate=options[0])
            d.addCallback(lambda downloader: downloader.restore())
            return d

        def log_error(err):
            logging.error("An error occurred while starting a lbry file: %s", err.getErrorMessage())

        def start_lbry_files(stream_hashes_and_options):
            for stream_hash, options in stream_hashes_and_options:
                d = set_options_and_restore(stream_hash, options)
                d.addErrback(log_error)
            return True

        d = self.get_all_lbry_file_stream_hashes_and_options()
        d.addCallback(start_lbry_files)
        return d

    def add_lbry_file(self, stream_hash, payment_rate_manager, blob_data_rate=None, upload_allowed=True):
        payment_rate_manager.min_blob_data_payment_rate = blob_data_rate
        lbry_file_downloader = ManagedLBRYFileDownloader(stream_hash, self.session.peer_finder,
                                                         self.session.rate_limiter, self.session.blob_manager,
                                                         self.stream_info_manager, self,
                                                         payment_rate_manager, self.session.wallet,
                                                         self.download_directory,
                                                         upload_allowed)
        self.lbry_files.append(lbry_file_downloader)
        d = self.save_lbry_file_options(stream_hash, blob_data_rate)
        d.addCallback(lambda _: lbry_file_downloader.set_stream_info())
        d.addCallback(lambda _: lbry_file_downloader)
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
        d.addCallback(lambda _: self.delete_lbry_file_status(stream_hash))
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
        self.db = leveldb.LevelDB(os.path.join(self.session.db_dir, "lbryfiles.db"))

    def _save_payment_rate(self, rate_type, rate):
        if rate is not None:
            self.db.Put(json.dumps((self.SETTING, rate_type)), json.dumps(rate), sync=True)
        else:
            self.db.Delete(json.dumps((self.SETTING, rate_type)), sync=True)

    def _save_lbry_file_options(self, stream_hash, blob_data_rate):
        self.db.Put(json.dumps((self.LBRYFILE_OPTIONS, stream_hash)), json.dumps((blob_data_rate,)),
                    sync=True)

    def _get_lbry_file_options(self, stream_hash):
        try:
            return json.loads(self.db.Get(json.dumps((self.LBRYFILE_OPTIONS, stream_hash))))
        except KeyError:
            return None, None

    def _delete_lbry_file_options(self, stream_hash):
        self.db.Delete(json.dumps((self.LBRYFILE_OPTIONS, stream_hash)), sync=True)

    def _set_lbry_file_payment_rate(self, stream_hash, new_rate):

        self.db.Put(json.dumps((self.LBRYFILE_OPTIONS, stream_hash)), json.dumps((new_rate, )), sync=True)

    def _get_all_lbry_file_stream_hashes(self):
        hashes = []
        for k, v in self.db.RangeIter():
            key_type, stream_hash = json.loads(k)
            if key_type == self.LBRYFILE_STATUS:
                hashes.append(stream_hash)
        return hashes

    def _change_file_status(self, stream_hash, new_status):
        self.db.Put(json.dumps((self.LBRYFILE_STATUS, stream_hash)), new_status, sync=True)

    def _get_lbry_file_status(self, stream_hash):
        try:
            return self.db.Get(json.dumps((self.LBRYFILE_STATUS, stream_hash)))
        except KeyError:
            return ManagedLBRYFileDownloader.STATUS_STOPPED

    def _delete_lbry_file_status(self, stream_hash):
        self.db.Delete(json.dumps((self.LBRYFILE_STATUS, stream_hash)), sync=True)