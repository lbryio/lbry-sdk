import logging
import os
from twisted.internet import defer
from twisted.internet.task import LoopingCall

from lbryschema.fee import Fee

from lbrynet.core.Error import InsufficientFundsError, KeyFeeAboveMaxAllowed
from lbrynet.core.StreamDescriptor import download_sd_blob
from lbrynet.lbryfilemanager.EncryptedFileDownloader import ManagedEncryptedFileDownloaderFactory
from lbrynet.lbryfilemanager.EncryptedFileDownloader import ManagedEncryptedFileDownloader
from lbrynet import conf

INITIALIZING_CODE = 'initializing'
DOWNLOAD_METADATA_CODE = 'downloading_metadata'
DOWNLOAD_TIMEOUT_CODE = 'timeout'
DOWNLOAD_RUNNING_CODE = 'running'
DOWNLOAD_STOPPED_CODE = 'stopped'
STREAM_STAGES = [
    (INITIALIZING_CODE, 'Initializing'),
    (DOWNLOAD_METADATA_CODE, 'Downloading metadata'),
    (DOWNLOAD_RUNNING_CODE, 'Started stream'),
    (DOWNLOAD_STOPPED_CODE, 'Paused stream'),
    (DOWNLOAD_TIMEOUT_CODE, 'Stream timed out')
]


log = logging.getLogger(__name__)


def safe_start(looping_call):
    if not looping_call.running:
        looping_call.start(1)


def safe_stop(looping_call):
    if looping_call.running:
        looping_call.stop()


