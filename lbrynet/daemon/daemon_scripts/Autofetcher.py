import json
import logging.handlers
import os

from twisted.internet.task import LoopingCall
from twisted.internet import reactor
from lbrynet import conf


conf.initialize_settings()
log_dir = conf.settings['data_dir']
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
        self.best_block = None

    def start(self):
        reactor.addSystemEventTrigger('before', 'shutdown', self.stop)
        self._checker.start(5)

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
                        log.info("Downloading stream for claim txid: %s" % t)
                        self._api.get({'name': t, 'stream_info': json.loads(i['value'])})


def run(api):
    fetcher = Autofetcher(api)
    fetcher.start()
