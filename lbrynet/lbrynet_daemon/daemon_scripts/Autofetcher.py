import json
import logging.handlers
import sys
import os
import requests
from datetime import datetime

from appdirs import user_data_dir
from twisted.internet.task import LoopingCall
from twisted.internet import reactor
from twisted.internet.threads import deferToThread


if sys.platform != "darwin":
    log_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
else:
    log_dir = user_data_dir("LBRY")

if not os.path.isdir(log_dir):
    os.mkdir(log_dir)

LOG_FILENAME = os.path.join(log_dir, 'lbrynet-daemon.log')

if os.path.isfile(LOG_FILENAME):
    f = open(LOG_FILENAME, 'r')
    PREVIOUS_LOG = len(f.read())
    f.close()
else:
    PREVIOUS_LOG = 0

log = logging.getLogger(__name__)
handler = logging.handlers.RotatingFileHandler(LOG_FILENAME, maxBytes=2097152, backupCount=5)
log.addHandler(handler)
log.setLevel(logging.INFO)


class Autofetcher(object):
    """
    Download name claims as they occur
    """

    def __init__(self, api):
        self._api = api
        self._checker = LoopingCall(self._check_for_new_claims)
        self._price_checker = LoopingCall(self._update_price)
        self.best_block = None
        self.last_price = None
        self.price_updated = None

    def start(self):
        reactor.addSystemEventTrigger('before', 'shutdown', self.stop)
        self._checker.start(5)
        self._price_checker.start(30)

    def stop(self):
        log.info("Stopping autofetcher")
        self._checker.stop()

    def _check_for_new_claims(self):
        block = self._api.get_best_blockhash()
        if block != self.best_block:
            log.info("Checking new block for name claims, block hash: %s" % block)
            self.best_block = block
            transactions = self._api.get_block({'blockhash': block})['tx']
            for t in transactions:
                c = self._api.get_claims_for_tx({'txid': t})
                if len(c):
                    for i in c:
                        if 'fee' in json.loads(i['value']):

                        log.info("Downloading stream for claim txid: %s" % t)
                        self._api.get({'name': t, 'stream_info': json.loads(i['value'])})

    def _update_price(self):
        def _check_bittrex():
            try:
                r = requests.get("https://bittrex.com/api/v1.1/public/getticker", {'market': 'BTC-LBC'})
                self.last_price = json.loads(r.text)['result']['Last']
                self.price_updated = datetime.now()
                log.info("Updated exchange rate, last BTC-LBC trade: %f" % self.last_price)
            except:
                log.info("Failed to update exchange rate")
                self.last_price = None
                self.price_updated = datetime.now()
        return deferToThread(_check_bittrex)


def run(api):
    fetcher = Autofetcher(api)
    fetcher.start()