class GetStream(object):
    def __init__(self, sd_identifier, session, exchange_rate_manager,
                 max_key_fee, data_rate=None, timeout=None, download_directory=None,
                 file_name=None):

        self.timeout = timeout or conf.settings['download_timeout']
        self.data_rate = data_rate or conf.settings['data_rate']
        self.max_key_fee = max_key_fee or conf.settings['max_key_fee'][1]
        self.download_directory = download_directory or conf.settings['download_directory']
        self.file_name = file_name
        self.timeout_counter = 0
        self.code = None
        self.sd_hash = None
        self.session = session
        self.wallet = self.session.wallet
        self.exchange_rate_manager = exchange_rate_manager
        self.payment_rate_manager = self.session.payment_rate_manager
        self.sd_identifier = sd_identifier
        self.downloader = None
        self.checker = LoopingCall(self.check_status)
        self.stream_info = None

        # fired when the download is complete
        self.finished_deferred = None
        # fired after the metadata and the first data blob have been downloaded
        self.data_downloading_deferred = defer.Deferred(None)


    @property
    def download_path(self):
        return os.path.join(self.download_directory, self.downloader.file_name)

    def _check_status(self, status):
        stop_condition = (status.num_completed > 0 or
                status.running_status == ManagedEncryptedFileDownloader.STATUS_STOPPED)

        if stop_condition and not self.data_downloading_deferred.called:
            self.data_downloading_deferred.callback(True)
        if self.data_downloading_deferred.called:
            safe_stop(self.checker)
        else:
            log.info("Downloading stream data (%i seconds)", self.timeout_counter)

    def check_status(self):
        """
        Check if we've got the first data blob in the stream yet
        """

        self.timeout_counter += 1
        if self.timeout_counter >= self.timeout:
            if not self.data_downloading_deferred.called:
                self.data_downloading_deferred.errback(Exception("Timeout"))
            safe_stop(self.checker)
        elif self.downloader:
            d = self.downloader.status()
            d.addCallback(self._check_status)
        else:
            log.info("Downloading stream descriptor blob (%i seconds)", self.timeout_counter)

    def convert_max_fee(self):
        currency, amount = self.max_key_fee['currency'], self.max_key_fee['amount']
        return self.exchange_rate_manager.convert_currency(currency, "LBC", amount)

    def set_status(self, status, name):
        log.info("Download lbry://%s status changed to %s" % (name, status))
        self.code = next(s for s in STREAM_STAGES if s[0] == status)

    def check_fee_and_convert(self, fee):
        max_key_fee_amount = self.convert_max_fee()
        converted_fee_amount = self.exchange_rate_manager.convert_currency(fee.currency, "LBC",
                                                                           fee.amount)
        if converted_fee_amount > self.wallet.get_balance():
            raise InsufficientFundsError('Unable to pay the key fee of %s' % converted_fee_amount)
        if converted_fee_amount > max_key_fee_amount:
            raise KeyFeeAboveMaxAllowed('Key fee %s above max allowed %s' % (converted_fee_amount,
                                                                             max_key_fee_amount))
        converted_fee = {
            'currency': 'LBC',
            'amount': converted_fee_amount,
            'address': fee.address
        }
        return Fee(converted_fee)

    def get_downloader_factory(self, factories):
        for factory in factories:
            if isinstance(factory, ManagedEncryptedFileDownloaderFactory):
                return factory
        raise Exception('No suitable factory was found in {}'.format(factories))

    @defer.inlineCallbacks
    def get_downloader(self, factory, stream_metadata):
        # TODO: we should use stream_metadata.options.get_downloader_options
        #       instead of hard-coding the options to be [self.data_rate]
        downloader = yield factory.make_downloader(
            self.stream_info
            stream_metadata,
            [self.data_rate],
            self.payment_rate_manager,
            download_directory=self.download_directory,
            file_name=self.file_name
        )
        defer.returnValue(downloader)

    def _pay_key_fee(self, address, fee_lbc, name):
        log.info("Pay key fee %f --> %s", fee_lbc, address)
        reserved_points = self.wallet.reserve_points(address, fee_lbc)
        if reserved_points is None:
            raise InsufficientFundsError('Unable to pay the key fee of %s for %s' % (fee_lbc, name))
        return self.wallet.send_points_to_address(reserved_points, fee_lbc)

    @defer.inlineCallbacks
    def pay_key_fee(self, fee, name):
        if fee is not None:
            yield self._pay_key_fee(fee.address, fee.amount, name)
        else:
            defer.returnValue(None)

    @defer.inlineCallbacks
    def finish(self, results, name):
        self.set_status(DOWNLOAD_STOPPED_CODE, name)
        log.info("Finished downloading lbry://%s (%s) --> %s", name, self.sd_hash[:6],
                 self.download_path)
        safe_stop(self.checker)
        status = yield self.downloader.status()
        self._check_status(status)
        defer.returnValue(self.download_path)

    @defer.inlineCallbacks
    def initialize(self, stream_info, name):
        # Set sd_hash and return key_fee from stream_info
        self.set_status(INITIALIZING_CODE, name)
        self.sd_hash = stream_info.source_hash
        key_fee = None
        if stream_info.has_fee:
            key_fee = yield self.check_fee_and_convert(stream_info.source_fee)
        defer.returnValue(key_fee)

    @defer.inlineCallbacks
    def _create_downloader(self, sd_blob):
        stream_metadata = yield self.sd_identifier.get_metadata_for_sd_blob(sd_blob)
        factory = self.get_downloader_factory(stream_metadata.factories)
        downloader = yield self.get_downloader(factory, stream_metadata)
        defer.returnValue(downloader)

    @defer.inlineCallbacks
    def download(self, name, key_fee):
        # download sd blob, and start downloader
        self.set_status(DOWNLOAD_METADATA_CODE, name)
        sd_blob = yield download_sd_blob(self.session, self.sd_hash, self.payment_rate_manager)
        self.downloader = yield self._create_downloader(sd_blob)

        self.set_status(DOWNLOAD_RUNNING_CODE, name)
        if key_fee:
            yield self.pay_key_fee(key_fee, name)

        log.info("Downloading lbry://%s (%s) --> %s", name, self.sd_hash[:6], self.download_path)
        self.finished_deferred = self.downloader.start()
        self.finished_deferred.addCallback(self.finish, name)

    @defer.inlineCallbacks
    def start(self, stream_info, name):
        """
        Start download

        Returns:
            (tuple) Tuple containing (downloader, finished_deferred)

            downloader - instance of ManagedEncryptedFileDownloader
            finished_deferred - deferred callbacked when download is finished
        """
        self.stream_info = stream_info
        key_fee = yield self.initialize(stream_info, name)
        safe_start(self.checker)

        try:
            yield self.download(name, key_fee)
        except Exception as err:
            safe_stop(self.checker)
            raise


        try:
            yield self.data_downloading_deferred
        except Exception as err:
            self.downloader.stop()
            safe_stop(self.checker)
            raise

        defer.returnValue((self.downloader, self.finished_deferred))

