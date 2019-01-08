import os
from unittest import skip
from hashlib import md5
from twisted.internet import defer, reactor
from twisted.trial import unittest
from lbrynet import conf
from lbrynet.staging.old_blob_server.BlobAvailabilityHandler import BlobAvailabilityHandlerFactory
from lbrynet.stream.descriptor import StreamDescriptorIdentifier
from lbrynet.stream.descriptor import download_sd_blob
from lbrynet.blob_exchange.price_negotiation import OnlyFreePaymentsManager
from lbrynet.blob.blob_manager import BlobFileManager
from lbrynet.peer import PeerManager
from lbrynet.staging.rate_limiter import RateLimiter
from lbrynet.staging.old_blob_server.BlobRequestHandler import BlobRequestHandlerFactory
from lbrynet.staging.old_blob_server.ServerProtocol import ServerProtocolFactory
from lbrynet.storage import SQLiteStorage
from lbrynet.staging.EncryptedFileCreator import create_lbry_file
from lbrynet.staging.EncryptedFileManager import EncryptedFileManager
from lbrynet.staging.old_stream_client import add_lbry_file_to_sd_identifier

from tests import mocks
from tests.test_utils import mk_db_and_blob_dir, rm_db_and_blob_dir

FakeNode = mocks.Node
FakeWallet = mocks.Wallet
FakePeerFinder = mocks.PeerFinder
FakeAnnouncer = mocks.Announcer
GenFile = mocks.GenFile
test_create_stream_sd_file = mocks.create_stream_sd_file


def init_conf_windows(settings={}):
    """
    There is no fork on windows, so imports
    are freshly initialized in new processes.
    So conf needs to be initialized for new processes
    """
    if os.name == 'nt':
        original_settings = conf.settings
        conf.settings = conf.Config(conf.FIXED_SETTINGS, conf.ADJUSTABLE_SETTINGS)
        conf.settings.installation_id = conf.settings.get_installation_id()
        conf.settings.update(settings)


class LbryUploader:
    def __init__(self, file_size, ul_rate_limit=None):
        self.file_size = file_size
        self.ul_rate_limit = ul_rate_limit
        self.kill_check = None
        # these attributes get defined in `start`
        self.db_dir = None
        self.blob_dir = None
        self.wallet = None
        self.peer_manager = None
        self.rate_limiter = None
        self.prm = None
        self.storage = None
        self.blob_manager = None
        self.lbry_file_manager = None
        self.server_port = None

    @defer.inlineCallbacks
    def setup(self):
        init_conf_windows()

        self.db_dir, self.blob_dir = mk_db_and_blob_dir()
        self.wallet = FakeWallet()
        self.peer_manager = PeerManager()
        self.rate_limiter = RateLimiter()
        if self.ul_rate_limit is not None:
            self.rate_limiter.set_ul_limit(self.ul_rate_limit)
        self.prm = OnlyFreePaymentsManager()
        self.storage = SQLiteStorage(':memory:')
        self.blob_manager = BlobFileManager(self.blob_dir, self.storage)
        self.lbry_file_manager = EncryptedFileManager(FakePeerFinder(5553, self.peer_manager, 1), self.rate_limiter,
                                                      self.blob_manager, self.wallet, self.prm, self.storage,
                                                      StreamDescriptorIdentifier())

        yield f2d(self.storage.open())
        yield f2d(self.blob_manager.setup())
        yield f2d(self.lbry_file_manager.setup())

        query_handler_factories = {
            1: BlobAvailabilityHandlerFactory(self.blob_manager),
            2: BlobRequestHandlerFactory(
                self.blob_manager, self.wallet,
                self.prm,
                None),
            3: self.wallet.get_wallet_info_query_handler_factory(),
        }
        server_factory = ServerProtocolFactory(self.rate_limiter,
                                               query_handler_factories,
                                               self.peer_manager)
        self.server_port = reactor.listenTCP(5553, server_factory, interface="localhost")
        test_file = GenFile(self.file_size, bytes(i for i in range(0, 64, 6)))
        lbry_file = yield create_lbry_file(self.blob_manager, self.storage, self.prm, self.lbry_file_manager,
                                           "test_file", test_file)
        defer.returnValue(lbry_file.sd_hash)

    @defer.inlineCallbacks
    def stop(self):
        lbry_files = self.lbry_file_manager.lbry_files
        for lbry_file in lbry_files:
            yield self.lbry_file_manager.delete_lbry_file(lbry_file)
        yield self.lbry_file_manager.stop()
        yield f2d(self.blob_manager.stop())
        yield f2d(self.storage.close())
        self.server_port.stopListening()
        rm_db_and_blob_dir(self.db_dir, self.blob_dir)
        if os.path.exists("test_file"):
            os.remove("test_file")


