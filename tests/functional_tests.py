import shutil
from multiprocessing import Process, Event, Queue
import logging
import sys
import random
import io
from Crypto.PublicKey import RSA
from Crypto import Random
from Crypto.Hash import MD5
from lbrynet.conf import MIN_BLOB_DATA_PAYMENT_RATE
from lbrynet.conf import MIN_BLOB_INFO_PAYMENT_RATE
from lbrynet.lbrylive.LiveStreamCreator import FileLiveStreamCreator
from lbrynet.lbrylive.PaymentRateManager import BaseLiveStreamPaymentRateManager
from lbrynet.lbrylive.PaymentRateManager import LiveStreamPaymentRateManager
from lbrynet.lbrylive.LiveStreamMetadataManager import DBLiveStreamMetadataManager
from lbrynet.lbrylive.LiveStreamMetadataManager import TempLiveStreamMetadataManager
from lbrynet.lbryfile.LBRYFileMetadataManager import TempLBRYFileMetadataManager, DBLBRYFileMetadataManager
from lbrynet.lbryfilemanager.LBRYFileManager import LBRYFileManager
from lbrynet.core.PaymentRateManager import PaymentRateManager
from lbrynet.core.PTCWallet import PointTraderKeyQueryHandlerFactory, PointTraderKeyExchanger
from lbrynet.core.Session import LBRYSession
from lbrynet.core.client.StandaloneBlobDownloader import StandaloneBlobDownloader
from lbrynet.core.StreamDescriptor import BlobStreamDescriptorWriter
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier
from lbrynet.core.StreamDescriptor import download_sd_blob
from lbrynet.lbryfilemanager.LBRYFileCreator import create_lbry_file
from lbrynet.lbryfile.client.LBRYFileOptions import add_lbry_file_to_sd_identifier
from lbrynet.lbryfile.StreamDescriptor import get_sd_info
from twisted.internet import defer, threads, task
from twisted.trial.unittest import TestCase
from twisted.python.failure import Failure
import os
from lbrynet.core.PeerManager import PeerManager
from lbrynet.core.RateLimiter import DummyRateLimiter, RateLimiter
from lbrynet.core.server.BlobAvailabilityHandler import BlobAvailabilityHandlerFactory
from lbrynet.core.server.BlobRequestHandler import BlobRequestHandlerFactory
from lbrynet.core.server.ServerProtocol import ServerProtocolFactory
from lbrynet.lbrylive.server.LiveBlobInfoQueryHandler import CryptBlobInfoQueryHandlerFactory
from lbrynet.lbrylive.client.LiveStreamOptions import add_live_stream_to_sd_identifier
from lbrynet.lbrylive.client.LiveStreamDownloader import add_full_live_stream_downloader_to_sd_identifier


log_format = "%(funcName)s(): %(message)s"
logging.basicConfig(level=logging.WARNING, format=log_format)


class FakeNode(object):
    def __init__(self, *args, **kwargs):
        pass

    def joinNetwork(self, *args):
        pass

    def stop(self):
        pass


class FakeWallet(object):
    def __init__(self):
        self.private_key = RSA.generate(1024)
        self.encoded_public_key = self.private_key.publickey().exportKey()

    def start(self):
        return defer.succeed(True)

    def stop(self):
        return defer.succeed(True)

    def get_info_exchanger(self):
        return PointTraderKeyExchanger(self)

    def get_wallet_info_query_handler_factory(self):
        return PointTraderKeyQueryHandlerFactory(self)

    def reserve_points(self, *args):
        return True

    def cancel_point_reservation(self, *args):
        pass

    def send_points(self, *args):
        return defer.succeed(True)

    def add_expected_payment(self, *args):
        pass

    def get_balance(self):
        return defer.succeed(1000)

    def set_public_key_for_peer(self, peer, public_key):
        pass


class FakePeerFinder(object):
    def __init__(self, port, peer_manager):
        self.peer_manager = peer_manager

    def find_peers_for_blob(self, *args):
        return defer.succeed([self.peer_manager.get_peer("127.0.0.1", 5553)])

    def run_manage_loop(self):
        pass

    def stop(self):
        pass


