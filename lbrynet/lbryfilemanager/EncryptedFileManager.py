import logging
import os

from twisted.internet import defer, task, reactor

from lbrynet.reflector.reupload import reflect_stream
from lbrynet.core.PaymentRateManager import NegotiatedPaymentRateManager
from lbrynet.core.Wallet import ClaimOutpoint
from lbrynet.lbryfilemanager.EncryptedFileDownloader import ManagedEncryptedFileDownloader
from lbrynet.lbryfilemanager.EncryptedFileDownloader import ManagedEncryptedFileDownloaderFactory
from lbrynet.lbryfile.StreamDescriptor import EncryptedFileStreamType
from lbrynet.cryptstream.client.CryptStreamDownloader import AlreadyStoppedError
from lbrynet.cryptstream.client.CryptStreamDownloader import CurrentlyStoppingError


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
        self.storage = stream_info_manager.storage
        self.stream_info_manager = stream_info_manager
        # TODO: why is sd_identifier part of the file manager?
        self.sd_identifier = sd_identifier
        self.lbry_files = []
        self.download_directory = download_directory or os.getcwd()
        self.lbry_file_reflector = task.LoopingCall(self.reflect_lbry_files)
        log.debug("Download directory for EncryptedFileManager: %s", str(self.download_directory))

    @defer.inlineCallbacks
    def setup(self):
        yield self.storage.open()
        downloader_factory = ManagedEncryptedFileDownloaderFactory(self)
        yield self.sd_identifier.add_stream_downloader_factory(EncryptedFileStreamType,
                                                               downloader_factory)
        yield self.start_lbry_files()
        safe_start_looping_call(self.lbry_file_reflector)

    @defer.inlineCallbacks
    def stop(self):
        safe_stop_looping_call(self.lbry_file_reflector)
        yield self.stop_lbry_files()
        yield self.storage.close()
        log.info("Stopped %s", self)

    @defer.inlineCallbacks
    def get_lbry_file_status(self, lbry_file):
        status = yield self.storage.get_lbry_file_status(lbry_file.rowid)
        defer.returnValue(status)

    @defer.inlineCallbacks
    def get_claim_metadata_for_file(self, lbry_file):
        outpoint = yield self.storage.get_outpoint_for_file(lbry_file.rowid)
        defer.returnValue(outpoint)

    @defer.inlineCallbacks
    def get_lbry_name_for_file(self, lbry_file):
        claim_out = yield self.storage.get_claimed_name_for_file(lbry_file.rowid)
        defer.returnValue(claim_out)

    @defer.inlineCallbacks
    def save_claim_to_file(self, lbry_file):
        outpoint = ClaimOutpoint(lbry_file.txid, lbry_file.nout)
        claim_row = yield self.storage.get_claim_row_id(outpoint)
        yield self.storage.save_claim_to_file(lbry_file.rowid, claim_row)

    @defer.inlineCallbacks
    def get_claim_status_for_file(self, lbry_file):
        status = yield self.storage.get_claim_status_for_file(lbry_file.rowid)
        defer.returnValue(status)

    @defer.inlineCallbacks
    def get_sd_hash_for_file(self, lbry_file):
        sd_hash = yield self.storage.get_sd_hash_for_file(lbry_file.rowid)
        defer.returnValue(sd_hash)

    @defer.inlineCallbacks
    def get_claim_id_for_file(self, lbry_file):
        claim_id = yield self.storage.get_claimid_for_tx(ClaimOutpoint(lbry_file.txid,
                                                                       lbry_file.nout))
        defer.returnValue(claim_id)

    @defer.inlineCallbacks
    def set_lbry_file_data_payment_rate(self, lbry_file, new_rate):
        yield self.storage.set_lbry_file_payment_rate(lbry_file.rowid, new_rate)

    @defer.inlineCallbacks
    def change_lbry_file_status(self, lbry_file, status):
        log.info("Changing status of %s (%s) to %s", lbry_file, lbry_file.stream_hash, status)
        yield self.storage.change_file_status(lbry_file.rowid, status)
        defer.returnValue(status)

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
        for lbry_file in self.lbry_files:
            if lbry_file.stream_hash == stream_hash:
                log.warning("A file for stream %s already exists", stream_hash)
                defer.returnValue(lbry_file)

        rowid = yield self.storage.save_lbry_file(stream_hash, blob_data_rate)
        log.info("Adding new file for stream %s", stream_hash)
        lbry_file = yield self.start_lbry_file(rowid, stream_hash, payment_rate_manager,
                                               blob_data_rate, download_directory,
                                               file_name)
        defer.returnValue(lbry_file)

    @defer.inlineCallbacks
    def delete_lbry_file(self, lbry_file, delete_file=True):
        stream_hash = lbry_file.stream_hash
        filename = os.path.join(self.download_directory, lbry_file.file_name)

        if lbry_file not in self.lbry_files:
            raise ValueError("Could not find that LBRY file")
        try:
            yield lbry_file.stop()
        except CurrentlyStoppingError:
            yield wait_for_finished(lbry_file)
        except AlreadyStoppedError:
            pass
        finally:
            yield lbry_file.delete_data()
            yield self.stream_info_manager.delete_stream(stream_hash)
            stream_count = yield self.stream_info_manager.get_count_for_stream(stream_hash)
            if stream_count:
                log.warning("Can't delete stream info for %s, count is %i", stream_hash,
                            stream_count)
            if delete_file:
                if os.path.isfile(filename):
                    os.remove(filename)
                    log.info("Deleted file %s", filename)
            log.info("Deleted stream %s", lbry_file.stream_hash)
            self.lbry_files.remove(lbry_file)

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
    def check_stream_is_managed(self, stream_hash):
        rowid = yield self.storage.get_file_row_id(stream_hash)
        if rowid:
            defer.returnValue(True)
        rate = self.session.base_payment_rate_manager.min_blob_data_payment_rate
        key, stream_name, file_name = yield self.stream_info_manager.get_stream_info(stream_hash)
        log.warning("Trying to fix missing lbry file for %s", stream_name.decode('hex'))
        yield self.storage.save_lbry_file(stream_hash, rate)
        defer.returnValue(None)

    @defer.inlineCallbacks
    def check_streams_are_managed(self):
        """
        check that all the streams in the stream_info_manager are also
        tracked by lbry_file_manager and fix any streams that aren't.
        """

        stream_hashes = yield self.stream_info_manager.get_all_streams()
        if stream_hashes:
            for stream_hash in stream_hashes:
                yield self.check_stream_is_managed(stream_hash)
        defer.returnValue(None)

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
        files_and_options = yield self.storage.get_all_lbry_files()
        if files_and_options:
            for rowid, stream_hash, options in files_and_options:
                yield self.set_options_and_restore(rowid, stream_hash, options)
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
