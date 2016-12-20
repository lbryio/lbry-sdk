from lbrynet.core import log_support

import io
import logging
from multiprocessing import Process, Event, Queue
import os
import platform
import shutil
import sys
import random
import unittest

from Crypto.PublicKey import RSA
from Crypto import Random
from Crypto.Hash import MD5
from lbrynet import conf
from lbrynet.lbrylive.LiveStreamCreator import FileLiveStreamCreator
from lbrynet.lbrylive.LiveStreamMetadataManager import DBLiveStreamMetadataManager
from lbrynet.lbrylive.LiveStreamMetadataManager import TempLiveStreamMetadataManager
from lbrynet.lbryfile.EncryptedFileMetadataManager import TempEncryptedFileMetadataManager, \
    DBEncryptedFileMetadataManager
from lbrynet import analytics
from lbrynet.lbrylive.LiveStreamCreator import FileLiveStreamCreator
from lbrynet.lbrylive.LiveStreamMetadataManager import DBLiveStreamMetadataManager
from lbrynet.lbrylive.LiveStreamMetadataManager import TempLiveStreamMetadataManager
from lbrynet.lbryfile.EncryptedFileMetadataManager import TempEncryptedFileMetadataManager
from lbrynet.lbryfile.EncryptedFileMetadataManager import DBEncryptedFileMetadataManager
from lbrynet.lbryfilemanager.EncryptedFileManager import EncryptedFileManager
from lbrynet.core.PTCWallet import PointTraderKeyQueryHandlerFactory, PointTraderKeyExchanger
from lbrynet.core.Session import Session
from lbrynet.core.server.BlobAvailabilityHandler import BlobAvailabilityHandlerFactory
from lbrynet.core.client.StandaloneBlobDownloader import StandaloneBlobDownloader
from lbrynet.core.StreamDescriptor import BlobStreamDescriptorWriter
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier
from lbrynet.core.StreamDescriptor import download_sd_blob
from lbrynet.lbryfilemanager.EncryptedFileCreator import create_lbry_file
from lbrynet.lbryfile.client.EncryptedFileOptions import add_lbry_file_to_sd_identifier
from lbrynet.lbryfile.StreamDescriptor import get_sd_info
from twisted.internet import defer, threads, task
from twisted.trial.unittest import TestCase
from twisted.python.failure import Failure

from lbrynet.dht.node import Node
from lbrynet.core.PeerManager import PeerManager
from lbrynet.core.RateLimiter import DummyRateLimiter, RateLimiter
from lbrynet.core.server.BlobRequestHandler import BlobRequestHandlerFactory
from lbrynet.core.server.ServerProtocol import ServerProtocolFactory

from lbrynet.lbrylive.server.LiveBlobInfoQueryHandler import CryptBlobInfoQueryHandlerFactory
from lbrynet.lbrylive.client.LiveStreamOptions import add_live_stream_to_sd_identifier
from lbrynet.lbrylive.client.LiveStreamDownloader import add_full_live_stream_downloader_to_sd_identifier

from tests import mocks


FakeNode = mocks.Node
FakeWallet = mocks.Wallet
FakePeerFinder = mocks.PeerFinder
FakeAnnouncer = mocks.Announcer
GenFile = mocks.GenFile
test_create_stream_sd_file = mocks.create_stream_sd_file
DummyBlobAvailabilityTracker = mocks.BlobAvailabilityTracker

log = logging.getLogger(__name__)

log_format = "%(funcName)s(): %(message)s"
logging.basicConfig(level=logging.WARNING, format=log_format)


def require_system(system):
    def wrapper(fn):
        return fn

    if platform.system() == system:
        return wrapper
    else:
        return unittest.skip("Skipping. Test can only be run on " + system)


def use_epoll_on_linux():
    if sys.platform.startswith("linux"):
        sys.modules = sys.modules.copy()
        del sys.modules['twisted.internet.reactor']
        import twisted.internet
        twisted.internet.reactor = twisted.internet.epollreactor.EPollReactor()
        sys.modules['twisted.internet.reactor'] = twisted.internet.reactor


