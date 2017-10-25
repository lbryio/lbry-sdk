from __future__ import print_function
from lbrynet.core import log_support

import argparse
import collections
import logging
import os
import random
import shutil
import sys
import tempfile

from twisted.internet import defer
from twisted.internet import reactor

from lbrynet import analytics
from lbrynet import conf
from lbrynet.core import Wallet
from lbrynet.core import BlobAvailability
from lbrynet.core import Session
from lbrynet.core import utils

import common
import name
import pool
import track


log = logging.getLogger()


def main(args=None):
    conf.initialize_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int)
    parser.add_argument('--download', action='store_true',
                        help='Set flag to also download each sd_blob and report on success')
    args = parser.parse_args(args)

    log_support.configure_console()
    log_support.configure_twisted()

    # make a fresh dir or else we will include blobs that we've
    # already downloaded but might not otherwise be available.
    db_dir = tempfile.mkdtemp()
    try:
        blob_dir = os.path.join(db_dir, 'blobfiles')
        os.makedirs(blob_dir)
        storage = Wallet.InMemoryStorage()
        wallet = Wallet.LBRYumWallet(storage)
        session = Session.Session(
            0,
            db_dir=db_dir,
            node_id=utils.generate_id(),
            blob_dir=blob_dir,
            dht_node_port=4444,
            known_dht_nodes=conf.settings['known_dht_nodes'],
            peer_port=3333,
            use_upnp=False,
            wallet=wallet
        )
        api = analytics.Api.new_instance(conf.settings['share_usage_data'])
        run(args, session, api)
        reactor.run()
    finally:
        shutil.rmtree(db_dir)


@defer.inlineCallbacks
def run(args, session, api):
    try:
        yield session.setup()
        names = yield common.getNames(session.wallet)
        if args.limit and len(names) > args.limit:
            names = random.sample(list(names), args.limit)
        names = [Name(n) for n in names]
        blob_tracker = BlobAvailability.BlobAvailabilityTracker(
            session.blob_manager, session.peer_finder, session.dht_node)

        tracker = yield Tracker(session, names, blob_tracker)
        yield tracker.processNameClaims(args.download)
        event = makeEvent(tracker.stats)
        if args.download and not args.limit:
            api.track(event)
        else:
            # don't send event to analytics if it doesn't contain the full info
            print(event)
    except Exception:
        log.exception('Something bad happened')
    finally:
        reactor.stop()


class Tracker(track.Tracker):
    def __init__(self, session, names, blob_tracker):
        track.Tracker.__init__(self, session, names)
        self.blob_tracker = blob_tracker

    @defer.inlineCallbacks
    def processNameClaims(self, download=False):
        try:
            yield self._getSdHashes()
            yield self._filterNames('sd_hash')
            yield self._checkAvailability()
            yield self._filterNames('is_available')
            yield self.print_attempts_counter()
            if download:
                yield self._downloadAllBlobs()
                yield self._filterNames('sd_blob')
        except Exception:
            log.exception('Something bad happened')

    def print_attempts_counter(self):
        print(self.attempts_counter)

    def attempts_counter(self):
        return collections.Counter([n.availability_attempts for n in self.names])

    def _checkAvailability(self):
        return pool.DeferredPool(
            (n.check_availability(self.blob_tracker) for n in self.names),
            10
        )


class Name(name.Name):
    # From experience, very few sd_blobs get found after the third attempt
    MAX_ATTEMPTS = 6
    def __init__(self, my_name):
        name.Name.__init__(self, my_name)
        self.is_available = None
        self.availability_attempts = 0

    @defer.inlineCallbacks
    def _check_availability(self, blob_tracker):
        b = yield blob_tracker.get_blob_availability(self.sd_hash)
        peer_count = b[self.sd_hash]
        self._setAvailable(peer_count)

    @defer.inlineCallbacks
    def check_availability(self, blob_tracker):
        while not self.is_available and self.availability_attempts < self.MAX_ATTEMPTS:
            self.availability_attempts += 1
            log.info('Attempt %s to find %s', self.availability_attempts, self.name)
            yield self._check_availability(blob_tracker)

    def _setAvailable(self, peer_count):
        self.is_available = peer_count > 0


def makeEvent(stats):
    return {
        'userId': 'lbry',
        'event': 'Content Availability',
        'properties': {
            'total_published': stats['sd_hash'],
            'sd_blob_available_on_dht': stats['is_available'],
            'sd_blob_available_for_download': stats['sd_blob'],
        },
        'context': {
            'app': {
                'name': 'Availability Tracker',
                'version': 1,
            },
            'library': {
                'name': 'lbrynet-analytics',
                'version': '1.0.0'
            },
        },
        'timestamp': utils.isonow()
    }

if __name__ == '__main__':
    sys.exit(main())
