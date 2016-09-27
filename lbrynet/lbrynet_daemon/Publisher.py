import logging
import mimetypes
import os
import sys
import random

from appdirs import user_data_dir

from lbrynet.core.Error import InsufficientFundsError
from lbrynet.lbryfilemanager.EncryptedFileCreator import create_lbry_file
from lbrynet.lbryfile.StreamDescriptor import publish_sd_blob
from lbrynet.core.PaymentRateManager import PaymentRateManager
from lbrynet.metadata.Metadata import Metadata
from lbrynet.lbryfilemanager.EncryptedFileDownloader import ManagedEncryptedFileDownloader
from lbrynet import reflector
from lbrynet.conf import LOG_FILE_NAME, REFLECTOR_SERVERS
from twisted.internet import threads, defer, reactor

if sys.platform != "darwin":
    log_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
else:
    log_dir = user_data_dir("LBRY")

if not os.path.isdir(log_dir):
    os.mkdir(log_dir)

lbrynet_log = os.path.join(log_dir, LOG_FILE_NAME)
log = logging.getLogger(__name__)


class Publisher(object):
    def __init__(self, session, lbry_file_manager, wallet):
        self.session = session
        self.lbry_file_manager = lbry_file_manager
        self.wallet = wallet
        self.received_file_name = False
        self.file_path = None
        self.file_name = None
        self.publish_name = None
        self.bid_amount = None
        self.verified = False
        self.lbry_file = None
        self.txid = None
        self.stream_hash = None
        reflector_server = random.choice(REFLECTOR_SERVERS)
        self.reflector_server, self.reflector_port = reflector_server[0], reflector_server[1]
        self.metadata = {}

    def start(self, name, file_path, bid, metadata):
        log.info('Starting publish for %s', name)
        def _show_result():
            log.info("Success! Published %s --> lbry://%s txid: %s", self.file_name, self.publish_name, self.txid)
            return defer.succeed(self.txid)

        self.publish_name = name
        self.file_path = file_path
        self.bid_amount = bid
        self.metadata = metadata

        if os.name == "nt":
            file_mode = 'rb'
        else:
            file_mode = 'r'

        d = self._check_file_path(self.file_path)
        d.addCallback(lambda _: create_lbry_file(self.session, self.lbry_file_manager,
                                                 self.file_name, open(self.file_path, file_mode)))
        d.addCallback(self.add_to_lbry_files)
        d.addCallback(lambda _: self._create_sd_blob())
        d.addCallback(lambda _: self._claim_name())
        d.addCallback(lambda _: self.set_status())
        d.addCallback(lambda _: self.start_reflector())
        d.addCallbacks(lambda _: _show_result(), self._show_publish_error)

        return d

    def start_reflector(self):
        reflector_server = random.choice(REFLECTOR_SERVERS)
        reflector_address, reflector_port = reflector_server[0], reflector_server[1]
        log.info("Reflecting new publication")
        factory = reflector.ClientFactory(
            self.session.blob_manager,
            self.lbry_file_manager.stream_info_manager,
            self.stream_hash
        )
        d = reactor.resolve(reflector_address)
        d.addCallback(lambda ip: reactor.connectTCP(ip, reflector_port, factory))
        d.addCallback(lambda _: factory.finished_deferred)
        return d

    def _check_file_path(self, file_path):
        def check_file_threaded():
            f = open(file_path)
            f.close()
            self.file_name = os.path.basename(self.file_path)
            return True
        return threads.deferToThread(check_file_threaded)

    def set_lbry_file(self, lbry_file_downloader):
        self.lbry_file = lbry_file_downloader
        return defer.succeed(None)

    def add_to_lbry_files(self, stream_hash):
        self.stream_hash = stream_hash
        prm = PaymentRateManager(self.session.base_payment_rate_manager)
        d = self.lbry_file_manager.add_lbry_file(stream_hash, prm)
        d.addCallback(self.set_lbry_file)
        return d

    def _create_sd_blob(self):
        log.debug('Creating stream descriptor blob')
        d = publish_sd_blob(self.lbry_file_manager.stream_info_manager,
                            self.session.blob_manager,
                            self.lbry_file.stream_hash)

        def set_sd_hash(sd_hash):
            log.debug('stream descriptor hash: %s', sd_hash)
            if 'sources' not in self.metadata:
                self.metadata['sources'] = {}
            self.metadata['sources']['lbry_sd_hash'] = sd_hash

        d.addCallback(set_sd_hash)
        return d

    def set_status(self):
        log.debug('Setting status')
        d = self.lbry_file_manager.change_lbry_file_status(self.lbry_file, ManagedEncryptedFileDownloader.STATUS_FINISHED)
        d.addCallback(lambda _: self.lbry_file.restore())
        return d

    def _claim_name(self):
        log.debug('Claiming name')
        self._update_metadata()
        m = Metadata(self.metadata)

        def set_tx_hash(txid):
            log.debug('Name claimed using txid: %s', txid)
            self.txid = txid

        d = self.wallet.claim_name(self.publish_name, self.bid_amount, m)
        d.addCallback(set_tx_hash)
        return d

    def _update_metadata(self):
        filename = os.path.join(self.lbry_file.download_directory, self.lbry_file.file_name)
        self.metadata['content_type'] = get_content_type(filename)
        self.metadata['ver'] = Metadata.current_version

    def _show_publish_error(self, err):
        log.info(err.getTraceback())
        message = "An error occurred publishing %s to %s. Error: %s."
        if err.check(InsufficientFundsError):
            error_message = "Insufficient funds"
        else:
            error_message = err.getErrorMessage()

        log.error(error_message)
        log.error(message, str(self.file_name), str(self.publish_name), err.getTraceback())

        return defer.fail(Exception("Publish failed"))


def get_content_type(filename):
    return mimetypes.guess_type(filename)[0]
