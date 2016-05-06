import logging
import os
import sys

from appdirs import user_data_dir
from datetime import datetime

from lbrynet.core.Error import InsufficientFundsError
from lbrynet.lbryfilemanager.LBRYFileCreator import create_lbry_file
from lbrynet.lbryfile.StreamDescriptor import publish_sd_blob
from lbrynet.core.PaymentRateManager import PaymentRateManager
from lbrynet.lbryfilemanager.LBRYFileDownloader import ManagedLBRYFileDownloader
from twisted.internet import threads, defer

if sys.platform != "darwin":
    log_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
else:
    log_dir = user_data_dir("LBRY")

if not os.path.isdir(log_dir):
    os.mkdir(log_dir)

LOG_FILENAME = os.path.join(log_dir, 'lbrynet-daemon.log')
log = logging.getLogger(__name__)
handler = logging.handlers.RotatingFileHandler(LOG_FILENAME, maxBytes=2097152, backupCount=5)
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
        self.thumbnail = None
        self.title = None
        self.publish_name = None
        self.bid_amount = None
        self.key_fee = None
        self.key_fee_address = None
        self.key_fee_address_chosen = False
        self.description = None
        self.verified = False
        self.lbry_file = None
        self.sd_hash = None
        self.tx_hash = None
        self.content_license = None
        self.author = None
        self.sources = None

    def start(self, name, file_path, bid, title=None, description=None, thumbnail=None,
              key_fee=None, key_fee_address=None, content_license=None, author=None, sources=None):

        def _show_result():
            message = "[" + str(datetime.now()) + "] Published " + self.file_name + " --> lbry://" + \
                        str(self.publish_name) + " with txid: " + str(self.tx_hash)
            log.info(message)
            return defer.succeed(self.tx_hash)

        self.publish_name = name
        self.file_path = file_path
        self.bid_amount = bid
        self.title = title
        self.description = description
        self.thumbnail = thumbnail
        self.key_fee = key_fee
        self.key_fee_address = key_fee_address
        self.content_license = content_license
        self.author = author
        self.sources = sources

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
            self.sd_hash = sd_hash

        d.addCallback(set_sd_hash)
        return d

    def _claim_name(self):
        d = self.wallet.claim_name(self.publish_name, self.sd_hash, self.bid_amount,
                                   description=self.description, key_fee=self.key_fee,
                                   key_fee_address=self.key_fee_address, thumbnail=self.thumbnail,
                                   content_license=self.content_license, author=self.author,
                                   sources=self.sources)

        def set_tx_hash(tx_hash):
            self.tx_hash = tx_hash

        d.addCallback(set_tx_hash)
        return d

    def _show_publish_error(self, err):
        log.info(err.getTraceback())
        message = "An error occurred publishing %s to %s. Error: %s."
        if err.check(InsufficientFundsError):
            error_message = "Insufficient funds"
        else:
            d = defer.succeed(True)
            error_message = err.getErrorMessage()
        log.error(error_message)
        log.error(message, str(self.file_name), str(self.publish_name), err.getTraceback())
        return d