@skip
class TestTransfer(unittest.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        mocks.mock_conf_settings(self)
        self.db_dir, self.blob_dir = mk_db_and_blob_dir()
        self.wallet = FakeWallet()
        self.peer_manager = PeerManager()
        self.peer_finder = FakePeerFinder(5553, self.peer_manager, 1)
        self.rate_limiter = RateLimiter()
        self.prm = OnlyFreePaymentsManager()
        self.storage = SQLiteStorage(':memory:')
        self.blob_manager = BlobFileManager(self.blob_dir, self.storage)
        self.sd_identifier = StreamDescriptorIdentifier()
        self.lbry_file_manager = EncryptedFileManager(self.peer_finder, self.rate_limiter,
                                                      self.blob_manager, self.wallet, self.prm, self.storage,
                                                      self.sd_identifier)

        self.uploader = LbryUploader(5209343)
        self.sd_hash = yield self.uploader.setup()
        yield f2d(self.storage.open())
        yield f2d(self.blob_manager.setup())
        yield f2d(self.lbry_file_manager.setup())
        yield add_lbry_file_to_sd_identifier(self.sd_identifier)

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.uploader.stop()
        lbry_files = self.lbry_file_manager.lbry_files
        for lbry_file in lbry_files:
            yield self.lbry_file_manager.delete_lbry_file(lbry_file)
        yield self.lbry_file_manager.stop()
        yield self.blob_manager.stop()
        yield f2d(self.storage.close())
        rm_db_and_blob_dir(self.db_dir, self.blob_dir)
        if os.path.exists("test_file"):
            os.remove("test_file")

    @defer.inlineCallbacks
    def test_lbry_transfer(self):
        sd_blob = yield download_sd_blob(
            self.sd_hash, self.blob_manager, self.peer_finder, self.rate_limiter, self.prm, self.wallet
        )
        metadata = yield self.sd_identifier.get_metadata_for_sd_blob(sd_blob)
        downloader = yield metadata.factories[0].make_downloader(
            metadata, self.prm.min_blob_data_payment_rate, self.prm, self.db_dir, download_mirrors=None
        )
        yield downloader.start()
        with open(os.path.join(self.db_dir, 'test_file'), 'rb') as f:
            hashsum = md5()
            hashsum.update(f.read())
        self.assertEqual(hashsum.hexdigest(), "4ca2aafb4101c1e42235aad24fbb83be")

    # TODO: update these
    # def test_last_blob_retrieval(self):
    #     kill_event = Event()
    #     dead_event_1 = Event()
    #     blob_hash_queue_1 = Queue()
    #     blob_hash_queue_2 = Queue()
    #     fast_uploader = Process(target=start_blob_uploader,
    #                             args=(blob_hash_queue_1, kill_event, dead_event_1, False))
    #     fast_uploader.start()
    #     self.server_processes.append(fast_uploader)
    #     dead_event_2 = Event()
    #     slow_uploader = Process(target=start_blob_uploader,
    #                             args=(blob_hash_queue_2, kill_event, dead_event_2, True))
    #     slow_uploader.start()
    #     self.server_processes.append(slow_uploader)
    #
    #     logging.debug("Testing transfer")
    #
    #     wallet = FakeWallet()
    #     peer_manager = PeerManager()
    #     peer_finder = FakePeerFinder(5553, peer_manager, 2)
    #     hash_announcer = FakeAnnouncer()
    #     rate_limiter = DummyRateLimiter()
    #     dht_node = FakeNode(peer_finder=peer_finder, peer_manager=peer_manager, udpPort=4445, peerPort=5553,
    #                         node_id="abcd", externalIP="127.0.0.1")
    #
    #     db_dir, blob_dir = mk_db_and_blob_dir()
    #     self.session = Session(
    #         conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir, node_id="abcd",
    #         peer_finder=peer_finder, hash_announcer=hash_announcer,
    #         blob_dir=blob_dir, peer_port=5553, dht_node_port=4445,
    #         rate_limiter=rate_limiter, wallet=wallet,
    #         dht_node=dht_node, external_ip="127.0.0.1")
    #
    #     d1 = self.wait_for_hash_from_queue(blob_hash_queue_1)
    #     d2 = self.wait_for_hash_from_queue(blob_hash_queue_2)
    #     d = defer.DeferredList([d1, d2], fireOnOneErrback=True)
    #
    #     def get_blob_hash(results):
    #         self.assertEqual(results[0][1], results[1][1])
    #         return results[0][1]
    #
    #     d.addCallback(get_blob_hash)
    #
    #     def download_blob(blob_hash):
    #         prm = self.session.payment_rate_manager
    #         downloader = StandaloneBlobDownloader(
    #             blob_hash, self.session.blob_manager, peer_finder, rate_limiter, prm, wallet)
    #         d = downloader.download()
    #         return d
    #
    #     def start_transfer(blob_hash):
    #
    #         logging.debug("Starting the transfer")
    #
    #         d = self.session.setup()
    #         d.addCallback(lambda _: download_blob(blob_hash))
    #
    #         return d
    #
    #     d.addCallback(start_transfer)
    #
    #     def stop(arg):
    #         if isinstance(arg, Failure):
    #             logging.debug("Client is stopping due to an error. Error: %s", arg.getTraceback())
    #         else:
    #             logging.debug("Client is stopping normally.")
    #         kill_event.set()
    #         logging.debug("Set the kill event")
    #         d1 = self.wait_for_event(dead_event_1, 15)
    #         d2 = self.wait_for_event(dead_event_2, 15)
    #         dl = defer.DeferredList([d1, d2])
    #
    #         def print_shutting_down():
    #             logging.info("Client is shutting down")
    #
    #         dl.addCallback(lambda _: print_shutting_down())
    #         dl.addCallback(lambda _: rm_db_and_blob_dir(db_dir, blob_dir))
    #         dl.addCallback(lambda _: arg)
    #         return dl
    #
    #     d.addBoth(stop)
    #     return d
    #
    # def test_double_download(self):
    #     sd_hash_queue = Queue()
    #     kill_event = Event()
    #     dead_event = Event()
    #     lbry_uploader = LbryUploader(sd_hash_queue, kill_event, dead_event, 5209343)
    #     uploader = Process(target=lbry_uploader.start)
    #     uploader.start()
    #     self.server_processes.append(uploader)
    #
    #     logging.debug("Testing double download")
    #
    #     wallet = FakeWallet()
    #     peer_manager = PeerManager()
    #     peer_finder = FakePeerFinder(5553, peer_manager, 1)
    #     hash_announcer = FakeAnnouncer()
    #     rate_limiter = DummyRateLimiter()
    #     sd_identifier = StreamDescriptorIdentifier()
    #     dht_node = FakeNode(peer_finder=peer_finder, peer_manager=peer_manager, udpPort=4445, peerPort=5553,
    #                         node_id="abcd", externalIP="127.0.0.1")
    #
    #     downloaders = []
    #
    #     db_dir, blob_dir = mk_db_and_blob_dir()
    #     self.session = Session(conf.ADJUSTABLE_SETTINGS['data_rate'][1], db_dir=db_dir,
    #                            node_id="abcd", peer_finder=peer_finder, dht_node_port=4445,
    #                            hash_announcer=hash_announcer, blob_dir=blob_dir, peer_port=5553,
    #                            rate_limiter=rate_limiter, wallet=wallet,
    #                            external_ip="127.0.0.1", dht_node=dht_node)
    #
    #     self.lbry_file_manager = EncryptedFileManager(self.session, sd_identifier)
    #
    #     @defer.inlineCallbacks
    #     def make_downloader(metadata, prm):
    #         factories = metadata.factories
    #         downloader = yield factories[0].make_downloader(metadata, prm.min_blob_data_payment_rate, prm, db_dir)
    #         defer.returnValue(downloader)
    #
    #     @defer.inlineCallbacks
    #     def download_file(sd_hash):
    #         prm = self.session.payment_rate_manager
    #         sd_blob = yield download_sd_blob(self.session, sd_hash, prm)
    #         metadata = yield sd_identifier.get_metadata_for_sd_blob(sd_blob)
    #         downloader = yield make_downloader(metadata, prm)
    #         downloaders.append(downloader)
    #         yield downloader.start()
    #         defer.returnValue(downloader)
    #
    #     def check_md5_sum():
    #         f = open(os.path.join(db_dir, 'test_file'))
    #         hashsum = md5()
    #         hashsum.update(f.read())
    #         self.assertEqual(hashsum.hexdigest(), "4ca2aafb4101c1e42235aad24fbb83be")
    #
    #     def delete_lbry_file(downloader):
    #         logging.debug("deleting the file")
    #         return self.lbry_file_manager.delete_lbry_file(downloader)
    #
    #     def check_lbry_file(downloader):
    #         d = downloader.status()
    #
    #         def check_status_report(status_report):
    #             self.assertEqual(status_report.num_known, status_report.num_completed)
    #             self.assertEqual(status_report.num_known, 3)
    #
    #         d.addCallback(check_status_report)
    #         return d
    #
    #     @defer.inlineCallbacks
    #     def start_transfer(sd_hash):
    #         # download a file, delete it, and download it again
    #
    #         logging.debug("Starting the transfer")
    #         yield self.session.setup()
    #         yield add_lbry_file_to_sd_identifier(sd_identifier)
    #         yield self.lbry_file_manager.setup()
    #         downloader = yield download_file(sd_hash)
    #         yield check_md5_sum()
    #         yield check_lbry_file(downloader)
    #         yield delete_lbry_file(downloader)
    #         downloader = yield download_file(sd_hash)
    #         yield check_lbry_file(downloader)
    #         yield check_md5_sum()
    #         yield delete_lbry_file(downloader)
    #
    #     def stop(arg):
    #         if isinstance(arg, Failure):
    #             logging.debug("Client is stopping due to an error. Error: %s", arg.getTraceback())
    #         else:
    #             logging.debug("Client is stopping normally.")
    #         kill_event.set()
    #         logging.debug("Set the kill event")
    #         d = self.wait_for_event(dead_event, 15)
    #
    #         def print_shutting_down():
    #             logging.info("Client is shutting down")
    #
    #         d.addCallback(lambda _: print_shutting_down())
    #         d.addCallback(lambda _: rm_db_and_blob_dir(db_dir, blob_dir))
    #         d.addCallback(lambda _: arg)
    #         return d
    #
    #     d = self.wait_for_hash_from_queue(sd_hash_queue)
    #     d.addCallback(start_transfer)
    #     d.addBoth(stop)
    #     return d