class FakeTwoPeerFinder(object):
    def __init__(self, port, peer_manager):
        self.peer_manager = peer_manager
        self.count = 0

    def find_peers_for_blob(self, *args):
        if self.count % 2 == 0:
            peer_port = 5553
        else:
            peer_port = 5554
        self.count += 1
        return defer.succeed([self.peer_manager.get_peer("127.0.0.1", peer_port)])

    def run_manage_loop(self):
        pass

    def stop(self):
        pass


class FakeAnnouncer(object):

    def __init__(self, *args):
        pass

    def add_supplier(self, supplier):
        pass

    def immediate_announce(self, *args):
        pass

    def run_manage_loop(self):
        pass

    def stop(self):
        pass


class GenFile(io.RawIOBase):
    def __init__(self, size, pattern):
        io.RawIOBase.__init__(self)
        self.size = size
        self.pattern = pattern
        self.read_so_far = 0
        self.buff = b''
        self.last_offset = 0

    def readable(self):
        return True

    def writable(self):
        return False

    def read(self, n=-1):
        if n > -1:
            bytes_to_read = min(n, self.size - self.read_so_far)
        else:
            bytes_to_read = self.size - self.read_so_far
        output, self.buff = self.buff[:bytes_to_read], self.buff[bytes_to_read:]
        bytes_to_read -= len(output)
        while bytes_to_read > 0:
            self.buff = self._generate_chunk()
            new_output, self.buff = self.buff[:bytes_to_read], self.buff[bytes_to_read:]
            bytes_to_read -= len(new_output)
            output += new_output
        self.read_so_far += len(output)
        return output

    def readall(self):
        return self.read()

    def _generate_chunk(self, n=2**10):
        output = self.pattern[self.last_offset:self.last_offset + n]
        n_left = n - len(output)
        whole_patterns = n_left / len(self.pattern)
        output += self.pattern * whole_patterns
        self.last_offset = n - len(output)
        output += self.pattern[:self.last_offset]
        return output


test_create_stream_sd_file = {
    'stream_name': '746573745f66696c65',
    'blobs': [
        {'length': 2097152, 'blob_num': 0,
         'blob_hash':
            'dc4708f76a5e7af0f1cae0ee96b824e2ed9250c9346c093b441f0a20d3607c17948b6fcfb4bc62020fe5286693d08586',
         'iv': '30303030303030303030303030303031'},
        {'length': 2097152, 'blob_num': 1,
         'blob_hash':
            'f4067522c1b49432a2a679512e3917144317caa1abba0c041e0cd2cf9f635d4cf127ce1824fa04189b63916174951f70',
         'iv': '30303030303030303030303030303032'},
        {'length': 1015056, 'blob_num': 2,
         'blob_hash':
            '305486c434260484fcb2968ce0e963b72f81ba56c11b08b1af0789b55b44d78422600f9a38e3cf4f2e9569897e5646a9',
         'iv': '30303030303030303030303030303033'},
        {'length': 0, 'blob_num': 3, 'iv': '30303030303030303030303030303034'}],
    'stream_type': 'lbryfile',
    'key': '30313233343536373031323334353637',
    'suggested_file_name': '746573745f66696c65',
    'stream_hash': '6d27fbe10c86d81aacfb897c7a426d0a2214f5a299455a6d315c0f998c4b3545c2dc60906122d94653c23b1898229e3f'}


