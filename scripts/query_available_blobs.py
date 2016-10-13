from __future__ import print_function

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
from lbrynet.core import BlobAvailability
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
    logging.basicConfig(level='DEBUG')
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int)
    parser.add_argument('--download', action='store_true')
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
    d.addCallback(lambda t: t.processNameClaims(args.limit, args.download))
    d.addCallback(lambda t: print(t.stats))
    d.addCallback(lambda _: reactor.stop())

    reactor.run()


def timeout(n):
    def wrapper(fn):
        def wrapped(*args, **kwargs):
            d = fn(*args, **kwargs)
            reactor.callLater(n, d.cancel)
            return d
        return wrapped
    return wrapper
    

class Tracker(object):
    def __init__(self, session, blob_tracker, wallet):
        self.session = session
        self.blob_tracker = blob_tracker
        self.wallet = wallet
        self.names = None
        self.stats = {}

    @classmethod
    def load(cls, session):
        blob_tracker = BlobAvailability.BlobAvailabilityTracker(
            session.blob_manager, session.peer_finder, session.dht_node)
        return cls(session, blob_tracker, session.wallet)

    def processNameClaims(self, limit=None, download=False):
        d = self.wallet.get_nametrie()
        d.addCallback(getNameClaims)
        if limit:
            d.addCallback(itertools.islice, limit)
        d.addCallback(self._setNames)
        d.addCallback(lambda _: self._getSdHashes())
        d.addCallback(lambda _: self._filterNames('sd_hash'))
        d.addCallback(lambda _: self._checkAvailability())
        d.addCallback(lambda _: self._filterNames('is_available'))
        if download:
            d.addCallback(lambda _: self._downloadAllBlobs())
            d.addCallback(lambda _: self._filterNames('sd_blob'))
        d.addCallback(lambda _: self)
        return d

    def _setNames(self, names):
        self.names = [Name(n) for n in names]

    def _getSdHashes(self):
        return defer.DeferredList([n.setSdHash(self.wallet) for n in self.names])

    def _filterNames(self, attr):
        self.names = [n for n in self.names if getattr(n, attr)]
        self.stats[attr] = len(self.names)
        print("We have {} names with attribute {}".format(len(self.names), attr))

    def _checkAvailability(self):
        return defer.DeferredList([
            n.check_availability(self.blob_tracker) for n in self.names
        ])
        
    def _downloadAllBlobs(self):
        return defer.DeferredList([
            n.download_sd_blob(self.session) for n in self.names
        ])


class Name(object):
    def __init__(self, name):
        self.name = name
        self.sd_hash = None
        self.is_available = None
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

    @timeout(10)
    def check_availability(self, blob_tracker):
        d = blob_tracker.get_blob_availability(self.sd_hash)
        d.addCallback(lambda b: self._setAvailable(b[self.sd_hash]))
        # swallow errors
        d.addErrback(lambda _: None)
        return d

    def _setAvailable(self, peer_count):
        self.is_available = peer_count > 0
        
    def download_sd_blob(self, session):
        print('Trying to get sd_blob for {} using {}'.format(self.name, self.sd_hash))
        d = download_sd_blob_with_timeout(session, self.sd_hash, session.payment_rate_manager)
        d.addCallback(sd.BlobStreamDescriptorReader)
        d.addCallback(self._setSdBlob)
        # swallow errors
        d.addErrback(lambda _: None)
        return d
        
    def _setSdBlob(self, blob):
        print('{} has a blob'.format(self.name))
        self.sd_blob = blob


@timeout(10)
def download_sd_blob_with_timeout(session, sd_hash, payment_rate_manager):
    return sd.download_sd_blob(session, sd_hash, payment_rate_manager)


def getNameClaims(trie):
    for x in trie:
        if 'txid' in x:
            yield x['name']


def _getSdHash(metadata):
    return metadata['sources']['lbry_sd_hash']


if __name__ == '__main__':
    sys.exit(main())



