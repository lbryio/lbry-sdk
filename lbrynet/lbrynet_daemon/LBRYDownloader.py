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
        self.wallet = wallet
        self.resolved_name = None
        self.description = None
        self.key_fee = None
        self.key_fee_address = None
        self.data_rate = data_rate
        self.pay_key = pay_key
        self.name = None
        self.session = session
        self.payment_rate_manager = PaymentRateManager(self.session.base_payment_rate_manager)
        self.lbry_file_manager = lbry_file_manager
        self.sd_identifier = sd_identifier
        self.stream_hash = None
        self.max_key_fee = max_key_fee
        self.stream_info = None
        self.stream_info_manager = None


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

        else:
            print 'InvalidStreamInfoError'
            raise InvalidStreamInfoError(self.stream_info)

        if self.key_fee > self.max_key_fee:
            if self.pay_key:
                print "Key fee (" + str(self.key_fee) + ") above limit of " + str(
                    self.max_key_fee) + ", didn't download lbry://" + str(self.resolved_name)
                return defer.fail(None)
        else:
            pass

        d = defer.Deferred(None)
        d.addCallback(lambda _: download_sd_blob(self.session, self.stream_hash, self.payment_rate_manager))
        d.addCallback(self.sd_identifier.get_metadata_for_sd_blob)
        d.addCallback(lambda metadata:
                      metadata.factories[1].make_downloader(metadata, [self.data_rate, True], self.payment_rate_manager))
        d.addErrback(lambda err: err.trap(defer.CancelledError))
        d.addErrback(lambda err: log.error("An exception occurred attempting to load the stream descriptor: %s", err.getTraceback()))
        d.addCallback(self._start_download)
        d.callback(None)

        return d

    def _start_download(self, downloader):
        def _pay_key_fee():
            if self.key_fee is not None and self.key_fee_address is not None:
                reserved_points = self.wallet.reserve_points(self.key_fee_address, self.key_fee)
                if reserved_points is None:
                    return defer.fail(InsufficientFundsError())
                print 'Key fee: ' + str(self.key_fee) + ' | ' + str(self.key_fee_address)
                return self.wallet.send_points_to_address(reserved_points, self.key_fee)
            return defer.succeed(None)

        if self.pay_key:
            d = _pay_key_fee()
        else:
            d = defer.Deferred()

        downloader.start()

        print "Downloading", self.stream_hash, "-->", os.path.join(downloader.download_directory, downloader.file_name)

        return d


class FetcherDaemon(object):
    def __init__(self, session, lbry_file_manager, lbry_file_metadata_manager, wallet, sd_identifier, autofetcher_conf,
                 verbose=False):
        self.autofetcher_conf = autofetcher_conf
        self.max_key_fee = 0.0
        self.sd_identifier = sd_identifier
        self.wallet = wallet
        self.session = session
        self.lbry_file_manager = lbry_file_manager
        self.lbry_metadata_manager = lbry_file_metadata_manager
        self.seen = []
        self.lastbestblock = None
        self.search = None
        self.first_run = True
        self.is_running = False
        self.verbose = verbose
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
        c = self.wallet.get_blockchain_info()
        rtn = []
        if self.lastbestblock != c:
            block = self.wallet.get_block(c['bestblockhash'])
            txids = block['tx']
            transactions = [self.wallet.get_tx(t) for t in txids]
            for t in transactions:
                claims = self.wallet.get_claims_for_tx(t['txid'])
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
                            rtn.append([claim['name'], t['txid']])
                            self.seen.append(claim)
                else:
                    if self.verbose:
                        print "[" + str(datetime.now()) + "] No claims in block", c['bestblockhash']

        self.lastbestblock = c

        if len(rtn):
            return defer.DeferredList([self.wallet.get_stream_info_for_name(name, txid=t) for name, t in rtn])

    def _download_claims(self, claims):
        if claims:
            for claim in claims:
                download = defer.Deferred()
                stream = GetStream(self.sd_identifier, self.session, self.wallet, self.lbry_file_manager,
                                   self.max_key_fee, pay_key=False)
                download.addCallback(lambda _: stream.start(claim[1]))
                download.callback(None)

        return defer.succeed(None)

    def _looped_search(self):
        d = defer.Deferred()
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
