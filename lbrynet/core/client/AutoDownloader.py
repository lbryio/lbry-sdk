import json
import logging
from twisted.internet import defer
from twisted.internet.task import LoopingCall
from lbrynet.core.Error import InvalidStreamInfoError, InsufficientFundsError
from lbrynet.core.PaymentRateManager import PaymentRateManager
from lbrynet.core.StreamDescriptor import download_sd_blob

log = logging.getLogger(__name__)


class AutoAddStreamFromLBRYcrdName(object):
    def __init__(self, console, sd_identifier, session, wallet, lbry_file_manager):
        self.finished_deferred = defer.Deferred(None)
        self.console = console
        self.wallet = wallet
        self.resolved_name = None
        self.description = None
        self.key_fee = None
        self.key_fee_address = None
        self.name = None
        self.session = session
        self.payment_rate_manager = PaymentRateManager(self.session.base_payment_rate_manager)
        self.loading_metadata_deferred = defer.Deferred()
        self.lbry_file_manager = lbry_file_manager
        self.sd_identifier = sd_identifier
        self.metadata = None
        self.loading_failed = False
        self.resolved_name = None
        self.description = None
        self.key_fee = None
        self.key_fee_address = None
        self.stream_hash = None

    def start(self, stream_info):
        self.stream_info = stream_info
        if 'stream_hash' not in json.loads(self.stream_info['value']):
            print 'InvalidStreamInfoError'
            raise InvalidStreamInfoError(self.stream_info)
        self.resolved_name = self.stream_info.get('name', None)
        self.description = json.loads(self.stream_info['value']).get('description', None)
        try:
            if 'key_fee' in json.loads(self.stream_info['value']):
                self.key_fee = float(json.loads(self.stream_info['value'])['key_fee'])
        except ValueError:
            self.key_fee = None
        self.key_fee_address = json.loads(self.stream_info['value']).get('key_fee_address', None)
        self.stream_hash = json.loads(self.stream_info['value'])['stream_hash']


        self.loading_metadata_deferred = defer.Deferred(None)
        self.loading_metadata_deferred.addCallback(lambda _: download_sd_blob(self.session,
                                                            self.stream_hash, self.payment_rate_manager))
        self.loading_metadata_deferred.addCallback(self.sd_identifier.get_metadata_for_sd_blob)
        self.loading_metadata_deferred.addCallback(self._handle_metadata)
        self.loading_metadata_deferred.addErrback(self._handle_load_canceled)
        self.loading_metadata_deferred.addErrback(self._handle_load_failed)

        self.finished_deferred.addCallback(lambda _: self.loading_metadata_deferred.callback(None))

        return self.finished_deferred.callback(None)

    def _start_download(self):
        d = self._pay_key_fee()
        d.addCallback(lambda _: self._make_downloader())
        d.addCallback(lambda stream_downloader: stream_downloader.start())
        d.addErrback(self._handle_download_error)
        return d

    def _pay_key_fee(self):
        if self.key_fee is not None and self.key_fee_address is not None:
            reserved_points = self.wallet.reserve_points(self.key_fee_address, self.key_fee)
            if reserved_points is None:
                return defer.fail(InsufficientFundsError())
            return self.wallet.send_points_to_address(reserved_points, self.key_fee)
        self.console.sendLine("Sent key fee" + str(self.key_fee_address) + " | " + str(self.key_fee))
        return defer.succeed(None)

    def _handle_load_canceled(self, err):
        err.trap(defer.CancelledError)
        self.finished_deferred.callback(None)

    def _handle_load_failed(self, err):
        self.loading_failed = True
        self.console.sendLine("handle load failed: " + str(err.getTraceback()))
        log.error("An exception occurred attempting to load the stream descriptor: %s", err.getTraceback())
        self.finished_deferred.callback(None)

    def _handle_metadata(self, metadata):
        self.metadata = metadata
        self.factory = self.metadata.factories[0]
        self.finished_deferred.addCallback(lambda _: self._start_download())

    def _handle_download_error(self, err):
        if err.check(InsufficientFundsError):
            self.console.sendLine("Download stopped due to insufficient funds.")
        else:
            self.console.sendLine("Autoaddstream: An unexpected error has caused the download to stop: %s" % err.getTraceback())

    def _make_downloader(self):
        self.downloader = self.factory.make_downloader(self.metadata, [0.5, True], self.payment_rate_manager)
        return self.downloader

class AutoFetcher(object):
    def __init__(self, session, lbry_file_manager, lbry_file_metadata_manager, wallet, sd_identifier):
        self.console = None
        self.sd_identifier = sd_identifier
        self.wallet = wallet
        self.session = session
        self.lbry_file_manager = lbry_file_manager
        self.lbry_metadata_manager = lbry_file_metadata_manager
        self.seen = []
        self.lastbestblock = None
        self.rpc_conn = self.wallet.get_rpc_conn_x()
        self.search = None
        self.first_run = True
        self.is_running = False

    def start(self, console):
        #TODO first search through the nametrie before monitoring live updates
        #TODO load previously downloaded streams

        self.console = console

        if not self.is_running:
            self.is_running = True
            self.search = LoopingCall(self._looped_search)
            self.search.start(1)
        else:
            self.console.sendLine("Autofetcher is already running")

    def stop(self, console):
        self.console = console

        if self.is_running:
            self.search.stop()
            self.is_running = False
        else:
            self.console.sendLine("Autofetcher isn't running, there's nothing to stop")

    def check_if_running(self, console):
        self.console = console

        if self.is_running:
            self.console.sendLine("Autofetcher is running")
            self.console.sendLine("Last block hash: " + str(self.lastbestblock['bestblockhash']))
        else:
            self.console.sendLine("Autofetcher is not running")

    def _get_names(self):
        c = self.rpc_conn.getblockchaininfo()
        rtn = []
        if self.lastbestblock != c:
            block = self.rpc_conn.getblock(c['bestblockhash'])
            txids = block['tx']
            transactions = [self.rpc_conn.decoderawtransaction(self.rpc_conn.getrawtransaction(t)) for t in txids]
            for t in transactions:
                claims = self.rpc_conn.getclaimsfortx(t['txid'])

                # uncomment to make it download lbry://y on startup
                # if self.first_run:
                #     claims = self.rpc_conn.getclaimsfortx("38da801a2c3620a79252e5b0b619d1d3f4d53aa9edd9cdc76d9ba65660fb9f06")
                #     self.first_run = False

                if claims:
                    for claim in claims:
                        if claim not in self.seen:
                            self.console.sendLine("lbry://" + str(claim['name']) + " | stream hash: " +
                                                        str(json.loads(claim['value'])['stream_hash']))
                            rtn.append(claim)
                            self.seen.append(claim)
                else:
                    #self.console.sendLine("No new claims in block #" + str(block['height']))
                    pass

        self.lastbestblock = c

        if len(rtn):
            return defer.succeed(rtn)

    def _download_claims(self, claims):
        if claims:
            for claim in claims:
                download = defer.Deferred()
                stream = AutoAddStreamFromLBRYcrdName(self.console, self.sd_identifier, self.session,
                                                      self.wallet, self.lbry_file_manager)
                download.addCallback(lambda _: stream.start(claim))
                download.callback(None)

        return defer.succeed(None)

    def _looped_search(self):
        d = defer.Deferred(None)
        d.addCallback(lambda _: self._get_names())
        d.addCallback(self._download_claims)
        d.callback(None)