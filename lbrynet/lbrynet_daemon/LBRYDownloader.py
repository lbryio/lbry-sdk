import json
import logging
import os
from datetime import datetime
from twisted.internet import defer
from twisted.internet.task import LoopingCall
from lbrynet.core.Error import InvalidStreamInfoError, InsufficientFundsError
from lbrynet.core.PaymentRateManager import PaymentRateManager
from lbrynet.core.StreamDescriptor import download_sd_blob

log = logging.getLogger(__name__)


class GetStream(object):
    def __init__(self, sd_identifier, session, wallet, lbry_file_manager, max_key_fee, pay_key=True, data_rate=0.5):
        self.finished_deferred = defer.Deferred(None)
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
        self.max_key_fee = max_key_fee
        self.stream_info = None
        self.stream_info_manager = None
        self.downloader = None
        self.data_rate = data_rate
        self.pay_key = pay_key

    def start(self, stream_info):
        self.stream_info = stream_info
        if 'stream_hash' in self.stream_info.keys():
            self.description = self.stream_info['description']
            if 'key_fee' in self.stream_info.keys():
                self.key_fee = float(self.stream_info['key_fee'])
                if 'key_fee_address' in self.stream_info.keys():
                    self.key_fee_address = self.stream_info['key_fee_address']
                else:
                    self.key_fee_address = None
            else:
                self.key_fee = None
                self.key_fee_address = None
            self.stream_hash = self.stream_info['stream_hash']
        elif 'stream_hash' in json.loads(self.stream_info['value']):
            self.resolved_name = self.stream_info.get('name', None)
            self.description = json.loads(self.stream_info['value']).get('description', None)

            try:
                if 'key_fee' in json.loads(self.stream_info['value']):
                    self.key_fee = float(json.loads(self.stream_info['value'])['key_fee'])
            except ValueError:
                self.key_fee = None
            self.key_fee_address = json.loads(self.stream_info['value']).get('key_fee_address', None)
            self.stream_hash = json.loads(self.stream_info['value'])['stream_hash']
        else:
            print 'InvalidStreamInfoError'
            raise InvalidStreamInfoError(self.stream_info)

        if self.key_fee > self.max_key_fee:
            if self.pay_key:
                print "Key fee (" + str(self.key_fee) + ") above limit of " + str(
                    self.max_key_fee) + ", didn't download lbry://" + str(self.resolved_name)
                return self.finished_deferred.callback(None)
        else:
            pass

        def _get_downloader_for_return():
            return defer.succeed(self.downloader)

        self.loading_metadata_deferred = defer.Deferred(None)
        self.loading_metadata_deferred.addCallback(
            lambda _: download_sd_blob(self.session, self.stream_hash, self.payment_rate_manager))
        self.loading_metadata_deferred.addCallback(self.sd_identifier.get_metadata_for_sd_blob)
        self.loading_metadata_deferred.addCallback(self._handle_metadata)
        self.loading_metadata_deferred.addErrback(self._handle_load_canceled)
        self.loading_metadata_deferred.addErrback(self._handle_load_failed)
        if self.pay_key:
            self.loading_metadata_deferred.addCallback(lambda _: self._pay_key_fee())
        self.loading_metadata_deferred.addCallback(lambda _: self._make_downloader())
        self.loading_metadata_deferred.addCallback(lambda _: self.downloader.start())
        self.loading_metadata_deferred.addErrback(self._handle_download_error)
        self.loading_metadata_deferred.addCallback(lambda _: _get_downloader_for_return())
        self.loading_metadata_deferred.callback(None)

        return defer.succeed(None)

    def _pay_key_fee(self):
        if self.key_fee is not None and self.key_fee_address is not None:
            reserved_points = self.wallet.reserve_points(self.key_fee_address, self.key_fee)
            if reserved_points is None:
                return defer.fail(InsufficientFundsError())
            print 'Key fee: ' + str(self.key_fee) + ' | ' + str(self.key_fee_address)
            return self.wallet.send_points_to_address(reserved_points, self.key_fee)
        return defer.succeed(None)

    def _handle_load_canceled(self, err):
        err.trap(defer.CancelledError)
        self.finished_deferred.callback(None)

    def _handle_load_failed(self, err):
        self.loading_failed = True
        log.error("An exception occurred attempting to load the stream descriptor: %s", err.getTraceback())
        print 'Load Failed: ', err.getTraceback()
        self.finished_deferred.callback(None)

    def _handle_metadata(self, metadata):
        self.metadata = metadata
        self.factory = self.metadata.factories[1]
        return defer.succeed(None)

    def _handle_download_error(self, err):
        if err.check(InsufficientFundsError):
            print "Download stopped due to insufficient funds."
        else:
            print "Autoaddstream: An unexpected error has caused the download to stop: ", err.getTraceback()

    def _make_downloader(self):

        def _set_downloader(downloader):
            self.downloader = downloader
            print "Downloading", self.stream_hash, "-->", os.path.join(self.downloader.download_directory,
                                                                        self.downloader.file_name)
            return self.downloader

        downloader = self.factory.make_downloader(self.metadata, [self.data_rate, True], self.payment_rate_manager)
        downloader.addCallback(_set_downloader)
        return downloader


