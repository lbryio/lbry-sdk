import logging
import os
from twisted.internet import defer
from twisted.internet.task import LoopingCall

from lbrynet.core.Error import InsufficientFundsError, KeyFeeAboveMaxAllowed
from lbrynet.core.StreamDescriptor import download_sd_blob
from lbrynet.metadata.Fee import FeeValidator
from lbrynet.lbryfilemanager.EncryptedFileDownloader import ManagedEncryptedFileDownloaderFactory
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
    def __init__(self, sd_identifier, session, wallet, lbry_file_manager, exchange_rate_manager,
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
        self.wallet = wallet
        self.session = session
        self.exchange_rate_manager = exchange_rate_manager
        self.payment_rate_manager = self.session.payment_rate_manager
        self.lbry_file_manager = lbry_file_manager
        self.sd_identifier = sd_identifier
        self.downloader = None
        self.checker = LoopingCall(self.check_status)

        # fired when the download is complete
        self.finished_deferred = defer.Deferred(None)
        # fired after the metadata and the first data blob have been downloaded
        self.data_downloading_deferred = defer.Deferred(None)

    @property
    def download_path(self):
        return os.path.join(self.download_directory, self.downloader.file_name)

    def _check_status(self, status):
        if status.num_completed and not self.data_downloading_deferred.called:
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
        max_fee = FeeValidator(self.max_key_fee)
        if max_fee.currency_symbol == "LBC":
            return max_fee.amount
        return self.exchange_rate_manager.to_lbc(self.max_key_fee).amount

    def set_status(self, status, name):
        log.info("Download lbry://%s status changed to %s" % (name, status))
        self.code = next(s for s in STREAM_STAGES if s[0] == status)

    def check_fee(self, fee):
        validated_fee = FeeValidator(fee)
        max_key_fee = self.convert_max_fee()
        converted_fee = self.exchange_rate_manager.to_lbc(validated_fee).amount
        if converted_fee > self.wallet.get_balance():
            raise InsufficientFundsError('Unable to pay the key fee of %s' % converted_fee)
        if converted_fee > max_key_fee:
            raise KeyFeeAboveMaxAllowed('Key fee %s above max allowed %s' % (converted_fee,
                                                                             max_key_fee))
        return validated_fee

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
            fee_lbc = self.exchange_rate_manager.to_lbc(fee).amount
            yield self._pay_key_fee(fee.address, fee_lbc, name)
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
    def download(self, stream_info, name, txid, nout):
        self.set_status(INITIALIZING_CODE, name)
        self.sd_hash = stream_info['sources']['lbry_sd_hash']
        if 'fee' in stream_info:
            fee = self.check_fee(stream_info['fee'])
        else:
            fee = None

        self.set_status(DOWNLOAD_METADATA_CODE, name)
        sd_blob = yield download_sd_blob(self.session, self.sd_hash, self.payment_rate_manager)
        stream_metadata = yield self.sd_identifier.get_metadata_for_sd_blob(sd_blob)
        factory = self.get_downloader_factory(stream_metadata.factories)
        self.downloader = yield self.get_downloader(factory, stream_metadata)
        yield self.downloader.set_claim(name, txid, nout)
        yield self.downloader.load_file_attributes()
        self.set_status(DOWNLOAD_RUNNING_CODE, name)
        if fee:
            yield self.pay_key_fee(fee, name)
        log.info("Downloading lbry://%s (%s) --> %s", name, self.sd_hash[:6], self.download_path)
        self.finished_deferred = self.downloader.start()
        self.finished_deferred.addCallback(self.finish, name)

    @defer.inlineCallbacks
    def start(self, stream_info, name, txid, nout):
        try:
            safe_start(self.checker)
            self.download(stream_info, name, txid, nout)
            yield self.data_downloading_deferred
            defer.returnValue(self.download_path)
        except Exception as err:
            safe_stop(self.checker)
            raise err