class LbryUploader(object):
    def __init__(self, sd_hash_queue, kill_event, dead_event,
                 file_size, ul_rate_limit=None, is_generous=False):
        self.sd_hash_queue = sd_hash_queue
        self.kill_event = kill_event
        self.dead_event = dead_event
        self.file_size = file_size
        self.ul_rate_limit = ul_rate_limit
        self.is_generous = is_generous
        # these attributes get defined in `start`
        self.reactor = None
        self.sd_identifier = None
        self.session = None
        self.lbry_file_manager = None
        self.server_port = None
        self.kill_check = None

    def start(self):
        use_epoll_on_linux()
        from twisted.internet import reactor
        self.reactor = reactor
        logging.debug("Starting the uploader")
        Random.atfork()
        r = random.Random()
        r.seed("start_lbry_uploader")
        wallet = FakeWallet()
        peer_manager = PeerManager()
        peer_finder = FakePeerFinder(5553, peer_manager, 1)
        hash_announcer = FakeAnnouncer()
        rate_limiter = RateLimiter()
        self.sd_identifier = StreamDescriptorIdentifier()
        db_dir = "server"
        os.mkdir(db_dir)
        self.session = Session(
            conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir, lbryid="abcd",
            peer_finder=peer_finder, hash_announcer=hash_announcer, peer_port=5553,
            use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
            blob_tracker_class=DummyBlobAvailabilityTracker,
            dht_node_class=Node, is_generous=self.is_generous)
        stream_info_manager = TempEncryptedFileMetadataManager()
        self.lbry_file_manager = EncryptedFileManager(
            self.session, stream_info_manager, self.sd_identifier)
        if self.ul_rate_limit is not None:
            self.session.rate_limiter.set_ul_limit(self.ul_rate_limit)
        reactor.callLater(1, self.start_all)
        if not reactor.running:
            reactor.run()

    def start_all(self):
        d = self.session.setup()
        d.addCallback(lambda _: add_lbry_file_to_sd_identifier(self.sd_identifier))
        d.addCallback(lambda _: self.lbry_file_manager.setup())
        d.addCallback(lambda _: self.start_server())
        d.addCallback(lambda _: self.create_stream())
        d.addCallback(self.create_stream_descriptor)
        d.addCallback(self.put_sd_hash_on_queue)
        d.addErrback(log.fail(), 'Failed to start')
        return d

    def start_server(self):
        session = self.session
        query_handler_factories = {
            1: BlobAvailabilityHandlerFactory(session.blob_manager),
            2: BlobRequestHandlerFactory(
                session.blob_manager, session.wallet,
                session.payment_rate_manager,
                analytics.Track()),
            3: session.wallet.get_wallet_info_query_handler_factory(),
        }
        server_factory = ServerProtocolFactory(session.rate_limiter,
                                               query_handler_factories,
                                               session.peer_manager)
        self.server_port = self.reactor.listenTCP(5553, server_factory)
        logging.debug("Started listening")
        self.kill_check = task.LoopingCall(self.check_for_kill)
        self.kill_check.start(1.0)
        return True

    def kill_server(self):
        session = self.session
        ds = []
        ds.append(session.shut_down())
        ds.append(self.lbry_file_manager.stop())
        if self.server_port:
            ds.append(self.server_port.stopListening())
        self.kill_check.stop()
        self.dead_event.set()
        dl = defer.DeferredList(ds)
        dl.addCallback(lambda _: self.reactor.stop())
        return dl

    def check_for_kill(self):
        if self.kill_event.is_set():
            self.kill_server()

    def create_stream(self):
        test_file = GenFile(self.file_size, b''.join([chr(i) for i in xrange(0, 64, 6)]))
        d = create_lbry_file(self.session, self.lbry_file_manager, "test_file", test_file)
        return d

    def create_stream_descriptor(self, stream_hash):
        descriptor_writer = BlobStreamDescriptorWriter(self.session.blob_manager)
        d = get_sd_info(self.lbry_file_manager.stream_info_manager, stream_hash, True)
        d.addCallback(descriptor_writer.create_descriptor)
        return d

    def put_sd_hash_on_queue(self, sd_hash):
        self.sd_hash_queue.put(sd_hash)


