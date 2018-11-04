import logging
import os
from twisted.internet import defer
from twisted.internet.task import LoopingCall

from lbrynet.daemon.Components import f2d
from lbrynet.schema.fee import Fee

from lbrynet.core.Error import InsufficientFundsError, KeyFeeAboveMaxAllowed, InvalidStreamDescriptorError
from lbrynet.core.Error import DownloadDataTimeout, DownloadCanceledError, DownloadSDTimeout
from lbrynet.core.utils import safe_start_looping_call, safe_stop_looping_call
from lbrynet.core.StreamDescriptor import download_sd_blob
from lbrynet.file_manager.EncryptedFileDownloader import ManagedEncryptedFileDownloaderFactory
from lbrynet import conf
from torba.client.constants import COIN
from lbrynet.extras.wallet.dewies import dewies_to_lbc

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


class GetStream:
    def __init__(self, sd_identifier, wallet, exchange_rate_manager, blob_manager, peer_finder, rate_limiter,
                 payment_rate_manager, storage, max_key_fee, disable_max_key_fee, data_rate=None, timeout=None):

        self.timeout = timeout or conf.settings['download_timeout']
        self.data_rate = data_rate or conf.settings['data_rate']
        self.max_key_fee = max_key_fee or conf.settings['max_key_fee'][1]
        self.disable_max_key_fee = disable_max_key_fee or conf.settings['disable_max_key_fee']
        self.download_directory = conf.settings['download_directory']
        self.timeout_counter = 0
        self.code = None
        self.sd_hash = None
        self.blob_manager = blob_manager
        self.peer_finder = peer_finder
        self.rate_limiter = rate_limiter
        self.wallet = wallet
        self.exchange_rate_manager = exchange_rate_manager
        self.payment_rate_manager = payment_rate_manager
        self.sd_identifier = sd_identifier
        self.storage = storage
        self.downloader = None
        self.checker = LoopingCall(self.check_status)

        # fired when the download is complete
        self.finished_deferred = None
        # fired after the metadata and the first data blob have been downloaded
        self.data_downloading_deferred = defer.Deferred(None)

    @property
    def download_path(self):
        return os.path.join(self.download_directory, self.downloader.file_name)

    def _check_status(self, status):
        if status.num_completed > 0 and not self.data_downloading_deferred.called:
            self.data_downloading_deferred.callback(True)
        if self.data_downloading_deferred.called:
            safe_stop_looping_call(self.checker)
        else:
            log.debug("Waiting for stream data (%i seconds)", self.timeout_counter)

    def check_status(self):
        """
        Check if we've got the first data blob in the stream yet
        """
        self.timeout_counter += 1
        if self.timeout_counter > self.timeout:
            if not self.data_downloading_deferred.called:
                if self.downloader:
                    err = DownloadDataTimeout(self.sd_hash)
                else:
                    err = DownloadSDTimeout(self.sd_hash)
                self.data_downloading_deferred.errback(err)
            safe_stop_looping_call(self.checker)
        elif self.downloader:
            d = self.downloader.status()
            d.addCallback(self._check_status)
        else:
            log.debug("Waiting for stream descriptor (%i seconds)", self.timeout_counter)

    def convert_max_fee(self):
        currency, amount = self.max_key_fee['currency'], self.max_key_fee['amount']
        return self.exchange_rate_manager.convert_currency(currency, "LBC", amount)

    def set_status(self, status, name):
        log.info("Download lbry://%s status changed to %s" % (name, status))
        self.code = next(s for s in STREAM_STAGES if s[0] == status)

    @defer.inlineCallbacks
    def check_fee_and_convert(self, fee):
        max_key_fee_amount = self.convert_max_fee()
        converted_fee_amount = self.exchange_rate_manager.convert_currency(fee.currency, "LBC",
                                                                           fee.amount)
        if converted_fee_amount > (yield f2d(self.wallet.default_account.get_balance())):
            raise InsufficientFundsError('Unable to pay the key fee of %s' % converted_fee_amount)
        if converted_fee_amount > max_key_fee_amount and not self.disable_max_key_fee:
            raise KeyFeeAboveMaxAllowed('Key fee {} above max allowed {}'.format(converted_fee_amount,
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
        raise Exception(f'No suitable factory was found in {factories}')

    @defer.inlineCallbacks
    def get_downloader(self, factory, stream_metadata, file_name=None):
        # TODO: we should use stream_metadata.options.get_downloader_options
        #       instead of hard-coding the options to be [self.data_rate]
        downloader = yield factory.make_downloader(
            stream_metadata,
            self.data_rate,
            self.payment_rate_manager,
            self.download_directory,
            file_name=file_name
        )
        defer.returnValue(downloader)

    def _pay_key_fee(self, address, fee_lbc, name):
        log.info("Pay key fee %s --> %s", dewies_to_lbc(fee_lbc), address)
        reserved_points = self.wallet.reserve_points(address, fee_lbc)
        if reserved_points is None:
            raise InsufficientFundsError(
                'Unable to pay the key fee of {} for {}'.format(dewies_to_lbc(fee_lbc), name)
            )
        return f2d(self.wallet.send_points_to_address(reserved_points, fee_lbc))

    @defer.inlineCallbacks
    def pay_key_fee(self, fee, name):
        if fee is not None:
            yield self._pay_key_fee(fee.address.decode(), int(fee.amount * COIN), name)
        else:
            defer.returnValue(None)

    @defer.inlineCallbacks
    def finish(self, results, name):
        self.set_status(DOWNLOAD_STOPPED_CODE, name)
        log.info("Finished downloading lbry://%s (%s) --> %s", name, self.sd_hash[:6],
                 self.download_path)
        safe_stop_looping_call(self.checker)
        status = yield self.downloader.status()
        self._check_status(status)
        defer.returnValue(self.download_path)

    def fail(self, err):
        safe_stop_looping_call(self.checker)
        raise err

    @defer.inlineCallbacks
    def _initialize(self, stream_info):
        # Set sd_hash and return key_fee from stream_info
        self.sd_hash = stream_info.source_hash.decode()
        key_fee = None
        if stream_info.has_fee:
            key_fee = yield self.check_fee_and_convert(stream_info.source_fee)
        defer.returnValue(key_fee)

    @defer.inlineCallbacks
    def _create_downloader(self, sd_blob, file_name=None):
        stream_metadata = yield self.sd_identifier.get_metadata_for_sd_blob(sd_blob)
        factory = self.get_downloader_factory(stream_metadata.factories)
        downloader = yield self.get_downloader(factory, stream_metadata, file_name)
        defer.returnValue(downloader)

    @defer.inlineCallbacks
    def _download_sd_blob(self):
        sd_blob = yield download_sd_blob(
            self.sd_hash, self.blob_manager, self.peer_finder, self.rate_limiter, self.payment_rate_manager,
            self.wallet, self.timeout, conf.settings['download_mirrors']
        )
        defer.returnValue(sd_blob)

    @defer.inlineCallbacks
    def _download(self, sd_blob, name, key_fee, txid, nout, file_name=None):
        self.downloader = yield self._create_downloader(sd_blob, file_name=file_name)
        yield self.pay_key_fee(key_fee, name)
        yield self.storage.save_content_claim(self.downloader.stream_hash, "%s:%i" % (txid, nout))
        log.info("Downloading lbry://%s (%s) --> %s", name, self.sd_hash[:6], self.download_path)
        self.finished_deferred = self.downloader.start()
        self.finished_deferred.addCallbacks(lambda result: self.finish(result, name), self.fail)

    @defer.inlineCallbacks
    def start(self, stream_info, name, txid, nout, file_name=None):
        """
        Start download

        Returns:
            (tuple) Tuple containing (downloader, finished_deferred)

            downloader - instance of ManagedEncryptedFileDownloader
            finished_deferred - deferred callbacked when download is finished
        """
        self.set_status(INITIALIZING_CODE, name)
        key_fee = yield self._initialize(stream_info)

        safe_start_looping_call(self.checker, 1)
        self.set_status(DOWNLOAD_METADATA_CODE, name)
        try:
            sd_blob = yield self._download_sd_blob()
            yield self._download(sd_blob, name, key_fee, txid, nout, file_name)
            self.set_status(DOWNLOAD_RUNNING_CODE, name)
            yield self.data_downloading_deferred
        except (DownloadDataTimeout, InvalidStreamDescriptorError) as err:
            safe_stop_looping_call(self.checker)
            raise err

        defer.returnValue((self.downloader, self.finished_deferred))

    def cancel(self, reason=None):
        if reason:
            msg = "download stream cancelled: %s" % reason
        else:
            msg = "download stream cancelled"
        if self.data_downloading_deferred and not self.data_downloading_deferred.called:
            self.data_downloading_deferred.errback(DownloadCanceledError(msg))
