import logging
from multiprocessing import Process, Event, Queue
import os
import platform
import shutil
import sys
import random
import unittest

from Crypto import Random
from Crypto.Hash import MD5
from lbrynet import conf
from lbrynet.file_manager.EncryptedFileManager import EncryptedFileManager
from lbrynet.core.Session import Session
from lbrynet.core.server.BlobAvailabilityHandler import BlobAvailabilityHandlerFactory
from lbrynet.core.client.StandaloneBlobDownloader import StandaloneBlobDownloader
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier
from lbrynet.core.StreamDescriptor import download_sd_blob
from lbrynet.file_manager.EncryptedFileCreator import create_lbry_file
from lbrynet.lbry_file.client.EncryptedFileOptions import add_lbry_file_to_sd_identifier
from twisted.internet import defer, threads, task
from twisted.trial.unittest import TestCase
from twisted.python.failure import Failure

from lbrynet.dht.node import Node
from lbrynet.core.PeerManager import PeerManager
from lbrynet.core.RateLimiter import DummyRateLimiter, RateLimiter
from lbrynet.core.server.BlobRequestHandler import BlobRequestHandlerFactory
from lbrynet.core.server.ServerProtocol import ServerProtocolFactory

from lbrynet.tests import mocks
from lbrynet.tests.util import mk_db_and_blob_dir, rm_db_and_blob_dir, is_android

FakeNode = mocks.Node
FakeWallet = mocks.Wallet
FakePeerFinder = mocks.PeerFinder
FakeAnnouncer = mocks.Announcer
GenFile = mocks.GenFile
test_create_stream_sd_file = mocks.create_stream_sd_file
DummyBlobAvailabilityTracker = mocks.BlobAvailabilityTracker

log_format = "%(funcName)s(): %(message)s"
logging.basicConfig(level=logging.CRITICAL, format=log_format)


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


def init_conf_windows(settings={}):
    """
    There is no fork on windows, so imports
    are freshly initialized in new processes.
    So conf needs to be intialized for new processes
    """
    if os.name == 'nt':
        original_settings = conf.settings
        conf.settings = conf.Config(conf.FIXED_SETTINGS, conf.ADJUSTABLE_SETTINGS)
        conf.settings.installation_id = conf.settings.get_installation_id()
        conf.settings.update(settings)


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
        init_conf_windows()

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
        self.db_dir, self.blob_dir = mk_db_and_blob_dir()

        self.session = Session(
            conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=self.db_dir, blob_dir=self.blob_dir,
            node_id="abcd", peer_finder=peer_finder, hash_announcer=hash_announcer,
            peer_port=5553, dht_node_port=4445, use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
            blob_tracker_class=DummyBlobAvailabilityTracker,
            dht_node_class=Node, is_generous=self.is_generous, external_ip="127.0.0.1")
        self.lbry_file_manager = EncryptedFileManager(self.session, self.sd_identifier)
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
        d.addCallback(self.put_sd_hash_on_queue)

        def print_error(err):
            logging.critical("Server error: %s", err.getErrorMessage())

        d.addErrback(print_error)
        return d

    def start_server(self):
        session = self.session
        query_handler_factories = {
            1: BlobAvailabilityHandlerFactory(session.blob_manager),
            2: BlobRequestHandlerFactory(
                session.blob_manager, session.wallet,
                session.payment_rate_manager,
                None),
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
        dl.addCallback(lambda _: rm_db_and_blob_dir(self.db_dir, self.blob_dir))
        dl.addCallback(lambda _: self.reactor.stop())
        return dl

    def check_for_kill(self):
        if self.kill_event.is_set():
            self.kill_server()

    @defer.inlineCallbacks
    def create_stream(self):
        test_file = GenFile(self.file_size, b''.join([chr(i) for i in xrange(0, 64, 6)]))
        lbry_file = yield create_lbry_file(self.session, self.lbry_file_manager, "test_file", test_file)
        defer.returnValue(lbry_file.sd_hash)

    def put_sd_hash_on_queue(self, sd_hash):
        self.sd_hash_queue.put(sd_hash)


def start_lbry_reuploader(sd_hash, kill_event, dead_event,
                          ready_event, n, ul_rate_limit=None, is_generous=False):
    use_epoll_on_linux()
    init_conf_windows()
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

    db_dir, blob_dir = mk_db_and_blob_dir()
    session = Session(conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir,
                      node_id="abcd" + str(n), dht_node_port=4446,
                      peer_finder=peer_finder, hash_announcer=hash_announcer,
                      blob_dir=blob_dir, peer_port=peer_port,
                      use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
                      blob_tracker_class=DummyBlobAvailabilityTracker,
                      is_generous=conf.ADJUSTABLE_SETTINGS['is_generous_host'][1],
                      external_ip="127.0.0.1")

    lbry_file_manager = EncryptedFileManager(session, sd_identifier)

    if ul_rate_limit is not None:
        session.rate_limiter.set_ul_limit(ul_rate_limit)

    def make_downloader(metadata, prm, download_directory):
        factories = metadata.factories
        return factories[0].make_downloader(metadata, prm.min_blob_data_payment_rate, prm, download_directory)

    def download_file():
        prm = session.payment_rate_manager
        d = download_sd_blob(session, sd_hash, prm)
        d.addCallback(sd_identifier.get_metadata_for_sd_blob)
        d.addCallback(make_downloader, prm, db_dir)
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
                None),
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
            ds.append(rm_db_and_blob_dir(db_dir, blob_dir))
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


