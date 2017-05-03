import logging

from twisted.internet import defer

import pool


log = logging.getLogger(__name__)


class Tracker(object):
    def __init__(self, session, names):
        self.session = session
        self.names = names
        self.stats = {}

    @property
    def wallet(self):
        return self.session.wallet

    @defer.inlineCallbacks
    def processNameClaims(self):
        try:
            log.info('Starting to get name claims')
            yield self._getSdHashes()
            self._filterNames('sd_hash')
            log.info('Downloading all of the blobs')
            yield self._downloadAllBlobs()
        except Exception:
            log.exception('Something bad happened')

    def _getSdHashes(self):
        return pool.DeferredPool((n.setSdHash(self.wallet) for n in self.names), 10)

    def _filterNames(self, attr):
        self.names = [n for n in self.names if getattr(n, attr)]
        self.stats[attr] = len(self.names)
        print("We have {} names with attribute {}".format(len(self.names), attr))

    def _downloadAllBlobs(self):
        return pool.DeferredPool((n.download_sd_blob(self.session) for n in self.names), 10)
