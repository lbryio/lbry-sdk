# Script to download the sd_blobs of the front page
# Author: hackrush(hackrush@lbry.io)
import asyncio

from twisted.internet import asyncioreactor
asyncioreactor.install()

import keyring
import logging
import tempfile
import time
import treq
import typing
import shutil

from binascii import unhexlify
from twisted.internet import defer, reactor

from lbrynet import conf, log_support
from lbrynet.p2p.Peer import Peer
from lbrynet.p2p.BlobManager import DiskBlobManager
from lbrynet.p2p import SinglePeerDownloader
from lbrynet.extras.daemon.ComponentManager import ComponentManager
from lbrynet.extras.daemon.Components import DatabaseComponent
from lbrynet.extras.daemon.PeerFinder import DummyPeerFinder
from lbrynet.extras.daemon.storage import SQLiteStorage

log = logging.getLogger()

component_manager = None


def f2d(future):
    return defer.Deferred.fromFuture(asyncio.ensure_future(future))


class FakeAnalytics:
    @property
    def is_started(self):
        return True

    def send_server_startup_success(self):
        pass

    def send_server_startup(self):
        pass

    def shutdown(self):
        pass

    def send_upnp_setup_success_fail(self, success, status):
        pass


class TempDatabaseComponent(DatabaseComponent):
    @defer.inlineCallbacks
    def start(self):
        self.storage = SQLiteStorage(tempfile.tempdir)
        yield self.storage.setup()

    @defer.inlineCallbacks
    def stop(self):
        yield self.storage.stop()
        self.storage = None


class MultiplePeerFinder(DummyPeerFinder):
    def __init__(self, peer):
        super().__init__()
        # This is just a dud!! It has absolutely no use
        self.peer = peer

    @defer.inlineCallbacks
    def find_peers_for_blob(self, blob_hash, timeout=None, filter_self=False):
        dht = component_manager.get_component('dht')
        peers = yield dht.iterativeFindValue(unhexlify(blob_hash))
        peers = [Peer(host, port) for node_id, host, port in peers]
        return peers


# monkeypatching custom peer finder
SinglePeerDownloader.SinglePeerFinder = MultiplePeerFinder


@defer.inlineCallbacks
def download_blob_for_uri(blob_hash: typing.Text):
    tmp_blob_manager = DiskBlobManager(tempfile.tempdir, component_manager.get_component('database'))

    downloader = SinglePeerDownloader.SinglePeerDownloader()
    downloader.setup(component_manager.get_component('wallet'))

    peer = Peer(None, None)  # required for the log statements in SinglePeerDownloader
    result = yield downloader.download_blob_from_peer(peer, 180, blob_hash, tmp_blob_manager)
    tmp_blob_manager.stop()
    return result


async def get_sd_hash_from_uri(uri: typing.Text):
    wallet = component_manager.get_component("wallet")
    resolved = await wallet.resolve(uri)
    sd_hash = resolved[uri]["claim"]["value"]["stream"]["source"]["source"]
    print(sd_hash)
    return sd_hash


@defer.inlineCallbacks
def benchmark_performance(uris: list) -> dict:
    results = dict()
    for uri in uris:
        sd_hash = yield f2d(get_sd_hash_from_uri(uri))

        start = time.time()
        was_download_successful = yield download_blob_for_uri(sd_hash)
        end = time.time()

        if was_download_successful:
            results[uri] = end - start
        else:
            results[uri] = "Could not download"

        print(results[uri], uri, file=open({YOUR OUTPUT FILENAME HERE}, "a"))

    return results


def extract_uris(response):
    uris = list()
    for key in response:
        for value in response[key]:
            uris.append(value)

    return uris


@defer.inlineCallbacks
def get_frontpage_uris():
    kr = keyring.get_keyring()
    c = kr.get_preferred_collection()
    lbry_keyring = None
    for col in c.get_all_items():
        if col.get_label() == "LBRY/auth_token":
            lbry_keyring = col
    lbry_keyring = lbry_keyring.get_secret().decode("ascii")
    response = yield treq.get("https://api.lbry.io/file/list_homepage?auth_token={}".format(lbry_keyring))
    if response.code != 200:
        log.error("API returned non 200 code!!")
        reactor.callLater(0, reactor.stop)

    body = yield response.json()
    uris = extract_uris(body['data']['Uris'])
    return uris


@defer.inlineCallbacks
def main():
    global component_manager
    yield component_manager.setup()
    yield component_manager.get_component('dht')._join_deferred
    uris = yield get_frontpage_uris()
    # uris = [
    #     "linux-kernel-patch-replaces-naughty#e4fc36ac921970b3d15138781d697841dfb745f7",
    #     "linux-thursday-dec-1-2018-linux-y#062615ab5b974f5536b7e3d47731e7c74279ea23",
    #     "what"
    # ]
    results = yield benchmark_performance(uris)
    yield component_manager.stop()
    shutil.rmtree(tempfile.tempdir)

    max_len = len(max(uris, key=len))
    for result, value in results.items():
        print("{0:>{1:d}s}: {2}".format(result, max_len, value))

    reactor.callLater(0, reactor.stop)


if __name__ == "__main__":
    log_support.configure_console(level='INFO')
    log_support.configure_twisted()

    tempfile.tempdir = tempfile.mkdtemp()

    conf.initialize_settings()
    conf.settings.set('download_directory', tempfile.tempdir)
    conf.settings.set('lbryum_wallet_dir', {YOUR WALLET DIRECTORY HERE})
    conf.settings.set('data_dir', tempfile.tempdir)
    conf.settings.set('use_upnp', False)

    skip_components = ["blob_manager", "hash_announcer", "file_manager", "peer_protocol_server", "reflector",
                       "exchange_rate_manager", "rate_limiter", "payment_rate_manager"]
    component_manager = ComponentManager(
        analytics_manager=FakeAnalytics,
        skip_components=skip_components,
        database=TempDatabaseComponent
    )

    main()
    reactor.run()