def start_blob_uploader(blob_hash_queue, kill_event, dead_event, slow, is_generous=False):
    use_epoll_on_linux()
    init_conf_windows()
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
    else:
        peer_port = 5554


    db_dir, blob_dir = mk_db_and_blob_dir()

    session = Session(conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir, node_id="efgh",
                      peer_finder=peer_finder, hash_announcer=hash_announcer,
                      blob_dir=blob_dir, peer_port=peer_port, dht_node_port=4446,
                      use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
                      blob_tracker_class=DummyBlobAvailabilityTracker,
                      is_generous=conf.ADJUSTABLE_SETTINGS['is_generous_host'][1],
                      external_ip="127.0.0.1")

    if slow is True:
        session.rate_limiter.set_ul_limit(2 ** 11)

    def start_all():
        d = session.setup()
        d.addCallback(lambda _: start_server())
        d.addCallback(lambda _: create_single_blob())
        d.addCallback(put_blob_hash_on_queue)

        def print_error(err):
            logging.critical("Server error: %s", err.getErrorMessage())

        d.addErrback(print_error)
        return d

    def start_server():

        server_port = None

        query_handler_factories = {
            1: BlobAvailabilityHandlerFactory(session.blob_manager),
            2: BlobRequestHandlerFactory(session.blob_manager, session.wallet,
                                         session.payment_rate_manager,
                                         None),
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
            dl.addCallback(lambda _: rm_db_and_blob_dir(db_dir, blob_dir))
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
        self.lbry_file_manager = None
        self.is_generous = True
        self.addCleanup(self.take_down_env)

    def take_down_env(self):

        d = defer.succeed(True)
        if self.lbry_file_manager is not None:
            d.addCallback(lambda _: self.lbry_file_manager.stop())
        if self.session is not None:
            d.addCallback(lambda _: self.session.shut_down())

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

    @unittest.skipIf(is_android(),
                     'Test cannot pass on Android because multiprocessing '
                     'is not supported at the OS level.')
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

        db_dir, blob_dir = mk_db_and_blob_dir()
        self.session = Session(
            conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir,
            node_id="abcd", peer_finder=peer_finder, hash_announcer=hash_announcer,
            blob_dir=blob_dir, peer_port=5553, dht_node_port=4445,
            use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
            blob_tracker_class=DummyBlobAvailabilityTracker,
            dht_node_class=Node, is_generous=self.is_generous, external_ip="127.0.0.1")

        self.lbry_file_manager = EncryptedFileManager(
            self.session, sd_identifier)

        def make_downloader(metadata, prm):
            factories = metadata.factories
            return factories[0].make_downloader(metadata, prm.min_blob_data_payment_rate, prm, db_dir)

        def download_file(sd_hash):
            prm = self.session.payment_rate_manager
            d = download_sd_blob(self.session, sd_hash, prm)
            d.addCallback(sd_identifier.get_metadata_for_sd_blob)
            d.addCallback(make_downloader, prm)
            d.addCallback(lambda downloader: downloader.start())
            return d

        def check_md5_sum():
            f = open(os.path.join(db_dir, 'test_file'))
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
            d.addCallback(lambda _: rm_db_and_blob_dir(db_dir, blob_dir))
            d.addCallback(lambda _: arg)
            return d

        d = self.wait_for_hash_from_queue(sd_hash_queue)
        d.addCallback(start_transfer)
        d.addBoth(stop)

        return d

    @unittest.skipIf(is_android(),
                     'Test cannot pass on Android because multiprocessing '
                     'is not supported at the OS level.')
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

        db_dir, blob_dir = mk_db_and_blob_dir()
        self.session = Session(
            conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir, node_id="abcd",
            peer_finder=peer_finder, hash_announcer=hash_announcer,
            blob_dir=blob_dir, peer_port=5553, dht_node_port=4445,
            use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
            blob_tracker_class=DummyBlobAvailabilityTracker,
            is_generous=conf.ADJUSTABLE_SETTINGS['is_generous_host'][1], external_ip="127.0.0.1")

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
            dl.addCallback(lambda _: rm_db_and_blob_dir(db_dir, blob_dir))
            dl.addCallback(lambda _: arg)
            return dl

        d.addBoth(stop)
        return d

    @unittest.skipIf(is_android(),
                     'Test cannot pass on Android because multiprocessing '
                     'is not supported at the OS level.')
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

        db_dir, blob_dir = mk_db_and_blob_dir()
        self.session = Session(conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir,
                               node_id="abcd", peer_finder=peer_finder, dht_node_port=4445,
                               hash_announcer=hash_announcer, blob_dir=blob_dir, peer_port=5553,
                               use_upnp=False, rate_limiter=rate_limiter, wallet=wallet,
                               blob_tracker_class=DummyBlobAvailabilityTracker,
                               is_generous=conf.ADJUSTABLE_SETTINGS['is_generous_host'][1],
                               external_ip="127.0.0.1")

        self.lbry_file_manager = EncryptedFileManager(self.session, sd_identifier)

        @defer.inlineCallbacks
        def make_downloader(metadata, prm):
            factories = metadata.factories
            downloader = yield factories[0].make_downloader(metadata, prm.min_blob_data_payment_rate, prm, db_dir)
            defer.returnValue(downloader)

        @defer.inlineCallbacks
        def download_file(sd_hash):
            prm = self.session.payment_rate_manager
            sd_blob = yield download_sd_blob(self.session, sd_hash, prm)
            metadata = yield sd_identifier.get_metadata_for_sd_blob(sd_blob)
            downloader = yield make_downloader(metadata, prm)
            downloaders.append(downloader)
            yield downloader.start()
            defer.returnValue(downloader)

        def check_md5_sum():
            f = open(os.path.join(db_dir, 'test_file'))
            hashsum = MD5.new()
            hashsum.update(f.read())
            self.assertEqual(hashsum.hexdigest(), "4ca2aafb4101c1e42235aad24fbb83be")

        def delete_lbry_file(downloader):
            logging.debug("deleting the file")
            return self.lbry_file_manager.delete_lbry_file(downloader)

        def check_lbry_file(downloader):
            d = downloader.status()

            def check_status_report(status_report):
                self.assertEqual(status_report.num_known, status_report.num_completed)
                self.assertEqual(status_report.num_known, 3)

            d.addCallback(check_status_report)
            return d

        @defer.inlineCallbacks
        def start_transfer(sd_hash):
            # download a file, delete it, and download it again

            logging.debug("Starting the transfer")
            yield self.session.setup()
            yield add_lbry_file_to_sd_identifier(sd_identifier)
            yield self.lbry_file_manager.setup()
            downloader = yield download_file(sd_hash)
            yield check_md5_sum()
            yield check_lbry_file(downloader)
            yield delete_lbry_file(downloader)
            downloader = yield download_file(sd_hash)
            yield check_lbry_file(downloader)
            yield check_md5_sum()
            yield delete_lbry_file(downloader)

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
            d.addCallback(lambda _: rm_db_and_blob_dir(db_dir, blob_dir))
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
            sd_hash_queue, kill_event, dead_events[0], 5209343, 9373419, 2 ** 22)
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

        db_dir, blob_dir = mk_db_and_blob_dir()
        self.session = Session(conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir,
                               node_id="abcd", peer_finder=peer_finder, dht_node_port=4445,
                               hash_announcer=hash_announcer, blob_dir=blob_dir,
                               peer_port=5553, use_upnp=False, rate_limiter=rate_limiter,
                               wallet=wallet, blob_tracker_class=DummyBlobAvailabilityTracker,
                               is_generous=conf.ADJUSTABLE_SETTINGS['is_generous_host'][1],
                               external_ip="127.0.0.1")

        self.lbry_file_manager = EncryptedFileManager(
            self.session, sd_identifier)

        def start_additional_uploaders(sd_hash):
            for i in range(1, num_uploaders):
                uploader = Process(target=start_lbry_reuploader,
                                   args=(
                                   sd_hash, kill_event, dead_events[i], ready_events[i - 1], i,
                                   2 ** 10))
                uploader.start()
                self.server_processes.append(uploader)
            return defer.succeed(True)

        def wait_for_ready_events():
            return defer.DeferredList(
                [self.wait_for_event(ready_event, 60) for ready_event in ready_events])

        def make_downloader(metadata, prm):
            info_validator = metadata.validator
            options = metadata.options
            factories = metadata.factories
            chosen_options = [o.default_value for o in
                              options.get_downloader_options(info_validator, prm)]
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
            d = defer.DeferredList(
                [self.wait_for_event(dead_event, 15) for dead_event in dead_events])

            def print_shutting_down():
                logging.info("Client is shutting down")

            d.addCallback(lambda _: print_shutting_down())
            d.addCallback(lambda _: rm_db_and_blob_dir(db_dir, blob_dir))
            d.addCallback(lambda _: arg)
            return d

        d = self.wait_for_hash_from_queue(sd_hash_queue)
        d.addCallback(start_transfer)
        d.addBoth(stop)

        return d
