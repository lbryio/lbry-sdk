import json
import logging
import os
import sys

from copy import deepcopy
from appdirs import user_data_dir
from datetime import datetime
from twisted.internet import defer
from twisted.internet.task import LoopingCall

from lbrynet.core.Error import InvalidStreamInfoError, InsufficientFundsError, KeyFeeAboveMaxAllowed
from lbrynet.core.PaymentRateManager import PaymentRateManager
from lbrynet.core.StreamDescriptor import download_sd_blob
from lbrynet.core.LBRYMetadata import Metadata, LBRYFee
from lbrynet.lbryfilemanager.LBRYFileDownloader import ManagedLBRYFileDownloaderFactory
from lbrynet.conf import DEFAULT_TIMEOUT, LOG_FILE_NAME

INITIALIZING_CODE = 'initializing'
DOWNLOAD_METADATA_CODE = 'downloading_metadata'
DOWNLOAD_TIMEOUT_CODE = 'timeout'
DOWNLOAD_RUNNING_CODE = 'running'
DOWNLOAD_STOPPED_CODE = 'stopped'
STREAM_STAGES = [
                    (INITIALIZING_CODE, 'Initializing...'),
                    (DOWNLOAD_METADATA_CODE, 'Downloading metadata'),
                    (DOWNLOAD_RUNNING_CODE, 'Started stream'),
                    (DOWNLOAD_STOPPED_CODE, 'Paused stream'),
                    (DOWNLOAD_TIMEOUT_CODE, 'Stream timed out')
                ]

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

class GetStream(object):
    def __init__(self, sd_identifier, session, wallet, lbry_file_manager, max_key_fee, data_rate=0.5,
                                    timeout=DEFAULT_TIMEOUT, download_directory=None, file_name=None):
        self.wallet = wallet
        self.resolved_name = None
        self.description = None
        self.fee = None
        self.data_rate = data_rate
        self.name = None
        self.file_name = file_name
        self.session = session
        self.payment_rate_manager = PaymentRateManager(self.session.base_payment_rate_manager)
        self.lbry_file_manager = lbry_file_manager
        self.sd_identifier = sd_identifier
        self.stream_hash = None
        self.max_key_fee = max_key_fee
        self.stream_info = None
        self.stream_info_manager = None
        self.d = defer.Deferred(None)
        self.timeout = timeout
        self.timeout_counter = 0
        self.download_directory = download_directory
        self.download_path = None
        self.downloader = None
        self.finished = defer.Deferred(None)
        self.checker = LoopingCall(self.check_status)
        self.code = STREAM_STAGES[0]

    def check_status(self):
        self.timeout_counter += 1

        # TODO: Why is this the stopping condition for the finished callback?
        if self.download_path:
            self.checker.stop()
            self.finished.callback((self.stream_hash, self.download_path))

        elif self.timeout_counter >= self.timeout:
            log.info("Timeout downloading lbry://%s" % self.resolved_name)
            self.checker.stop()
            self.d.cancel()
            self.code = STREAM_STAGES[4]
            self.finished.callback(False)

    def start(self, stream_info, name):
        self.resolved_name = name
        self.stream_info = deepcopy(stream_info)
        self.description = self.stream_info['description']
        self.stream_hash = self.stream_info['sources']['lbry_sd_hash']

        if 'fee' in self.stream_info:
            self.fee = LBRYFee(self.stream_info['fee'], {'USDBTC': self.wallet._USDBTC, 'BTCLBC': self.wallet._BTCLBC})
            if isinstance(self.max_key_fee, float):
                if self.fee.to_lbc() > self.max_key_fee:
                    log.info("Key fee %f above limit of %f didn't download lbry://%s" % (self.fee.to_lbc(), self.max_key_fee, self.resolved_name))
                    return defer.fail(KeyFeeAboveMaxAllowed())
                log.info("Key fee %f below limit of %f, downloading lbry://%s" % (self.fee.to_lbc(), self.max_key_fee, self.resolved_name))
            elif isinstance(self.max_key_fee, dict):
                max_key = LBRYFee(deepcopy(self.max_key_fee), {'USDBTC': self.wallet._USDBTC, 'BTCLBC': self.wallet._BTCLBC})
                if self.fee.to_lbc() > max_key.to_lbc():
                    log.info("Key fee %f above limit of %f didn't download lbry://%s" % (self.fee.to_lbc(), max_key.to_lbc(), self.resolved_name))
                    return defer.fail(KeyFeeAboveMaxAllowed())
                log.info("Key fee %f below limit of %f, downloading lbry://%s" % (self.fee.to_lbc(), max_key.to_lbc(), self.resolved_name))

        def _cause_timeout(err):
            log.error(err)
            log.debug('Forcing a timeout')
            self.timeout_counter = self.timeout * 2

        def _set_status(x, status):
            log.info("Download lbry://%s status changed to %s" % (self.resolved_name, status))
            self.code = next(s for s in STREAM_STAGES if s[0] == status)
            return x

        def get_downloader_factory(metadata):
            for factory in metadata.factories:
                if isinstance(factory, ManagedLBRYFileDownloaderFactory):
                    return factory, metadata
            raise Exception('No suitable factory was found in {}'.format(metadata.factories))

        def make_downloader(args):
            factory, metadata = args
            return factory.make_downloader(metadata,
                                           [self.data_rate, True],
                                           self.payment_rate_manager,
                                           download_directory=self.download_directory,
                                           file_name=self.file_name)

        self.checker.start(1)

        self.d.addCallback(lambda _: _set_status(None, DOWNLOAD_METADATA_CODE))
        self.d.addCallback(lambda _: download_sd_blob(self.session, self.stream_hash, self.payment_rate_manager))
        self.d.addCallback(self.sd_identifier.get_metadata_for_sd_blob)
        self.d.addCallback(lambda r: _set_status(r, DOWNLOAD_RUNNING_CODE))
        self.d.addCallback(get_downloader_factory)
        self.d.addCallback(make_downloader)
        self.d.addCallbacks(self._start_download, _cause_timeout)
        self.d.callback(None)

        return self.finished

    def _start_download(self, downloader):
        def _pay_key_fee():
            if self.fee is not None:
                fee_lbc = float(self.fee.to_lbc())
                reserved_points = self.wallet.reserve_points(self.fee.address, fee_lbc)
                if reserved_points is None:
                    return defer.fail(InsufficientFundsError())
                return self.wallet.send_points_to_address(reserved_points, fee_lbc)

            return defer.succeed(None)

        d = _pay_key_fee()

        self.downloader = downloader
        self.download_path = os.path.join(downloader.download_directory, downloader.file_name)

        d.addCallback(lambda _: log.info("Downloading %s --> %s", self.stream_hash, self.downloader.file_name))
        d.addCallback(lambda _: self.downloader.start())

