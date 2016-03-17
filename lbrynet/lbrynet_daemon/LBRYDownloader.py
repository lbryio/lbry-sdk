import json
import logging
import os
from datetime import datetime
from twisted.internet import defer
from twisted.internet.task import LoopingCall
from lbrynet.core.Error import InvalidStreamInfoError, InsufficientFundsError
from lbrynet.core.PaymentRateManager import PaymentRateManager
from lbrynet.core.StreamDescriptor import download_sd_blob
from lbrynet.lbryfilemanager.LBRYFileDownloader import ManagedLBRYFileDownloaderFactory

log = logging.getLogger(__name__)


class GetStream(object):
    def __init__(self, sd_identifier, session, wallet, lbry_file_manager, max_key_fee, pay_key=True, data_rate=0.5,
                                                                                                        timeout=30):
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
        self.d = defer.Deferred(None)
        self.timeout = timeout
        self.timeout_counter = 0
        self.download_path = None
        self.checker = LoopingCall(self.check_status)


    def check_status(self):
        self.timeout_counter += 1

        if self.download_path and os.path.isfile(self.download_path):
            self.checker.stop()
            return defer.succeed(True)

        elif self.timeout_counter >= self.timeout:
            log.info("Timeout downloading " + str(self.stream_info))
            self.checker.stop()
            self.d.cancel()

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
            log.error("InvalidStreamInfoError in autofetcher: ", stream_info)
            raise InvalidStreamInfoError(self.stream_info)

        if self.key_fee > self.max_key_fee:
            if self.pay_key:
                log.info("Key fee (" + str(self.key_fee) + ") above limit of " + str(
                    self.max_key_fee) + ", didn't download lbry://" + str(self.resolved_name))
                return defer.fail(None)
        else:
            pass

        self.checker.start(1)

        self.d.addCallback(lambda _: download_sd_blob(self.session, self.stream_hash, self.payment_rate_manager))
        self.d.addCallback(self.sd_identifier.get_metadata_for_sd_blob)
        self.d.addCallback(lambda metadata: (next(factory for factory in metadata.factories if isinstance(factory, ManagedLBRYFileDownloaderFactory)), metadata))
        self.d.addCallback(lambda (factory, metadata): factory.make_downloader(metadata, [self.data_rate, True], self.payment_rate_manager))
        self.d.addErrback(lambda err: err.trap(defer.CancelledError))
        self.d.addErrback(lambda err: log.error("An exception occurred attempting to load the stream descriptor: %s", err.getTraceback()))
        self.d.addCallback(self._start_download)
        self.d.callback(None)

        return self.d

    def _start_download(self, downloader):
        def _pay_key_fee():
            if self.key_fee is not None and self.key_fee_address is not None:
                reserved_points = self.wallet.reserve_points(self.key_fee_address, self.key_fee)
                if reserved_points is None:
                    return defer.fail(InsufficientFundsError())
                log.info("Key fee: " + str(self.key_fee) + " | " + str(self.key_fee_address))
                return self.wallet.send_points_to_address(reserved_points, self.key_fee)
            return defer.succeed(None)

        if self.pay_key:
            d = _pay_key_fee()
        else:
            d = defer.Deferred()

        self.download_path = os.path.join(downloader.download_directory, downloader.file_name)
        d.addCallback(lambda _: downloader.start())
        d.addCallback(lambda _: log.info("Downloading " + str(self.stream_hash) + " --> " + str(self.download_path)))

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
            log.info("Starting autofetcher")
        else:
            log.info("Autofetcher is already running")

    def stop(self):
        if self.is_running:
            self.search.stop()
            self.is_running = False
        else:
            log.info("Autofetcher isn't running, there's nothing to stop")

    def check_if_running(self):
        if self.is_running:
            msg = "Autofetcher is running\n"
            msg += "Last block hash: " + str(self.lastbestblock)
        else:
            msg = "Autofetcher is not running"
        return msg

    def _get_names(self):
        d = self.wallet.get_best_blockhash()
        d.addCallback(lambda blockhash: get_new_streams(blockhash) if blockhash != self.lastbestblock else [])

        def get_new_streams(blockhash):
            self.lastbestblock = blockhash
            d = self.wallet.get_block(blockhash)
            d.addCallback(lambda block: get_new_streams_in_txes(block['tx'], blockhash))
            return d

        def get_new_streams_in_txes(txids, blockhash):
            ds = []
            for t in txids:
                d = self.wallet.get_claims_from_tx(t)
                d.addCallback(get_new_streams_in_tx, t, blockhash)
                ds.append(d)
            d = defer.DeferredList(ds, consumeErrors=True)
            d.addCallback(lambda result: [r[1] for r in result if r[0]])
            d.addCallback(lambda stream_lists: [stream for streams in stream_lists for stream in streams])
            return d

        def get_new_streams_in_tx(claims, t, blockhash):
            rtn = []
            if claims:
                for claim in claims:
                    if claim not in self.seen:
                        msg = "[" + str(datetime.now()) + "] New claim | lbry://" + str(claim['name']) + \
                              " | stream hash: " + str(json.loads(claim['value'])['stream_hash'])
                        log.info(msg)
                        if self.verbose:
                            print msg
                        rtn.append((claim['name'], t))
                        self.seen.append(claim)
            else:
                if self.verbose:
                    print "[" + str(datetime.now()) + "] No claims in block", blockhash
            return rtn

        d.addCallback(lambda streams: defer.DeferredList(
            [self.wallet.get_stream_info_from_txid(name, t) for name, t in streams]))
        return d

    def _download_claims(self, claims):
        if claims:
            for claim in claims:
                stream = GetStream(self.sd_identifier, self.session, self.wallet, self.lbry_file_manager,
                                   self.max_key_fee, pay_key=False)
                stream.start(claim[1])

        return defer.succeed(None)

    def _looped_search(self):
        d = self._get_names()
        d.addCallback(self._download_claims)
        return d

    def _get_autofetcher_conf(self):
        settings = {"maxkey": "0.0"}
        if os.path.exists(self.autofetcher_conf):
            conf = open(self.autofetcher_conf)
            for l in conf:
                if l.startswith("maxkey="):
                    settings["maxkey"] = float(l[7:].rstrip('\n'))
            conf.close()
        else:
            conf = open(self.autofetcher_conf, "w")
            conf.write("maxkey=10.0")
            conf.close()
            settings["maxkey"] = 10.0
            log.info("No autofetcher conf file found, making one with max key fee of 10.0")

        self.max_key_fee = settings["maxkey"]