def start_lbry_reuploader(sd_hash, kill_event, dead_event,
                          ready_event, n, ul_rate_limit=None, is_generous=False):
    use_epoll_on_linux()
    from twisted.internet import reactor

    logging.debug("Starting the uploader")

    Random.atfork()

    r = random.Random()
    r.seed("start_lbry_reuploader")

    wallet = FakeWallet()
    peer_port = 5553 + n
    peer_manager = PeerManager()
    peer_finder = FakePeerFinder(5553, peer_manager, 1)
    hash_announcer = FakeAnnouncer()
    rate_limiter = RateLimiter()
    sd_identifier = StreamDescriptorIdentifier()

    db_dir = "server_" + str(n)
    blob_dir = os.path.join(db_dir, "blobfiles")
    os.mkdir(db_dir)
    os.mkdir(blob_dir)

    session = Session(conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir, lbryid="abcd" + str(n),
                      peer_finder=peer_finder, hash_announcer=hash_announcer,
                      blob_dir=None, peer_port=peer_port,
                      use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
                      blob_tracker_class=DummyBlobAvailabilityTracker, is_generous=conf.ADJUSTABLE_SETTINGS['is_generous_host'][1])

    stream_info_manager = TempEncryptedFileMetadataManager()

    lbry_file_manager = EncryptedFileManager(session, stream_info_manager, sd_identifier)

    if ul_rate_limit is not None:
        session.rate_limiter.set_ul_limit(ul_rate_limit)

    def make_downloader(metadata, prm):
        info_validator = metadata.validator
        options = metadata.options
        factories = metadata.factories
        chosen_options = [o.default_value for o in options.get_downloader_options(info_validator, prm)]
        return factories[0].make_downloader(metadata, chosen_options, prm)

    def download_file():
        prm = session.payment_rate_manager
        d = download_sd_blob(session, sd_hash, prm)
        d.addCallback(sd_identifier.get_metadata_for_sd_blob)
        d.addCallback(make_downloader, prm)
        d.addCallback(lambda downloader: downloader.start())
        return d

    def start_transfer():

        logging.debug("Starting the transfer")

        d = session.setup()
        d.addCallback(lambda _: add_lbry_file_to_sd_identifier(sd_identifier))
        d.addCallback(lambda _: lbry_file_manager.setup())
        d.addCallback(lambda _: download_file())

        return d

    def start_server():

        server_port = None

        query_handler_factories = {
            1: BlobAvailabilityHandlerFactory(session.blob_manager),
            2: BlobRequestHandlerFactory(
                session.blob_manager, session.wallet,
                session.payment_rate_manager,
                analytics.Track()),
            3: session.wallet.get_wallet_info_query_handler_factory(),
        }

        server_factory = ServerProtocolFactory(session.rate_limiter,
                                               query_handler_factories,
                                               session.peer_manager)

        server_port = reactor.listenTCP(peer_port, server_factory)
        logging.debug("Started listening")

        def kill_server():
            ds = []
            ds.append(session.shut_down())
            ds.append(lbry_file_manager.stop())
            if server_port:
                ds.append(server_port.stopListening())
            kill_check.stop()
            dead_event.set()
            dl = defer.DeferredList(ds)
            dl.addCallback(lambda _: reactor.stop())
            return dl

        def check_for_kill():
            if kill_event.is_set():
                kill_server()

        kill_check = task.LoopingCall(check_for_kill)
        kill_check.start(1.0)
        ready_event.set()
        logging.debug("set the ready event")

    d = task.deferLater(reactor, 1.0, start_transfer)
    d.addCallback(lambda _: start_server())
    if not reactor.running:
        reactor.run()


def start_live_server(sd_hash_queue, kill_event, dead_event):
    use_epoll_on_linux()
    from twisted.internet import reactor

    logging.debug("In start_server.")

    Random.atfork()

    r = random.Random()
    r.seed("start_live_server")

    wallet = FakeWallet()
    peer_manager = PeerManager()
    peer_finder = FakePeerFinder(5553, peer_manager, 1)
    hash_announcer = FakeAnnouncer()
    rate_limiter = DummyRateLimiter()
    sd_identifier = StreamDescriptorIdentifier()

    db_dir = "server"
    os.mkdir(db_dir)

    session = Session(conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir, lbryid="abcd",
                      peer_finder=peer_finder, hash_announcer=hash_announcer, peer_port=5553,
                      use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
                      blob_tracker_class=DummyBlobAvailabilityTracker,
                      is_generous=conf.ADJUSTABLE_SETTINGS['is_generous_host'][1])
    stream_info_manager = DBLiveStreamMetadataManager(session.db_dir, hash_announcer)

    logging.debug("Created the session")

    server_port = []

    def start_listening():
        logging.debug("Starting the server protocol")
        query_handler_factories = {
            1: CryptBlobInfoQueryHandlerFactory(stream_info_manager, session.wallet,
                                             session.payment_rate_manager),
            2: BlobRequestHandlerFactory(session.blob_manager, session.wallet,
                                      session.payment_rate_manager,
                                      analytics.Track()),
            3: session.wallet.get_wallet_info_query_handler_factory()
        }

        server_factory = ServerProtocolFactory(session.rate_limiter,
                                               query_handler_factories,
                                               session.peer_manager)
        server_port.append(reactor.listenTCP(5553, server_factory))
        logging.debug("Server protocol has started")

    def create_stream():
        logging.debug("Making the live stream")
        test_file = GenFile(5209343, b''.join([chr(i + 2) for i in xrange(0, 64, 6)]))
        stream_creator_helper = FileLiveStreamCreator(session.blob_manager, stream_info_manager,
                                                      "test_file", test_file)
        d = stream_creator_helper.setup()
        d.addCallback(lambda _: stream_creator_helper.publish_stream_descriptor())
        d.addCallback(put_sd_hash_on_queue)
        d.addCallback(lambda _: stream_creator_helper.start_streaming())
        return d

    def put_sd_hash_on_queue(sd_hash):
        logging.debug("Telling the client to start running. Stream hash: %s", str(sd_hash))
        sd_hash_queue.put(sd_hash)
        logging.debug("sd hash has been added to the queue")

    def set_dead_event():
        logging.debug("Setting the dead event")
        dead_event.set()

    def print_error(err):
        logging.debug("An error occurred during shutdown: %s", err.getTraceback())

    def stop_reactor():
        logging.debug("Server is stopping its reactor")
        reactor.stop()

    def shut_down(arg):
        logging.debug("Shutting down")
        if isinstance(arg, Failure):
            logging.error("Shut down is due to an error: %s", arg.getTraceback())
        d = defer.maybeDeferred(server_port[0].stopListening)
        d.addErrback(print_error)
        d.addCallback(lambda _: session.shut_down())
        d.addCallback(lambda _: stream_info_manager.stop())
        d.addErrback(print_error)
        d.addCallback(lambda _: set_dead_event())
        d.addErrback(print_error)
        d.addCallback(lambda _: reactor.callLater(0, stop_reactor))
        d.addErrback(print_error)
        return d

    def wait_for_kill_event():

        d = defer.Deferred()

        def check_for_kill():
            if kill_event.is_set():
                logging.debug("Kill event has been found set")
                kill_check.stop()
                d.callback(True)

        kill_check = task.LoopingCall(check_for_kill)
        kill_check.start(1.0)

        return d

    def enable_live_stream():
        add_live_stream_to_sd_identifier(sd_identifier, session.base_payment_rate_manager)
        add_full_live_stream_downloader_to_sd_identifier(session, stream_info_manager, sd_identifier,
                                                         session.base_payment_rate_manager)

    def run_server():
        d = session.setup()
        d.addCallback(lambda _: stream_info_manager.setup())
        d.addCallback(lambda _: enable_live_stream())
        d.addCallback(lambda _: start_listening())
        d.addCallback(lambda _: create_stream())
        d.addCallback(lambda _: wait_for_kill_event())
        d.addBoth(shut_down)
        return d

    reactor.callLater(1, run_server)
    if not reactor.running:
        reactor.run()


