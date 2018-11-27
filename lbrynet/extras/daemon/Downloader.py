import logging
import os
from twisted.internet import defer

from lbrynet import conf
from lbrynet.schema.fee import Fee

from lbrynet.p2p.Error import InsufficientFundsError, KeyFeeAboveMaxAllowed, InvalidStreamDescriptorError
from lbrynet.p2p.Error import DownloadDataTimeout, DownloadCanceledError
from lbrynet.p2p.StreamDescriptor import download_sd_blob
from lbrynet.blob.EncryptedFileDownloader import ManagedEncryptedFileDownloaderFactory
from torba.client.constants import COIN
from lbrynet.extras.wallet.dewies import dewies_to_lbc
from lbrynet.extras.daemon.Components import f2d

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
                 payment_rate_manager, storage, max_key_fee, data_rate=None, timeout=None,
                 reactor=None):
        if not reactor:
            from twisted.internet import reactor
        self.reactor = reactor
        self.timeout = timeout or conf.settings['download_timeout']
        self.data_rate = data_rate or conf.settings['data_rate']
        self.max_key_fee = max_key_fee or conf.settings['max_key_fee'][1]
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

        # fired when the download is complete
        self.finished_deferred = None
        # fired after the metadata and the first data blob have been downloaded
        self.data_downloading_deferred = defer.Deferred(None)
        self.wrote_data = False

    @property
    def download_path(self):
        return os.path.join(self.download_directory, self.downloader.file_name)

    def set_status(self, status, name):
        log.info("Download lbry://%s status changed to %s" % (name, status))
        self.code = next(s for s in STREAM_STAGES if s[0] == status)

    @defer.inlineCallbacks
    def check_fee_and_convert(self, fee):
        from_currency = self.max_key_fee['currency']
        to_currency = 'LBC'
        amount = self.max_key_fee['amount']

        convert_fee = self.exchange_rate_manager.convert_currency
        max_key_fee_amount = convert_fee(from_currency,
                                         to_currency,
                                         amount)
        converted_fee_amount = convert_fee(fee.currency,
                                           to_currency,
                                           fee.amount)

        if converted_fee_amount > (yield f2d(self.wallet.default_account.get_balance())):
            raise InsufficientFundsError('Unable to pay the key fee of %s' % converted_fee_amount)
        if converted_fee_amount > max_key_fee_amount and amount >= 0:
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

    def finish(self, results, name):
        self.set_status(DOWNLOAD_STOPPED_CODE, name)
        log.info("Finished downloading lbry://%s (%s) --> %s", name, self.sd_hash[:6],
                 self.download_path)
        return defer.succeed(self.download_path)

    def fail(self, err):
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
        self.finished_deferred = self.downloader.start()
        self.downloader.download_manager.progress_manager.wrote_first_data.addCallback(
            self.data_downloading_deferred.callback
        )
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
        self.set_status(DOWNLOAD_METADATA_CODE, name)
        try:
            sd_blob = yield self._download_sd_blob()
            yield self._download(sd_blob, name, key_fee, txid, nout, file_name)
            self.set_status(DOWNLOAD_RUNNING_CODE, name)
            log.info("Downloading lbry://%s (%s) --> %s", name, self.sd_hash[:6], self.download_path)
            self.data_downloading_deferred.addTimeout(self.timeout, self.reactor)
            try:
                yield self.data_downloading_deferred
                self.wrote_data = True
            except defer.TimeoutError:
                raise DownloadDataTimeout("data download timed out")
        except (DownloadDataTimeout, InvalidStreamDescriptorError) as err:
            raise err

        defer.returnValue((self.downloader, self.finished_deferred))

    def cancel(self, reason=None):
        if reason:
            msg = "download stream cancelled: %s" % reason
        else:
            msg = "download stream cancelled"
        if self.data_downloading_deferred and not self.data_downloading_deferred.called:
            self.data_downloading_deferred.errback(DownloadCanceledError(msg))
