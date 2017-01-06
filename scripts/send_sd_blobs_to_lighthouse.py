from __future__ import print_function
from lbrynet.core import log_support

import argparse
import collections
import itertools
import logging
import os
import random
import sys

import appdirs
from twisted.internet import defer
from twisted.internet import reactor
from twisted.internet import protocol
from twisted.internet import endpoints

from lbrynet import conf
from lbrynet.core import Error
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
from lbrynet import reflector

import common
import name
import pool
import track


log = logging.getLogger('main')


def main(args=None):
    conf.initialize_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=conf.server_port, nargs='+')
    parser.add_argument('--names', nargs='*')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args(args)

    log_support.configure_console(level='INFO')

    db_dir = appdirs.user_data_dir('lighthouse-uploader')
    safe_makedirs(db_dir)
    # no need to persist metadata info
    storage = Wallet.InMemoryStorage()
    wallet = Wallet.LBRYumWallet(storage)
    blob_dir = os.path.join(db_dir, 'blobfiles')
    safe_makedirs(blob_dir)
    # Don't set a hash_announcer, we have no need to tell anyone we
    # have these blobs
    blob_manager = BlobManager.DiskBlobManager(None, blob_dir, db_dir)
    # TODO: make it so that I can disable the BlobAvailabilityTracker
    #       or, in general, make the session more reusable for users
    #       that only want part of the functionality
    session = Session.Session(
        blob_data_payment_rate=0,
        db_dir=db_dir,
        lbryid=utils.generate_id(),
        blob_dir=blob_dir,
        dht_node_port=4444,
        known_dht_nodes=conf.settings.known_dht_nodes,
        peer_port=3333,
        use_upnp=False,
        wallet=wallet,
        blob_manager=blob_manager,
    )
    assert session.wallet
    run(session, args.destination, args.names, args.limit)
    reactor.run()


def safe_makedirs(directory):
    try:
        os.makedirs(directory)
    except OSError:
        pass


@defer.inlineCallbacks
def run(session, destinations, names, limit):
    try:
        yield session.setup()
        while not session.wallet.network.is_connected():
            log.info('Retrying wallet startup')
            try:
                yield session.wallet.start()
            except ValueError:
                pass
        names = yield getNames(session.wallet, names)
        if limit and limit < len(names):
            names = random.sample(names, limit)
        log.info('Processing %s names', len(names))
        names = [Name(n, session.blob_manager) for n in names]
        t = Tracker(session, destinations, names)
        yield t.processNameClaims()
    except Exception:
        log.exception('Something bad happened')
    finally:
        log.warning('We are stopping the reactor gracefully')
        reactor.stop()


def logAndStop(err):
    log_support.failure(err, log, 'This sucks: %s')
    reactor.stop()


def logAndRaise(err):
    log_support.failure(err, log, 'This still sucks: %s')
    return err


class Tracker(track.Tracker):
    def __init__(self, session, destinations, names):
        self.destinations = destinations
        track.Tracker.__init__(self, session, names)

    @property
    def blob_manager(self):
        return self.session.blob_manager

    @defer.inlineCallbacks
    def processNameClaims(self):
        yield super(Tracker, self).processNameClaims()
        log.info('Sending the blobs')
        yield self._sendSdBlobs()

    @defer.inlineCallbacks
    def _sendSdBlobs(self):
        blobs = [n.sd_blob for n in self.names if n.sd_blob]
        log.info('Sending %s blobs', len(blobs))
        blob_hashes = [b.blob_hash for b in blobs]
        for destination in self.destinations:
            factory = reflector.BlobClientFactory(self.blob_manager, blob_hashes)
            yield self._connect(destination, factory)

    @defer.inlineCallbacks
    def _connect(self, destination, factory):
        url, port = destination
        ip = yield reactor.resolve(url)
        try:
            print('Connecting to {}'.format(ip))
            yield reactor.connectTCP(ip, port, factory)
            #factory.finished_deferred.addTimeout(60, reactor)
            value = yield factory.finished_deferred
            if value:
                print('Success!')
            else:
                print('Not success?', value)
        except Exception:
            log.exception('Somehow failed to send blobs')


class Name(name.Name):
    def __init__(self, my_name, blob_manager):
        name.Name.__init__(self, my_name)
        self.blob_manager = blob_manager

    def _after_download(self, blob):
        # keep the blob for future runs
        self.blob_manager.blob_completed(blob)


if __name__ == '__main__':
    sys.exit(main())