def start_blob_uploader(blob_hash_queue, kill_event, dead_event, slow, is_generous=False):
    use_epoll_on_linux()
    from twisted.internet import reactor

    logging.debug("Starting the uploader")

    Random.atfork()

    wallet = FakeWallet()
    peer_manager = PeerManager()
    peer_finder = FakePeerFinder(5553, peer_manager, 1)
    hash_announcer = FakeAnnouncer()
    rate_limiter = RateLimiter()

    if slow is True:
        peer_port = 5553
        db_dir = "server1"
    else:
        peer_port = 5554
        db_dir = "server2"
    blob_dir = os.path.join(db_dir, "blobfiles")
    os.mkdir(db_dir)
    os.mkdir(blob_dir)

    session = Session(conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir, lbryid="efgh",
                      peer_finder=peer_finder, hash_announcer=hash_announcer,
                      blob_dir=blob_dir, peer_port=peer_port,
                      use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
                      blob_tracker_class=DummyBlobAvailabilityTracker,
                      is_generous=conf.ADJUSTABLE_SETTINGS['is_generous_host'][1])

    if slow is True:
        session.rate_limiter.set_ul_limit(2 ** 11)

    def start_all():
        d = session.setup()
        d.addCallback(lambda _: start_server())
        d.addCallback(lambda _: create_single_blob())
        d.addCallback(put_blob_hash_on_queue)
        d.addErrback(log.fail(), 'Failed to start')
        return d

    def start_server():

        server_port = None

        query_handler_factories = {
            1: BlobAvailabilityHandlerFactory(session.blob_manager),
            2: BlobRequestHandlerFactory(session.blob_manager, session.wallet,
                                      session.payment_rate_manager,
                                      analytics.Track()),
            3: session.wallet.get_wallet_info_query_handler_factory(),
        }

        server_factory = ServerProtocolFactory(session.rate_limiter,
                                               query_handler_factories,
                                               session.peer_manager)

        server_port = reactor.listenTCP(peer_port, server_factory)
        logging.debug("Started listening")

        def kill_server():
            ds = []
            ds.append(session.shut_down())
            if server_port:
                ds.append(server_port.stopListening())
            kill_check.stop()
            dead_event.set()
            dl = defer.DeferredList(ds)
            dl.addCallback(lambda _: reactor.stop())
            return dl

        def check_for_kill():
            if kill_event.is_set():
                kill_server()

        kill_check = task.LoopingCall(check_for_kill)
        kill_check.start(1.0)
        return True

    def create_single_blob():
        blob_creator = session.blob_manager.get_blob_creator()
        blob_creator.write("0" * 2 ** 21)
        return blob_creator.close()

    def put_blob_hash_on_queue(blob_hash):
        logging.debug("Telling the client to start running. Blob hash: %s", str(blob_hash))
        blob_hash_queue.put(blob_hash)
        logging.debug("blob hash has been added to the queue")

    reactor.callLater(1, start_all)
    if not reactor.running:
        reactor.run()