class FetcherDaemon(object):
    def __init__(self, session, lbry_file_manager, lbry_file_metadata_manager, wallet, sd_identifier, autofetcher_conf):
        self.autofetcher_conf = autofetcher_conf
        self.max_key_fee = 0.0
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
        self._get_autofetcher_conf()

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.search = LoopingCall(self._looped_search)
            self.search.start(1)
        else:
            print "Autofetcher is already running"

    def stop(self):
        if self.is_running:
            self.search.stop()
            self.is_running = False
        else:
            print "Autofetcher isn't running, there's nothing to stop"

    def check_if_running(self):
        if self.is_running:
            msg = "Autofetcher is running\n"
            msg += "Last block hash: " + str(self.lastbestblock['bestblockhash'])
        else:
            msg = "Autofetcher is not running"
        return msg

    def _get_names(self):
        c = self.rpc_conn.getblockchaininfo()
        rtn = []
        if self.lastbestblock != c:
            block = self.rpc_conn.getblock(c['bestblockhash'])
            txids = block['tx']
            transactions = [self.rpc_conn.decoderawtransaction(self.rpc_conn.getrawtransaction(t)) for t in txids]
            for t in transactions:
                claims = self.rpc_conn.getclaimsfortx(t['txid'])
                # if self.first_run:
                #     # claims = self.rpc_conn.getclaimsfortx("96aca2c60efded5806b7336430c5987b9092ffbea9c6ed444e3bf8e008993e11")
                #     # claims = self.rpc_conn.getclaimsfortx("cc9c7f5225ecb38877e6ca7574d110b23214ac3556b9d65784065ad3a85b4f74")
                #     self.first_run = False
                if claims:
                    for claim in claims:
                        if claim not in self.seen:
                            msg = "[" + str(datetime.now()) + "] New claim | lbry://" + str(claim['name']) + \
                                  " | stream hash: " + str(json.loads(claim['value'])['stream_hash'])
                            print msg
                            log.debug(msg)
                            rtn.append(claim)
                            self.seen.append(claim)

        self.lastbestblock = c

        if len(rtn):
            return defer.succeed(rtn)

    def _download_claims(self, claims):
        if claims:
            for claim in claims:
                download = defer.Deferred()
                stream = GetStream(self.sd_identifier, self.session, self.wallet, self.lbry_file_manager,
                                   self.max_key_fee, pay_key=False)
                download.addCallback(lambda _: stream.start(claim))
                download.callback(None)

        return defer.succeed(None)

    def _looped_search(self):
        d = defer.Deferred(None)
        d.addCallback(lambda _: self._get_names())
        d.addCallback(self._download_claims)
        d.callback(None)

    def _get_autofetcher_conf(self):
        settings = {"maxkey": "0.0"}
        if os.path.exists(self.autofetcher_conf):
            conf = open(self.autofetcher_conf)
            for l in conf:
                if l.startswith("maxkey="):
                    settings["maxkey"] = float(l[7:].rstrip('\n'))
                    print "Autofetcher using max key price of", settings["maxkey"], ", to start call start_fetcher()"
        else:
            print "Autofetcher using default max key price of 0.0"
            print "To change this create the file:"
            print str(self.autofetcher_conf)
            print "Example contents of conf file:"
            print "maxkey=1.0"

        self.max_key_fee = settings["maxkey"]
