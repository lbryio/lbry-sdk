import logging
import mimetypes
import os
import sys

from appdirs import user_data_dir
from datetime import datetime

from lbrynet.core.Error import InsufficientFundsError
from lbrynet.lbryfilemanager.LBRYFileCreator import create_lbry_file
from lbrynet.lbryfile.StreamDescriptor import publish_sd_blob
from lbrynet.core.PaymentRateManager import PaymentRateManager
from lbrynet.lbryfilemanager.LBRYFileDownloader import ManagedLBRYFileDownloader
from lbrynet.conf import LOG_FILE_NAME
from twisted.internet import threads, defer

if sys.platform != "darwin":
    log_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
else:
    log_dir = user_data_dir("LBRY")

if not os.path.isdir(log_dir):
    os.mkdir(log_dir)

lbrynet_log = os.path.join(log_dir, LOG_FILE_NAME)
log = logging.getLogger(__name__)
handler = logging.handlers.RotatingFileHandler(lbrynet_log, maxBytes=2097152, backupCount=5)
log.addHandler(handler)
log.setLevel(logging.INFO)


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
        self.sources = {}
        self.fee = None

    def start(self, name, file_path, bid, metadata, fee=None, sources={}):

        def _show_result():

            message = "[%s] Published %s --> lbry://%s txid: %s" % (datetime.now(), self.file_name, self.publish_name, self.txid)
            log.info(message)
            return defer.succeed(self.txid)

        self.publish_name = name
        self.file_path = file_path
        self.bid_amount = bid
        self.fee = fee
        self.metadata = metadata

        d = self._check_file_path(self.file_path)
        d.addCallback(lambda _: create_lbry_file(self.session, self.lbry_file_manager,
                                                 self.file_name, open(self.file_path)))
        d.addCallback(self.add_to_lbry_files)
        d.addCallback(lambda _: self._create_sd_blob())
        d.addCallback(lambda _: self._claim_name())
        d.addCallbacks(lambda _: _show_result(), self._show_publish_error)

        return d

    def _check_file_path(self, file_path):
        def check_file_threaded():
            f = open(file_path)
            f.close()
            self.file_name = os.path.basename(self.file_path)
            return True
        return threads.deferToThread(check_file_threaded)

    def _get_new_address(self):
        d = self.wallet.get_new_address()

        def set_address(address):
            self.key_fee_address = address
            return True

        d.addCallback(set_address)
        return d

    def set_status(self, lbry_file_downloader):
        self.lbry_file = lbry_file_downloader
        d = self.lbry_file_manager.change_lbry_file_status(self.lbry_file, ManagedLBRYFileDownloader.STATUS_FINISHED)
        d.addCallback(lambda _: lbry_file_downloader.restore())
        return d

    def add_to_lbry_files(self, stream_hash):
        prm = PaymentRateManager(self.session.base_payment_rate_manager)
        d = self.lbry_file_manager.add_lbry_file(stream_hash, prm)
        d.addCallback(self.set_status)
        return d

    def _create_sd_blob(self):
        d = publish_sd_blob(self.lbry_file_manager.stream_info_manager, self.session.blob_manager,
                            self.lbry_file.stream_hash)

        def set_sd_hash(sd_hash):
            self.sources['lbry_sd_hash'] = sd_hash

        d.addCallback(set_sd_hash)
        return d

    def _claim_name(self):
        self.metadata['content-type'] = mimetypes.guess_type(os.path.join(self.lbry_file.download_directory,
                                                                          self.lbry_file.file_name))[0]
        d = self.wallet.claim_name(self.publish_name,
                                   self.bid_amount,
                                   self.sources,
                                   self.metadata,
                                   fee=self.fee)
        def set_tx_hash(txid):
            self.txid = txid

        d.addCallback(set_tx_hash)
        return d

    def _show_publish_error(self, err):
        log.info(err.getTraceback())
        message = "An error occurred publishing %s to %s. Error: %s."
        if err.check(InsufficientFundsError):
            error_message = "Insufficient funds"
        else:
            error_message = err.getErrorMessage()

        log.error(error_message)
        log.error(message, str(self.file_name), str(self.publish_name), err.getTraceback())

        return defer.succeed(error_message)
