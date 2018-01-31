"""A simple script that attempts to directly download a single blob or stream from a given peer"""
import argparse
import logging
import sys
import tempfile
import time
import shutil
from pprint import pprint

from twisted.internet import defer, reactor, threads

from lbrynet import conf
from lbrynet.core import log_support, Wallet, Peer
from lbrynet.core.SinglePeerDownloader import SinglePeerDownloader
from lbrynet.core.StreamDescriptor import BlobStreamDescriptorReader
from lbrynet.core.BlobManager import DiskBlobManager
from lbrynet.core.HashAnnouncer import DummyHashAnnouncer

log = logging.getLogger()


def main(args=None):
    conf.initialize_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument('peer')
    parser.add_argument('blob_hash')
    parser.add_argument('--timeout', type=int, default=30)
    args = parser.parse_args(args)

    log_support.configure_console(level='DEBUG')
    log_support.configure_twisted()

    if ":" in str(args.peer):
        host, port = str(args.peer).strip().split(":")
    else:
        host = args.peer
        port = 3333

    d = download_it(Peer.Peer(host, int(port)), args.timeout, args.blob_hash)
    d.addErrback(log.exception)
    d.addBoth(lambda _: reactor.callLater(0, reactor.stop))
    reactor.run()


@defer.inlineCallbacks
def download_it(peer, timeout, blob_hash):
    tmp_dir = yield threads.deferToThread(tempfile.mkdtemp)
    announcer = DummyHashAnnouncer()
    tmp_blob_manager = DiskBlobManager(announcer, tmp_dir, tmp_dir)

    config = {'auto_connect': True}
    if conf.settings['lbryum_wallet_dir']:
        config['lbryum_path'] = conf.settings['lbryum_wallet_dir']
    storage = Wallet.InMemoryStorage()
    wallet = Wallet.LBRYumWallet(storage, config)

    downloader = SinglePeerDownloader()
    downloader.setup(wallet)

    try:
        blob_downloaded = yield downloader.download_blob_from_peer(peer, timeout, blob_hash,
                                                                   tmp_blob_manager)
        if blob_downloaded:
            log.info("SUCCESS!")
            blob = yield tmp_blob_manager.get_blob(blob_hash)
            pprint(blob)
            if not blob.verified:
                log.error("except that its not verified....")
            else:
                reader = BlobStreamDescriptorReader(blob)
                info = None
                for x in range(0, 3):
                    try:
                        info = yield reader.get_info()
                    except ValueError:
                        pass
                    if info:
                        break
                    time.sleep(
                        0.1)  # there's some kind of race condition where it sometimes doesnt write the blob to disk in time

                if info is not None:
                    pprint(info)
                    for content_blob in info['blobs']:
                        if 'blob_hash' in content_blob:
                            yield download_it(peer, timeout, content_blob['blob_hash'])
        else:
            log.error("Download failed")
    finally:
        yield tmp_blob_manager.stop()
        yield threads.deferToThread(shutil.rmtree, tmp_dir)

    defer.returnValue(True)


if __name__ == '__main__':
    sys.exit(main())