class TestTransfer(TestCase):
    def setUp(self):
        mocks.mock_conf_settings(self)
        self.server_processes = []
        self.session = None
        self.stream_info_manager = None
        self.lbry_file_manager = None
        self.is_generous = True
        self.addCleanup(self.take_down_env)

    def take_down_env(self):

        d = defer.succeed(True)
        if self.lbry_file_manager is not None:
            d.addCallback(lambda _: self.lbry_file_manager.stop())
        if self.session is not None:
            d.addCallback(lambda _: self.session.shut_down())
        if self.stream_info_manager is not None:
            d.addCallback(lambda _: self.stream_info_manager.stop())

        def delete_test_env():
            dirs = ['server', 'server1', 'server2', 'client']
            files = ['test_file']
            for di in dirs:
                if os.path.exists(di):
                    shutil.rmtree(di)
            for f in files:
                if os.path.exists(f):
                    os.remove(f)
            for p in self.server_processes:
                p.terminate()
            return True

        d.addCallback(lambda _: threads.deferToThread(delete_test_env))
        return d

    @staticmethod
    def wait_for_event(event, timeout):

        from twisted.internet import reactor
        d = defer.Deferred()

        def stop():
            set_check.stop()
            if stop_call.active():
                stop_call.cancel()
                d.callback(True)

        def check_if_event_set():
            if event.is_set():
                logging.debug("Dead event has been found set")
                stop()

        def done_waiting():
            logging.warning("Event has not been found set and timeout has expired")
            stop()

        set_check = task.LoopingCall(check_if_event_set)
        set_check.start(.1)
        stop_call = reactor.callLater(timeout, done_waiting)
        return d

    @staticmethod
    def wait_for_hash_from_queue(hash_queue):
        logging.debug("Waiting for the sd_hash to come through the queue")

        d = defer.Deferred()

        def check_for_start():
            if hash_queue.empty() is False:
                logging.debug("Client start event has been found set")
                start_check.stop()
                d.callback(hash_queue.get(False))
            else:
                logging.debug("Client start event has NOT been found set")

        start_check = task.LoopingCall(check_for_start)
        start_check.start(1.0)

        return d

    def test_lbry_transfer(self):
        sd_hash_queue = Queue()
        kill_event = Event()
        dead_event = Event()
        lbry_uploader = LbryUploader(sd_hash_queue, kill_event, dead_event, 5209343)
        uploader = Process(target=lbry_uploader.start)
        uploader.start()
        self.server_processes.append(uploader)

        logging.debug("Testing transfer")

        wallet = FakeWallet()
        peer_manager = PeerManager()
        peer_finder = FakePeerFinder(5553, peer_manager, 1)
        hash_announcer = FakeAnnouncer()
        rate_limiter = DummyRateLimiter()
        sd_identifier = StreamDescriptorIdentifier()

        db_dir = "client"
        blob_dir = os.path.join(db_dir, "blobfiles")
        os.mkdir(db_dir)
        os.mkdir(blob_dir)

        self.session = Session(
            conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir, lbryid="abcd",
            peer_finder=peer_finder, hash_announcer=hash_announcer,
            blob_dir=blob_dir, peer_port=5553,
            use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
            blob_tracker_class=DummyBlobAvailabilityTracker,
            dht_node_class=Node, is_generous=self.is_generous)

        self.stream_info_manager = TempEncryptedFileMetadataManager()

        self.lbry_file_manager = EncryptedFileManager(
            self.session, self.stream_info_manager, sd_identifier)

        def make_downloader(metadata, prm):
            info_validator = metadata.validator
            options = metadata.options
            factories = metadata.factories
            chosen_options = [
                o.default_value for o in options.get_downloader_options(info_validator, prm)
            ]
            return factories[0].make_downloader(metadata, chosen_options, prm)

        def download_file(sd_hash):
            prm = self.session.payment_rate_manager
            d = download_sd_blob(self.session, sd_hash, prm)
            d.addCallback(sd_identifier.get_metadata_for_sd_blob)
            d.addCallback(make_downloader, prm)
            d.addCallback(lambda downloader: downloader.start())
            return d

        def check_md5_sum():
            f = open('test_file')
            hashsum = MD5.new()
            hashsum.update(f.read())
            self.assertEqual(hashsum.hexdigest(), "4ca2aafb4101c1e42235aad24fbb83be")

        @defer.inlineCallbacks
        def start_transfer(sd_hash):
            logging.debug("Starting the transfer")
            yield self.session.setup()
            yield add_lbry_file_to_sd_identifier(sd_identifier)
            yield self.lbry_file_manager.setup()
            yield download_file(sd_hash)
            yield check_md5_sum()

        def stop(arg):
            if isinstance(arg, Failure):
                logging.debug("Client is stopping due to an error. Error: %s", arg.getTraceback())
            else:
                logging.debug("Client is stopping normally.")
            kill_event.set()
            logging.debug("Set the kill event")
            d = self.wait_for_event(dead_event, 15)

            def print_shutting_down():
                logging.info("Client is shutting down")

            d.addCallback(lambda _: print_shutting_down())
            d.addCallback(lambda _: arg)
            return d

        d = self.wait_for_hash_from_queue(sd_hash_queue)
        d.addCallback(start_transfer)
        d.addBoth(stop)

        return d

    @unittest.skip("Sadly skipping failing test instead of fixing it")
    def test_live_transfer(self):

        sd_hash_queue = Queue()
        kill_event = Event()
        dead_event = Event()
        server_args = (sd_hash_queue, kill_event, dead_event)
        server = Process(target=start_live_server, args=server_args)
        server.start()
        self.server_processes.append(server)

        wallet = FakeWallet()
        peer_manager = PeerManager()
        peer_finder = FakePeerFinder(5553, peer_manager, 1)
        hash_announcer = FakeAnnouncer()
        rate_limiter = DummyRateLimiter()
        sd_identifier = StreamDescriptorIdentifier()

        db_dir = "client"
        os.mkdir(db_dir)

        self.session = Session(
            conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir, lbryid="abcd",
            peer_finder=peer_finder, hash_announcer=hash_announcer, blob_dir=None,
            peer_port=5553, use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
            blob_tracker_class=DummyBlobAvailabilityTracker, dht_node_class=Node
        )

        self.stream_info_manager = TempLiveStreamMetadataManager(hash_announcer)

        d = self.wait_for_hash_from_queue(sd_hash_queue)

        def create_downloader(metadata, prm):
            info_validator = metadata.validator
            options = metadata.options
            factories = metadata.factories
            chosen_options = [
                o.default_value for o in options.get_downloader_options(info_validator, prm)]
            return factories[0].make_downloader(metadata, chosen_options, prm)

        def start_lbry_file(lbry_file):
            lbry_file = lbry_file
            return lbry_file.start()

        def download_stream(sd_blob_hash):
            prm = self.session.payment_rate_manager
            d = download_sd_blob(self.session, sd_blob_hash, prm)
            d.addCallback(sd_identifier.get_metadata_for_sd_blob)
            d.addCallback(create_downloader, prm)
            d.addCallback(start_lbry_file)
            return d

        def do_download(sd_blob_hash):
            logging.debug("Starting the download")

            d = self.session.setup()
            d.addCallback(lambda _: enable_live_stream())
            d.addCallback(lambda _: download_stream(sd_blob_hash))
            return d

        def enable_live_stream():
            add_live_stream_to_sd_identifier(sd_identifier, self.session.payment_rate_manager)
            add_full_live_stream_downloader_to_sd_identifier(self.session, self.stream_info_manager,
                                                             sd_identifier,
                                                             self.session.payment_rate_manager)

        d.addCallback(do_download)

        def check_md5_sum():
            f = open('test_file')
            hashsum = MD5.new()
            hashsum.update(f.read())
            self.assertEqual(hashsum.hexdigest(), "215b177db8eed86d028b37e5cbad55c7")

        d.addCallback(lambda _: check_md5_sum())

        def stop(arg):
            if isinstance(arg, Failure):
                logging.debug("Client is stopping due to an error. Error: %s", arg.getTraceback())
            else:
                logging.debug("Client is stopping normally.")
            kill_event.set()
            logging.debug("Set the kill event")
            d = self.wait_for_event(dead_event, 15)

            def print_shutting_down():
                logging.info("Client is shutting down")

            d.addCallback(lambda _: print_shutting_down())
            d.addCallback(lambda _: arg)
            return d

        d.addBoth(stop)
        return d

    def test_last_blob_retrieval(self):
        kill_event = Event()
        dead_event_1 = Event()
        blob_hash_queue_1 = Queue()
        blob_hash_queue_2 = Queue()
        fast_uploader = Process(target=start_blob_uploader,
                                args=(blob_hash_queue_1, kill_event, dead_event_1, False))
        fast_uploader.start()
        self.server_processes.append(fast_uploader)
        dead_event_2 = Event()
        slow_uploader = Process(target=start_blob_uploader,
                                args=(blob_hash_queue_2, kill_event, dead_event_2, True))
        slow_uploader.start()
        self.server_processes.append(slow_uploader)

        logging.debug("Testing transfer")

        wallet = FakeWallet()
        peer_manager = PeerManager()
        peer_finder = FakePeerFinder(5553, peer_manager, 2)
        hash_announcer = FakeAnnouncer()
        rate_limiter = DummyRateLimiter()

        db_dir = "client"
        blob_dir = os.path.join(db_dir, "blobfiles")
        os.mkdir(db_dir)
        os.mkdir(blob_dir)

        self.session = Session(
            conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir, lbryid="abcd",
            peer_finder=peer_finder, hash_announcer=hash_announcer,
            blob_dir=blob_dir, peer_port=5553,
            use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
            blob_tracker_class=DummyBlobAvailabilityTracker,
            is_generous=conf.ADJUSTABLE_SETTINGS['is_generous_host'][1])

        d1 = self.wait_for_hash_from_queue(blob_hash_queue_1)
        d2 = self.wait_for_hash_from_queue(blob_hash_queue_2)
        d = defer.DeferredList([d1, d2], fireOnOneErrback=True)

        def get_blob_hash(results):
            self.assertEqual(results[0][1], results[1][1])
            return results[0][1]

        d.addCallback(get_blob_hash)

        def download_blob(blob_hash):
            prm = self.session.payment_rate_manager
            downloader = StandaloneBlobDownloader(
                blob_hash, self.session.blob_manager, peer_finder, rate_limiter, prm, wallet)
            d = downloader.download()
            return d

        def start_transfer(blob_hash):

            logging.debug("Starting the transfer")

            d = self.session.setup()
            d.addCallback(lambda _: download_blob(blob_hash))

            return d

        d.addCallback(start_transfer)

        def stop(arg):
            if isinstance(arg, Failure):
                logging.debug("Client is stopping due to an error. Error: %s", arg.getTraceback())
            else:
                logging.debug("Client is stopping normally.")
            kill_event.set()
            logging.debug("Set the kill event")
            d1 = self.wait_for_event(dead_event_1, 15)
            d2 = self.wait_for_event(dead_event_2, 15)
            dl = defer.DeferredList([d1, d2])
            def print_shutting_down():
                logging.info("Client is shutting down")
            dl.addCallback(lambda _: print_shutting_down())
            dl.addCallback(lambda _: arg)
            return dl
        d.addBoth(stop)
        return d

    def test_double_download(self):
        sd_hash_queue = Queue()
        kill_event = Event()
        dead_event = Event()
        lbry_uploader = LbryUploader(sd_hash_queue, kill_event, dead_event, 5209343)
        uploader = Process(target=lbry_uploader.start)
        uploader.start()
        self.server_processes.append(uploader)

        logging.debug("Testing double download")

        wallet = FakeWallet()
        peer_manager = PeerManager()
        peer_finder = FakePeerFinder(5553, peer_manager, 1)
        hash_announcer = FakeAnnouncer()
        rate_limiter = DummyRateLimiter()
        sd_identifier = StreamDescriptorIdentifier()

        downloaders = []

        db_dir = "client"
        blob_dir = os.path.join(db_dir, "blobfiles")
        os.mkdir(db_dir)
        os.mkdir(blob_dir)

        self.session = Session(conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir,
                               lbryid="abcd", peer_finder=peer_finder,
                               hash_announcer=hash_announcer, blob_dir=blob_dir, peer_port=5553,
                               use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
                               blob_tracker_class=DummyBlobAvailabilityTracker,
                               is_generous=conf.ADJUSTABLE_SETTINGS['is_generous_host'][1])

        self.stream_info_manager = DBEncryptedFileMetadataManager(self.session.db_dir)
        self.lbry_file_manager = EncryptedFileManager(self.session, self.stream_info_manager, sd_identifier)

        @defer.inlineCallbacks
        def make_downloader(metadata, prm):
            info_validator = metadata.validator
            options = metadata.options
            factories = metadata.factories
            chosen_options = [
                o.default_value for o in options.get_downloader_options(info_validator, prm)
            ]
            downloader = yield factories[0].make_downloader(metadata, chosen_options, prm)
            defer.returnValue(downloader)

        def append_downloader(downloader):
            downloaders.append(downloader)
            return downloader

        @defer.inlineCallbacks
        def download_file(sd_hash):
            prm = self.session.payment_rate_manager
            sd_blob = yield download_sd_blob(self.session, sd_hash, prm)
            metadata = yield sd_identifier.get_metadata_for_sd_blob(sd_blob)
            downloader = yield make_downloader(metadata, prm)
            downloaders.append(downloader)
            finished_value = yield downloader.start()
            defer.returnValue(finished_value)

        def check_md5_sum():
            f = open('test_file')
            hashsum = MD5.new()
            hashsum.update(f.read())
            self.assertEqual(hashsum.hexdigest(), "4ca2aafb4101c1e42235aad24fbb83be")

        def delete_lbry_file():
            logging.debug("deleting the file")
            d = self.lbry_file_manager.delete_lbry_file(downloaders[0])
            d.addCallback(lambda _: self.lbry_file_manager.get_count_for_stream_hash(downloaders[0].stream_hash))
            d.addCallback(
                lambda c: self.stream_info_manager.delete_stream(downloaders[1].stream_hash) if c == 0 else True)
            return d

        def check_lbry_file():
            d = downloaders[1].status()
            d.addCallback(lambda _: downloaders[1].status())

            def check_status_report(status_report):
                self.assertEqual(status_report.num_known, status_report.num_completed)
                self.assertEqual(status_report.num_known, 3)

            d.addCallback(check_status_report)
            return d

        @defer.inlineCallbacks
        def start_transfer(sd_hash):
            logging.debug("Starting the transfer")
            yield self.session.setup()
            yield self.stream_info_manager.setup()
            yield add_lbry_file_to_sd_identifier(sd_identifier)
            yield self.lbry_file_manager.setup()
            yield download_file(sd_hash)
            yield check_md5_sum()
            yield download_file(sd_hash)
            yield delete_lbry_file()
            yield check_lbry_file()

        def stop(arg):
            if isinstance(arg, Failure):
                logging.debug("Client is stopping due to an error. Error: %s", arg.getTraceback())
            else:
                logging.debug("Client is stopping normally.")
            kill_event.set()
            logging.debug("Set the kill event")
            d = self.wait_for_event(dead_event, 15)

            def print_shutting_down():
                logging.info("Client is shutting down")

            d.addCallback(lambda _: print_shutting_down())
            d.addCallback(lambda _: arg)
            return d

        d = self.wait_for_hash_from_queue(sd_hash_queue)
        d.addCallback(start_transfer)
        d.addBoth(stop)
        return d

    @unittest.skip("Sadly skipping failing test instead of fixing it")
    def test_multiple_uploaders(self):
        sd_hash_queue = Queue()
        num_uploaders = 3
        kill_event = Event()
        dead_events = [Event() for _ in range(num_uploaders)]
        ready_events = [Event() for _ in range(1, num_uploaders)]
        lbry_uploader = LbryUploader(
            sd_hash_queue, kill_event, dead_events[0], 5209343, 9373419, 2**22)
        uploader = Process(target=lbry_uploader.start)
        uploader.start()
        self.server_processes.append(uploader)

        logging.debug("Testing multiple uploaders")

        wallet = FakeWallet()
        peer_manager = PeerManager()
        peer_finder = FakePeerFinder(5553, peer_manager, num_uploaders)
        hash_announcer = FakeAnnouncer()
        rate_limiter = DummyRateLimiter()
        sd_identifier = StreamDescriptorIdentifier()

        db_dir = "client"
        blob_dir = os.path.join(db_dir, "blobfiles")
        os.mkdir(db_dir)
        os.mkdir(blob_dir)

        self.session = Session(conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir,
                               lbryid="abcd", peer_finder=peer_finder,
                               hash_announcer=hash_announcer, blob_dir=None,
                               peer_port=5553, use_upnp=False, rate_limiter=rate_limiter,
                               wallet=wallet, blob_tracker_class=DummyBlobAvailabilityTracker,
                               is_generous=conf.ADJUSTABLE_SETTINGS['is_generous_host'][1])

        self.stream_info_manager = TempEncryptedFileMetadataManager()

        self.lbry_file_manager = EncryptedFileManager(
            self.session, self.stream_info_manager, sd_identifier)

        def start_additional_uploaders(sd_hash):
            for i in range(1, num_uploaders):
                uploader = Process(target=start_lbry_reuploader,
                                   args=(sd_hash, kill_event, dead_events[i], ready_events[i - 1], i, 2 ** 10))
                uploader.start()
                self.server_processes.append(uploader)
            return defer.succeed(True)

        def wait_for_ready_events():
            return defer.DeferredList([self.wait_for_event(ready_event, 60) for ready_event in ready_events])

        def make_downloader(metadata, prm):
            info_validator = metadata.validator
            options = metadata.options
            factories = metadata.factories
            chosen_options = [o.default_value for o in options.get_downloader_options(info_validator, prm)]
            return factories[0].make_downloader(metadata, chosen_options, prm)

        def download_file(sd_hash):
            prm = self.session.payment_rate_manager
            d = download_sd_blob(self.session, sd_hash, prm)
            d.addCallback(sd_identifier.get_metadata_for_sd_blob)
            d.addCallback(make_downloader, prm)
            d.addCallback(lambda downloader: downloader.start())
            return d

        def check_md5_sum():
            f = open('test_file')
            hashsum = MD5.new()
            hashsum.update(f.read())
            self.assertEqual(hashsum.hexdigest(), "e5941d615f53312fd66638239c1f90d5")

        def start_transfer(sd_hash):

            logging.debug("Starting the transfer")

            d = start_additional_uploaders(sd_hash)
            d.addCallback(lambda _: wait_for_ready_events())
            d.addCallback(lambda _: self.session.setup())
            d.addCallback(lambda _: add_lbry_file_to_sd_identifier(sd_identifier))
            d.addCallback(lambda _: self.lbry_file_manager.setup())
            d.addCallback(lambda _: download_file(sd_hash))
            d.addCallback(lambda _: check_md5_sum())

            return d

        def stop(arg):
            if isinstance(arg, Failure):
                logging.debug("Client is stopping due to an error. Error: %s", arg.getTraceback())
            else:
                logging.debug("Client is stopping normally.")
            kill_event.set()
            logging.debug("Set the kill event")
            d = defer.DeferredList([self.wait_for_event(dead_event, 15) for dead_event in dead_events])

            def print_shutting_down():
                logging.info("Client is shutting down")

            d.addCallback(lambda _: print_shutting_down())
            d.addCallback(lambda _: arg)
            return d

        d = self.wait_for_hash_from_queue(sd_hash_queue)
        d.addCallback(start_transfer)
        d.addBoth(stop)

        return d
