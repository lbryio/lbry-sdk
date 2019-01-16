"""
Keep track of which LBRY Files are downloading and store their LBRY File specific metadata
"""
import os
import logging
from binascii import hexlify, unhexlify

from twisted.internet import defer, task, reactor
from twisted.python.failure import Failure
from lbrynet import conf
from lbrynet.extras.reflector.reupload import reflect_file
from lbrynet.staging.EncryptedFileDownloader import ManagedEncryptedFileDownloader
from lbrynet.staging.EncryptedFileDownloader import ManagedEncryptedFileDownloaderFactory
# from lbrynet.blob.stream import EncryptedFileStreamType, get_sd_info
from lbrynet.utils import safe_start_looping_call, safe_stop_looping_call

log = logging.getLogger(__name__)


class EncryptedFileManager:
    """
    Keeps track of currently opened LBRY Files, their options, and
    their LBRY File specific metadata.
    """
    # when reflecting files, reflect up to this many files at a time
    CONCURRENT_REFLECTS = 5

    def __init__(self, peer_finder, rate_limiter, blob_manager, wallet, payment_rate_manager, storage, sd_identifier):
        self.auto_re_reflect = conf.settings['reflect_uploads'] and conf.settings['auto_re_reflect_interval'] > 0
        self.auto_re_reflect_interval = conf.settings['auto_re_reflect_interval']
        self.peer_finder = peer_finder
        self.rate_limiter = rate_limiter
        self.blob_manager = blob_manager
        self.wallet = wallet
        self.payment_rate_manager = payment_rate_manager
        self.storage = storage
        # TODO: why is sd_identifier part of the file manager?
        self.sd_identifier = sd_identifier
        self.lbry_files = []
        self.lbry_file_reflector = task.LoopingCall(self.reflect_lbry_files)

    @defer.inlineCallbacks
    def setup(self):
        yield self._add_to_sd_identifier()
        yield self._start_lbry_files()
        log.info("Started file manager")

    def get_lbry_file_status(self, lbry_file):
        return self.storage.get_lbry_file_status(lbry_file.rowid)

    def set_lbry_file_data_payment_rate(self, lbry_file, new_rate):
        return self.storage(lbry_file.rowid, new_rate)

    def change_lbry_file_status(self, lbry_file, status):
        log.debug("Changing status of %s to %s", lbry_file.stream_hash, status)
        return self.storage.change_file_status(lbry_file.rowid, status)

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
        downloader_factory = ManagedEncryptedFileDownloaderFactory(self, self.blob_manager)
        self.sd_identifier.add_stream_downloader_factory(
            EncryptedFileStreamType, downloader_factory)

    def _get_lbry_file(self, rowid, stream_hash, payment_rate_manager, sd_hash, key,
                       stream_name, file_name, download_directory, suggested_file_name, download_mirrors=None):
        return ManagedEncryptedFileDownloader(
            rowid,
            stream_hash,
            self.peer_finder,
            self.rate_limiter,
            self.blob_manager,
            self.storage,
            self,
            payment_rate_manager,
            self.wallet,
            download_directory,
            file_name,
            stream_name=stream_name,
            sd_hash=sd_hash,
            key=key,
            suggested_file_name=suggested_file_name,
            download_mirrors=download_mirrors
        )

    def _start_lbry_file(self, file_info, payment_rate_manager, claim_info, download_mirrors=None):
        lbry_file = self._get_lbry_file(
            file_info['row_id'], file_info['stream_hash'], payment_rate_manager, file_info['sd_hash'],
            file_info['key'], file_info['stream_name'], file_info['file_name'], file_info['download_directory'],
            file_info['suggested_file_name'], download_mirrors
        )
        if claim_info:
            lbry_file.set_claim_info(claim_info)
        try:
            # restore will raise an Exception if status is unknown
            lbry_file.restore(file_info['status'])
            self.storage.content_claim_callbacks[lbry_file.stream_hash] = lbry_file.get_claim_info
            self.lbry_files.append(lbry_file)
            if len(self.lbry_files) % 500 == 0:
                log.info("Started %i files", len(self.lbry_files))
        except Exception:
            log.warning("Failed to start %i", file_info.get('rowid'))

    @defer.inlineCallbacks
    def _start_lbry_files(self):
        files = yield self.storage.get_all_lbry_files()
        claim_infos = yield self.storage.get_claims_from_stream_hashes([file['stream_hash'] for file in files])
        prm = self.payment_rate_manager

        log.info("Starting %i files", len(files))
        for file_info in files:
            claim_info = claim_infos.get(file_info['stream_hash'])
            self._start_lbry_file(file_info, prm, claim_info)

        log.info("Started %i lbry files", len(self.lbry_files))
        if self.auto_re_reflect is True:
            safe_start_looping_call(self.lbry_file_reflector, self.auto_re_reflect_interval / 10)

    @defer.inlineCallbacks
    def _stop_lbry_file(self, lbry_file):
        def wait_for_finished(lbry_file, count=2):
            if count or lbry_file.saving_status is not False:
                return task.deferLater(reactor, 1, self._stop_lbry_file, lbry_file,
                                       count=count - 1)
        try:
            yield lbry_file.stop(change_status=False)
            self.lbry_files.remove(lbry_file)
        # except CurrentlyStoppingError:
        #     yield wait_for_finished(lbry_file)
        # except AlreadyStoppedError:
        #     pass
        finally:
            defer.returnValue(None)

    @defer.inlineCallbacks
    def _stop_lbry_files(self):
        log.info("Stopping %i lbry files", len(self.lbry_files))
        yield defer.DeferredList([self._stop_lbry_file(lbry_file) for lbry_file in list(self.lbry_files)])

    @defer.inlineCallbacks
    def add_published_file(self, stream_hash, sd_hash, download_directory, payment_rate_manager, blob_data_rate):
        status = ManagedEncryptedFileDownloader.STATUS_FINISHED
        stream_metadata = yield get_sd_info(self.storage, stream_hash, include_blobs=False)
        key = stream_metadata['key']
        stream_name = stream_metadata['stream_name']
        file_name = stream_metadata['suggested_file_name']
        rowid = yield self.storage.save_published_file(
            stream_hash, file_name, download_directory, blob_data_rate, status
        )
        lbry_file = self._get_lbry_file(
            rowid, stream_hash, payment_rate_manager, sd_hash, key, stream_name, file_name, download_directory,
            stream_metadata['suggested_file_name'], download_mirrors=None
        )
        lbry_file.restore(status)
        yield lbry_file.get_claim_info()
        self.storage.content_claim_callbacks[stream_hash] = lbry_file.get_claim_info
        self.lbry_files.append(lbry_file)
        defer.returnValue(lbry_file)

    @defer.inlineCallbacks
    def add_downloaded_file(self, stream_hash, sd_hash, download_directory, payment_rate_manager=None,
                            blob_data_rate=None, status=None, file_name=None, download_mirrors=None):
        status = status or ManagedEncryptedFileDownloader.STATUS_STOPPED
        payment_rate_manager = payment_rate_manager or self.payment_rate_manager
        blob_data_rate = blob_data_rate or payment_rate_manager.min_blob_data_payment_rate
        stream_metadata = yield get_sd_info(self.storage, stream_hash, include_blobs=False)
        key = stream_metadata['key']
        stream_name = stream_metadata['stream_name']
        file_name = file_name or stream_metadata['suggested_file_name']

        # when we save the file we'll atomic touch the nearest file to the suggested file name
        # that doesn't yet exist in the download directory
        rowid = yield self.storage.save_downloaded_file(
            stream_hash, hexlify(os.path.basename(unhexlify(file_name))), download_directory, blob_data_rate
        )
        file_name = (yield self.storage.get_filename_for_rowid(rowid)).decode()
        lbry_file = self._get_lbry_file(
            rowid, stream_hash, payment_rate_manager, sd_hash, key, stream_name, file_name, download_directory,
            stream_metadata['suggested_file_name'], download_mirrors
        )
        lbry_file.restore(status)
        yield lbry_file.get_claim_info(include_supports=False)
        self.storage.content_claim_callbacks[stream_hash] = lbry_file.get_claim_info
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

        if lbry_file.stream_hash in self.storage.content_claim_callbacks:
            del self.storage.content_claim_callbacks[lbry_file.stream_hash]

        yield lbry_file.delete_data()
        yield self.storage.delete_stream(lbry_file.stream_hash)

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
        sd_hashes_to_reflect = yield self.storage.get_streams_to_re_reflect()
        for lbry_file in self.lbry_files:
            if lbry_file.sd_hash in sd_hashes_to_reflect:
                ds.append(sem.run(reflect_file, lbry_file))
        yield defer.DeferredList(ds)

    @defer.inlineCallbacks
    def stop(self):
        safe_stop_looping_call(self.lbry_file_reflector)
        yield self._stop_lbry_files()
        log.info("Stopped encrypted file manager")
        defer.returnValue(True)