def start_lbry_uploader(sd_hash_queue, kill_event, dead_event):

    sys.modules = sys.modules.copy()

    del sys.modules['twisted.internet.reactor']

    import twisted.internet

    twisted.internet.reactor = twisted.internet.epollreactor.EPollReactor()

    sys.modules['twisted.internet.reactor'] = twisted.internet.reactor

    from twisted.internet import reactor

    logging.debug("Starting the uploader")

    Random.atfork()

    r = random.Random()
    r.seed("start_lbry_uploader")

    wallet = FakeWallet()
    peer_manager = PeerManager()
    peer_finder = FakePeerFinder(5553, peer_manager)
    hash_announcer = FakeAnnouncer()
    rate_limiter = DummyRateLimiter()
    sd_identifier = StreamDescriptorIdentifier()

    db_dir = "server"
    os.mkdir(db_dir)

    session = LBRYSession(MIN_BLOB_DATA_PAYMENT_RATE, db_dir=db_dir, lbryid="abcd",
                          peer_finder=peer_finder, hash_announcer=hash_announcer, peer_port=5553,
                          use_upnp=False, rate_limiter=rate_limiter, wallet=wallet)

    stream_info_manager = TempLBRYFileMetadataManager()

    lbry_file_manager = LBRYFileManager(session, stream_info_manager, sd_identifier)

    def start_all():

        d = session.setup()
        d.addCallback(lambda _: add_lbry_file_to_sd_identifier(sd_identifier))
        d.addCallback(lambda _: lbry_file_manager.setup())
        d.addCallback(lambda _: start_server())
        d.addCallback(lambda _: create_stream())
        d.addCallback(create_stream_descriptor)
        d.addCallback(put_sd_hash_on_queue)

        def print_error(err):
            logging.critical("Server error: %s", err.getErrorMessage())

        d.addErrback(print_error)
        return d

    def start_server():

        server_port = None

        query_handler_factories = {
            BlobAvailabilityHandlerFactory(session.blob_manager): True,
            BlobRequestHandlerFactory(session.blob_manager, session.wallet,
                                      PaymentRateManager(session.base_payment_rate_manager)): True,
            session.wallet.get_wallet_info_query_handler_factory(): True,
        }

        server_factory = ServerProtocolFactory(session.rate_limiter,
                                               query_handler_factories,
                                               session.peer_manager)

        server_port = reactor.listenTCP(5553, server_factory)
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
        return True

    def create_stream():
        test_file = GenFile(5209343, b''.join([chr(i) for i in xrange(0, 64, 6)]))
        d = create_lbry_file(session, lbry_file_manager, "test_file", test_file)
        return d

    def create_stream_descriptor(stream_hash):
        descriptor_writer = BlobStreamDescriptorWriter(session.blob_manager)
        d = get_sd_info(lbry_file_manager.stream_info_manager, stream_hash, True)
        d.addCallback(descriptor_writer.create_descriptor)
        return d

    def put_sd_hash_on_queue(sd_hash):
        sd_hash_queue.put(sd_hash)

    reactor.callLater(1, start_all)
    reactor.run()


