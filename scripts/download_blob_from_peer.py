"""A simple script that attempts to directly download a single blob from a given peer"""
import argparse
import logging
import sys
import os

from twisted.internet import defer
from twisted.internet import reactor
from zope.interface import implements

from lbrynet import interfaces
from lbrynet import conf
from lbrynet.core import log_support
from lbrynet.core import BlobManager
from lbrynet.core import HashAnnouncer
from lbrynet.core import HashBlob
from lbrynet.core import RateLimiter
from lbrynet.core import Peer
from lbrynet.core import Wallet
from lbrynet.core.client import BlobRequester
from lbrynet.core.client import ConnectionManager


log = logging.getLogger()
SUCCESS = False


def main(args=None):
    conf.initialize_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument('--timeout', type=int, default=30)
    parser.add_argument('peer')
    parser.add_argument('blob_hash')
    parser.add_argument('directory', type=str, default=os.getcwd())
    args = parser.parse_args(args)

    log_support.configure_console(level='DEBUG')

    announcer = HashAnnouncer.DummyHashAnnouncer()
    blob_manager = MyBlobManager(announcer)
    blob = HashBlob.BlobFile(args.directory, args.blob_hash)
    download_manager = SingleBlobDownloadManager(blob)
    peer = Peer.Peer(*conf.server_port(args.peer))
    payment_rate_manager = DumbPaymentRateManager()
    wallet = getWallet()
    requester = SingleBlobRequester(
        peer, blob_manager, payment_rate_manager, wallet, download_manager)
    rate_limiter = RateLimiter.DummyRateLimiter()
    downloader = SingleBlobDownloader()
    connection_manager = ConnectionManager.ConnectionManager(
        downloader, rate_limiter, [requester], [wallet.get_info_exchanger()])
    reactor.callLater(args.timeout, reactor.stop)
    d = connection_manager.start()
    d.addErrback(log_support.failure, 'Something bad happened: %s')
    reactor.run()

    if SUCCESS:
        sys.exit(0)
    else:
        sys.exit(1)


class MyBlobManager(BlobManager.BlobManager):
    def blob_completed(self, blob):
        global SUCCESS
        log.info('Blob has been downloaded, we can stop')
        # this feels pretty hacky, but its as good of a stopping point as any
        SUCCESS = True
        reactor.stop()


def getWallet():
    config = {'auto_connect': True}
    if conf.settings['lbryum_wallet_dir']:
        config['lbryum_path'] = conf.settings['lbryum_wallet_dir']
    storage = Wallet.InMemoryStorage()
    return Wallet.LBRYumWallet(storage, config)


class SingleBlobDownloader(object):
    def insufficientfunds(self, err):
        pass


class SingleBlobDownloadManager(object):
    def __init__(self, blob):
        self.blob = blob

    def needed_blobs(self):
        if self.blob.verified:
            return []
        else:
            return [self.blob]


class NullStrategy(object):
    def __init__(self):
        self.pending_sent_offers = {}


class DumbPaymentRateManager(object):
    def __init__(self):
        self.strategy = NullStrategy()

    def price_limit_reached(self, peer):
        return False

    def get_rate_blob_data(self, *args):
        return 0.0

    def record_offer_reply(self, peer, offer):
        pass

    def record_points_paid(self, point_ammount):
        pass


class FreeDownload(BlobRequester.DownloadRequest):
    def _pay_peer(self, *args):
        # TODO: somewhere I missed the part that is supposed to get
        #       and address from the remote server for where to send
        #       data fees to so we can't make payments. Probably has
        #       to do with the wallet_info_exchanger
        pass


class SingleBlobRequester(BlobRequester.BlobRequester):
    implements(interfaces.IRequestCreator)
    DownloadRequest = FreeDownload

    def __init__(self, peer, blob_manager, payment_rate_manager, wallet, download_manager):
        self.peer = peer
        self.sent = False
        BlobRequester.BlobRequester.__init__(
            self, blob_manager, None, payment_rate_manager, wallet, download_manager)

    def __repr__(self):
        return 'SingleBlobRequestor({!r})'.format(self.peer)

    def get_new_peers(self):
        if self.sent:
            return defer.succeed([])
        else:
            self.sent = True
            return defer.succeed([self.peer])

    def send_next_request(self, peer, protocol):
        return self._send_next_request(peer, protocol)


if __name__ == '__main__':
    sys.exit(main())
