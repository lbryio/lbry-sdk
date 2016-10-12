import argparse
import itertools
import logging
import os
import sys

import appdirs
from twisted.internet import defer
from twisted.internet import reactor
from twisted.internet import protocol
from twisted.internet import endpoints
from twisted.python import log

from lbrynet import conf
from lbrynet.core import Wallet
from lbrynet.core import BlobManager
from lbrynet.core import HashAnnouncer
from lbrynet.core import PeerManager
from lbrynet.core import Session
from lbrynet.core import utils
from lbrynet.core.client import DHTPeerFinder
from lbrynet.dht import node
from lbrynet.metadata import Metadata
from lbrynet.core import StreamDescriptor as sd


logger = logging.getLogger()


def main(args=None):
    logging.basicConfig()
    parser = argparse.ArgumentParser()
    args = parser.parse_args(args)

    db_dir = appdirs.user_data_dir('LBRY')
    lbrycrd = appdirs.user_data_dir('lbrycrd')

    wallet = Wallet.LBRYcrdWallet(db_dir, wallet_conf=os.path.join(lbrycrd, 'lbrycrd.conf'))
    session = Session.Session(
        conf.MIN_BLOB_DATA_PAYMENT_RATE,
        db_dir=db_dir,
        lbryid=utils.generate_id(),
        blob_dir=os.path.join(db_dir, 'blobfiles'),
        dht_node_port=4444,
        known_dht_nodes=conf.KNOWN_DHT_NODES,
        peer_port=3333,
        use_upnp=False,
        wallet=wallet
    )
    
    d = session.setup()
    d.addCallback(lambda _: Tracker.load(session))
    d.addCallback(lambda t: t.processNameClaims())
    d.addCallback(lambda _: reactor.stop())

    reactor.run()
    

class Tracker(object):
    def __init__(self, session, wallet):
        self.session = session
        self.wallet = wallet
        self.names = None

    @classmethod
    def load(cls, session):
        return cls(session, session.wallet)

    def processNameClaims(self, limit=None):
        d = self.wallet.get_nametrie()
        d.addCallback(getNameClaims)
        if limit:
            d.addCallback(itertools.islice, limit)
        d.addCallback(self._setNames)
        d.addCallback(lambda _: self._getSdHashes())
        d.addCallback(lambda _: self._filterNames('sd_hash'))
        d.addCallback(lambda _: self._downloadAllBlobs())
        d.addCallback(lambda _: self._filterNames('sd_blob'))
        return d

    def _setNames(self, names):
        self.names = [Name(n) for n in names]

    def _getSdHashes(self):
        return defer.DeferredList([n.setSdHash(self.wallet) for n in self.names])

    def _filterNames(self, attr):
        self.names = [n for n in self.names if getattr(n, attr)]
        print "We have {} names with attribute {}".format(len(self.names), attr)

    def _downloadAllBlobs(self):
        return defer.DeferredList([
            n.download_sd_blob(self.session) for n in self.names
        ])


class Name(object):
    def __init__(self, name):
        self.name = name
        self.sd_hash = None
        self.sd_blob = None

    def setSdHash(self, wallet):
        d = wallet.get_stream_info_for_name(self.name)
        d.addCallback(Metadata.Metadata)
        d.addCallback(_getSdHash)
        d.addCallback(self._setSdHash)
        # swallow errors
        d.addErrback(lambda _: None)
        return d

    def _setSdHash(self, sd_hash):
        self.sd_hash = sd_hash

    def download_sd_blob(self, session):
        print 'Trying to get sd_blob for {} using {}'.format(self.name, self.sd_hash)
        d = download_sd_blob_with_timeout(session, self.sd_hash, session.payment_rate_manager)
        d.addCallback(sd.BlobStreamDescriptorReader)
        d.addCallback(self._setSdBlob)
        # swallow errors
        d.addErrback(lambda _: None)
        return d
        
    def _setSdBlob(self, blob):
        print '{} has a blob'.format(self.name)
        self.sd_blob = blob


def download_sd_blob_with_timeout(session, sd_hash, payment_rate_manager):
    d = sd.download_sd_blob(session, sd_hash, payment_rate_manager)
    reactor.callLater(10, d.cancel)
    return d


def getNameClaims(trie):
    for x in trie:
        if 'txid' in x:
            yield x['name']


def _getSdHash(metadata):
    return metadata['sources']['lbry_sd_hash']


if __name__ == '__main__':
    sys.exit(main())