def start_live_server(sd_hash_queue, kill_event, dead_event):

    sys.modules = sys.modules.copy()

    del sys.modules['twisted.internet.reactor']

    import twisted.internet

    twisted.internet.reactor = twisted.internet.epollreactor.EPollReactor()

    sys.modules['twisted.internet.reactor'] = twisted.internet.reactor

    from twisted.internet import reactor

    logging.debug("In start_server.")

    Random.atfork()

    r = random.Random()
    r.seed("start_live_server")

    wallet = FakeWallet()
    peer_manager = PeerManager()
    peer_finder = FakePeerFinder(5553, peer_manager)
    hash_announcer = FakeAnnouncer()
    rate_limiter = DummyRateLimiter()
    sd_identifier = StreamDescriptorIdentifier()

    db_dir = "server"
    os.mkdir(db_dir)

    session = LBRYSession(MIN_BLOB_DATA_PAYMENT_RATE, db_dir=db_dir, lbryid="abcd",
                          peer_finder=peer_finder, hash_announcer=hash_announcer, peer_port=5553,
                          use_upnp=False, rate_limiter=rate_limiter, wallet=wallet)

    base_payment_rate_manager = BaseLiveStreamPaymentRateManager(MIN_BLOB_INFO_PAYMENT_RATE)
    data_payment_rate_manager = PaymentRateManager(session.base_payment_rate_manager)
    payment_rate_manager = LiveStreamPaymentRateManager(base_payment_rate_manager,
                                                        data_payment_rate_manager)

    stream_info_manager = DBLiveStreamMetadataManager(session.db_dir, hash_announcer)

    logging.debug("Created the session")

    server_port = []

    def start_listening():
        logging.debug("Starting the server protocol")
        query_handler_factories = {
            CryptBlobInfoQueryHandlerFactory(stream_info_manager, session.wallet,
                                             payment_rate_manager): True,
            BlobAvailabilityHandlerFactory(session.blob_manager): True,
            BlobRequestHandlerFactory(session.blob_manager, session.wallet,
                                      payment_rate_manager): True,
            session.wallet.get_wallet_info_query_handler_factory(): True,
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
        base_live_stream_payment_rate_manager = BaseLiveStreamPaymentRateManager(
            MIN_BLOB_INFO_PAYMENT_RATE
        )
        add_live_stream_to_sd_identifier(sd_identifier, base_live_stream_payment_rate_manager)
        add_full_live_stream_downloader_to_sd_identifier(session, stream_info_manager, sd_identifier,
                                                         base_live_stream_payment_rate_manager)

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
    reactor.run()


def start_blob_uploader(blob_hash_queue, kill_event, dead_event, slow):

    sys.modules = sys.modules.copy()

    del sys.modules['twisted.internet.reactor']

    import twisted.internet

    twisted.internet.reactor = twisted.internet.epollreactor.EPollReactor()

    sys.modules['twisted.internet.reactor'] = twisted.internet.reactor

    from twisted.internet import reactor

    logging.debug("Starting the uploader")

    Random.atfork()

    wallet = FakeWallet()
    peer_manager = PeerManager()
    peer_finder = FakePeerFinder(5554, peer_manager)
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

    session = LBRYSession(MIN_BLOB_DATA_PAYMENT_RATE, db_dir=db_dir, lbryid="efgh",
                          peer_finder=peer_finder, hash_announcer=hash_announcer,
                          blob_dir=blob_dir, peer_port=peer_port,
                          use_upnp=False, rate_limiter=rate_limiter, wallet=wallet)

    if slow is True:
        session.rate_limiter.set_ul_limit(2**11)

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
            BlobAvailabilityHandlerFactory(session.blob_manager): True,
            BlobRequestHandlerFactory(session.blob_manager, session.wallet,
                                      PaymentRateManager(session.base_payment_rate_manager)): True,
            session.wallet.get_wallet_info_query_handler_factory(): True,
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
        blob_creator.write("0" * 2**21)
        return blob_creator.close()

    def put_blob_hash_on_queue(blob_hash):
        logging.debug("Telling the client to start running. Blob hash: %s", str(blob_hash))
        blob_hash_queue.put(blob_hash)
        logging.debug("blob hash has been added to the queue")

    reactor.callLater(1, start_all)
    reactor.run()


class TestTransfer(TestCase):
    def setUp(self):
        self.server_processes = []
        self.session = None
        self.stream_info_manager = None
        self.lbry_file_manager = None
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
    def wait_for_dead_event(dead_event):

        from twisted.internet import reactor
        d = defer.Deferred()

        def stop():
            dead_check.stop()
            if stop_call.active():
                stop_call.cancel()
                d.callback(True)

        def check_if_dead_event_set():
            if dead_event.is_set():
                logging.debug("Dead event has been found set")
                stop()

        def done_waiting():
            logging.warning("Dead event has not been found set and timeout has expired")
            stop()

        dead_check = task.LoopingCall(check_if_dead_event_set)
        dead_check.start(.1)
        stop_call = reactor.callLater(15, done_waiting)
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
        uploader = Process(target=start_lbry_uploader, args=(sd_hash_queue, kill_event, dead_event))
        uploader.start()
        self.server_processes.append(uploader)

        logging.debug("Testing transfer")

        wallet = FakeWallet()
        peer_manager = PeerManager()
        peer_finder = FakePeerFinder(5553, peer_manager)
        hash_announcer = FakeAnnouncer()
        rate_limiter = DummyRateLimiter()
        sd_identifier = StreamDescriptorIdentifier()

        db_dir = "client"
        blob_dir = os.path.join(db_dir, "blobfiles")
        os.mkdir(db_dir)
        os.mkdir(blob_dir)

        self.session = LBRYSession(MIN_BLOB_DATA_PAYMENT_RATE, db_dir=db_dir, lbryid="abcd",
                                   peer_finder=peer_finder, hash_announcer=hash_announcer,
                                   blob_dir=blob_dir, peer_port=5553,
                                   use_upnp=False, rate_limiter=rate_limiter, wallet=wallet)

        self.stream_info_manager = TempLBRYFileMetadataManager()

        self.lbry_file_manager = LBRYFileManager(self.session, self.stream_info_manager, sd_identifier)

        def make_downloader(metadata, prm):
            info_validator = metadata.validator
            options = metadata.options
            factories = metadata.factories
            chosen_options = [o.default_value for o in options.get_downloader_options(info_validator, prm)]
            return factories[0].make_downloader(metadata, chosen_options, prm)

        def download_file(sd_hash):
            prm = PaymentRateManager(self.session.base_payment_rate_manager)
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

        def start_transfer(sd_hash):

            logging.debug("Starting the transfer")

            d = self.session.setup()
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
            d = self.wait_for_dead_event(dead_event)

            def print_shutting_down():
                logging.info("Client is shutting down")

            d.addCallback(lambda _: print_shutting_down())
            d.addCallback(lambda _: arg)
            return d

        d = self.wait_for_hash_from_queue(sd_hash_queue)
        d.addCallback(start_transfer)
        d.addBoth(stop)

        return d

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
        peer_finder = FakePeerFinder(5553, peer_manager)
        hash_announcer = FakeAnnouncer()
        rate_limiter = DummyRateLimiter()
        sd_identifier = StreamDescriptorIdentifier()

        db_dir = "client"
        os.mkdir(db_dir)

        self.session = LBRYSession(MIN_BLOB_DATA_PAYMENT_RATE, db_dir=db_dir, lbryid="abcd",
                                   peer_finder=peer_finder, hash_announcer=hash_announcer, blob_dir=None,
                                   peer_port=5553, use_upnp=False, rate_limiter=rate_limiter, wallet=wallet)

        self.stream_info_manager = TempLiveStreamMetadataManager(hash_announcer)

        d = self.wait_for_hash_from_queue(sd_hash_queue)

        def create_downloader(metadata, prm):
            info_validator = metadata.validator
            options = metadata.options
            factories = metadata.factories
            chosen_options = [o.default_value for o in options.get_downloader_options(info_validator, prm)]
            return factories[0].make_downloader(metadata, chosen_options, prm)

        def start_lbry_file(lbry_file):
            lbry_file = lbry_file
            logging.debug("Calling lbry_file.start()")
            return lbry_file.start()

        def download_stream(sd_blob_hash):
            logging.debug("Downloaded the sd blob. Reading it now")
            prm = PaymentRateManager(self.session.base_payment_rate_manager)
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
            base_live_stream_payment_rate_manager = BaseLiveStreamPaymentRateManager(
                MIN_BLOB_INFO_PAYMENT_RATE
            )
            add_live_stream_to_sd_identifier(sd_identifier,
                                             base_live_stream_payment_rate_manager)
            add_full_live_stream_downloader_to_sd_identifier(self.session, self.stream_info_manager,
                                                             sd_identifier,
                                                             base_live_stream_payment_rate_manager)

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
            d = self.wait_for_dead_event(dead_event)

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
        peer_finder = FakeTwoPeerFinder(5553, peer_manager)
        hash_announcer = FakeAnnouncer()
        rate_limiter = DummyRateLimiter()

        db_dir = "client"
        blob_dir = os.path.join(db_dir, "blobfiles")
        os.mkdir(db_dir)
        os.mkdir(blob_dir)

        self.session = LBRYSession(MIN_BLOB_DATA_PAYMENT_RATE, db_dir=db_dir, lbryid="abcd",
                                   peer_finder=peer_finder, hash_announcer=hash_announcer,
                                   blob_dir=blob_dir, peer_port=5553,
                                   use_upnp=False, rate_limiter=rate_limiter, wallet=wallet)

        d1 = self.wait_for_hash_from_queue(blob_hash_queue_1)
        d2 = self.wait_for_hash_from_queue(blob_hash_queue_2)
        d = defer.DeferredList([d1, d2], fireOnOneErrback=True)

        def get_blob_hash(results):
            self.assertEqual(results[0][1], results[1][1])
            return results[0][1]

        d.addCallback(get_blob_hash)

        def download_blob(blob_hash):
            prm = PaymentRateManager(self.session.base_payment_rate_manager)
            downloader = StandaloneBlobDownloader(blob_hash, self.session.blob_manager, peer_finder,
                                                  rate_limiter, prm, wallet)
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
            d1 = self.wait_for_dead_event(dead_event_1)
            d2 = self.wait_for_dead_event(dead_event_2)
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
        uploader = Process(target=start_lbry_uploader, args=(sd_hash_queue, kill_event, dead_event))
        uploader.start()
        self.server_processes.append(uploader)

        logging.debug("Testing double download")

        wallet = FakeWallet()
        peer_manager = PeerManager()
        peer_finder = FakePeerFinder(5553, peer_manager)
        hash_announcer = FakeAnnouncer()
        rate_limiter = DummyRateLimiter()
        sd_identifier = StreamDescriptorIdentifier()

        downloaders = []

        db_dir = "client"
        blob_dir = os.path.join(db_dir, "blobfiles")
        os.mkdir(db_dir)
        os.mkdir(blob_dir)

        self.session = LBRYSession(MIN_BLOB_DATA_PAYMENT_RATE, db_dir=db_dir, lbryid="abcd",
                                   peer_finder=peer_finder, hash_announcer=hash_announcer,
                                   blob_dir=blob_dir, peer_port=5553, use_upnp=False,
                                   rate_limiter=rate_limiter, wallet=wallet)

        self.stream_info_manager = DBLBRYFileMetadataManager(self.session.db_dir)

        self.lbry_file_manager = LBRYFileManager(self.session, self.stream_info_manager, sd_identifier)

        def make_downloader(metadata, prm):
            info_validator = metadata.validator
            options = metadata.options
            factories = metadata.factories
            chosen_options = [o.default_value for o in options.get_downloader_options(info_validator, prm)]
            return factories[0].make_downloader(metadata, chosen_options, prm)

        def append_downloader(downloader):
            downloaders.append(downloader)
            return downloader

        def download_file(sd_hash):
            prm = PaymentRateManager(self.session.base_payment_rate_manager)
            d = download_sd_blob(self.session, sd_hash, prm)
            d.addCallback(sd_identifier.get_metadata_for_sd_blob)
            d.addCallback(make_downloader, prm)
            d.addCallback(append_downloader)
            d.addCallback(lambda downloader: downloader.start())
            return d

        def check_md5_sum():
            f = open('test_file')
            hashsum = MD5.new()
            hashsum.update(f.read())
            self.assertEqual(hashsum.hexdigest(), "4ca2aafb4101c1e42235aad24fbb83be")

        def delete_lbry_file():
            logging.debug("deleting the file...")
            d = self.lbry_file_manager.delete_lbry_file(downloaders[0])
            d.addCallback(lambda _: self.lbry_file_manager.get_count_for_stream_hash(downloaders[0].stream_hash))
            d.addCallback(lambda c: self.stream_info_manager.delete_stream(downloaders[1].stream_hash) if c == 0 else True)
            return d

        def check_lbry_file():
            d = downloaders[1].status()
            d.addCallback(lambda _: downloaders[1].status())

            def check_status_report(status_report):
                self.assertEqual(status_report.num_known, status_report.num_completed)
                self.assertEqual(status_report.num_known, 3)

            d.addCallback(check_status_report)
            return d

        def start_transfer(sd_hash):

            logging.debug("Starting the transfer")

            d = self.session.setup()
            d.addCallback(lambda _: self.stream_info_manager.setup())
            d.addCallback(lambda _: add_lbry_file_to_sd_identifier(sd_identifier))
            d.addCallback(lambda _: self.lbry_file_manager.setup())
            d.addCallback(lambda _: download_file(sd_hash))
            d.addCallback(lambda _: check_md5_sum())
            d.addCallback(lambda _: download_file(sd_hash))
            d.addCallback(lambda _: delete_lbry_file())
            d.addCallback(lambda _: check_lbry_file())

            return d

        def stop(arg):
            if isinstance(arg, Failure):
                logging.debug("Client is stopping due to an error. Error: %s", arg.getTraceback())
            else:
                logging.debug("Client is stopping normally.")
            kill_event.set()
            logging.debug("Set the kill event")
            d = self.wait_for_dead_event(dead_event)

            def print_shutting_down():
                logging.info("Client is shutting down")

            d.addCallback(lambda _: print_shutting_down())
            d.addCallback(lambda _: arg)
            return d

        d = self.wait_for_hash_from_queue(sd_hash_queue)
        d.addCallback(start_transfer)
        d.addBoth(stop)
        return d


class TestStreamify(TestCase):

    def setUp(self):
        self.session = None
        self.stream_info_manager = None
        self.lbry_file_manager = None
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
            shutil.rmtree('client')
            if os.path.exists("test_file"):
                os.remove("test_file")

        d.addCallback(lambda _: threads.deferToThread(delete_test_env))
        return d

    def test_create_stream(self):

        wallet = FakeWallet()
        peer_manager = PeerManager()
        peer_finder = FakeTwoPeerFinder(5553, peer_manager)
        hash_announcer = FakeAnnouncer()
        rate_limiter = DummyRateLimiter()
        sd_identifier = StreamDescriptorIdentifier()

        db_dir = "client"
        blob_dir = os.path.join(db_dir, "blobfiles")
        os.mkdir(db_dir)
        os.mkdir(blob_dir)

        self.session = LBRYSession(MIN_BLOB_DATA_PAYMENT_RATE, db_dir=db_dir, lbryid="abcd",
                                   peer_finder=peer_finder, hash_announcer=hash_announcer,
                                   blob_dir=blob_dir, peer_port=5553,
                                   use_upnp=False, rate_limiter=rate_limiter, wallet=wallet)

        self.stream_info_manager = TempLBRYFileMetadataManager()

        self.lbry_file_manager = LBRYFileManager(self.session, self.stream_info_manager, sd_identifier)

        d = self.session.setup()
        d.addCallback(lambda _: self.stream_info_manager.setup())
        d.addCallback(lambda _: add_lbry_file_to_sd_identifier(sd_identifier))
        d.addCallback(lambda _: self.lbry_file_manager.setup())

        def verify_equal(sd_info):
            self.assertEqual(sd_info, test_create_stream_sd_file)

        def verify_stream_descriptor_file(stream_hash):
            d = get_sd_info(self.lbry_file_manager.stream_info_manager, stream_hash, True)
            d.addCallback(verify_equal)
            return d

        def iv_generator():
            iv = 0
            while 1:
                iv += 1
                yield "%016d" % iv

        def create_stream():
            test_file = GenFile(5209343, b''.join([chr(i + 3) for i in xrange(0, 64, 6)]))
            d = create_lbry_file(self.session, self.lbry_file_manager, "test_file", test_file,
                                 key="0123456701234567", iv_generator=iv_generator())
            return d

        d.addCallback(lambda _: create_stream())
        d.addCallback(verify_stream_descriptor_file)
        return d

    def test_create_and_combine_stream(self):

        wallet = FakeWallet()
        peer_manager = PeerManager()
        peer_finder = FakeTwoPeerFinder(5553, peer_manager)
        hash_announcer = FakeAnnouncer()
        rate_limiter = DummyRateLimiter()
        sd_identifier = StreamDescriptorIdentifier()

        db_dir = "client"
        blob_dir = os.path.join(db_dir, "blobfiles")
        os.mkdir(db_dir)
        os.mkdir(blob_dir)

        self.session = LBRYSession(MIN_BLOB_DATA_PAYMENT_RATE, db_dir=db_dir, lbryid="abcd",
                                   peer_finder=peer_finder, hash_announcer=hash_announcer,
                                   blob_dir=blob_dir, peer_port=5553,
                                   use_upnp=False, rate_limiter=rate_limiter, wallet=wallet)

        self.stream_info_manager = DBLBRYFileMetadataManager(self.session.db_dir)

        self.lbry_file_manager = LBRYFileManager(self.session, self.stream_info_manager, sd_identifier)

        def start_lbry_file(lbry_file):
            logging.debug("Calling lbry_file.start()")
            d = lbry_file.start()
            return d

        def combine_stream(stream_hash):

            prm = PaymentRateManager(self.session.base_payment_rate_manager)
            d = self.lbry_file_manager.add_lbry_file(stream_hash, prm)
            d.addCallback(start_lbry_file)

            def check_md5_sum():
                f = open('test_file')
                hashsum = MD5.new()
                hashsum.update(f.read())
                self.assertEqual(hashsum.hexdigest(), "68959747edc73df45e45db6379dd7b3b")

            d.addCallback(lambda _: check_md5_sum())
            return d

        def create_stream():
            test_file = GenFile(53209343, b''.join([chr(i + 5) for i in xrange(0, 64, 6)]))
            return create_lbry_file(self.session, self.lbry_file_manager, "test_file", test_file,
                                    suggested_file_name="test_file")

        d = self.session.setup()
        d.addCallback(lambda _: self.stream_info_manager.setup())
        d.addCallback(lambda _: add_lbry_file_to_sd_identifier(sd_identifier))
        d.addCallback(lambda _: self.lbry_file_manager.setup())
        d.addCallback(lambda _: create_stream())
        d.addCallback(combine_stream)
        return d