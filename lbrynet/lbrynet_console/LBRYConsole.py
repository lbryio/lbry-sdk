import logging
from lbrynet.core.Session import LBRYSession
import os.path
import argparse
import requests
import locale
from yapsy.PluginManager import PluginManager
from twisted.internet import defer, threads, stdio, task, error
# from lbrynet.core.client.AutoDownloader import AutoFetcher
from lbrynet.lbrynet_console.ConsoleControl import ConsoleControl
from lbrynet.lbrynet_console.LBRYSettings import LBRYSettings
from lbrynet.lbryfilemanager.LBRYFileManager import LBRYFileManager
from lbrynet.conf import MIN_BLOB_DATA_PAYMENT_RATE  # , MIN_BLOB_INFO_PAYMENT_RATE
from lbrynet.core.utils import generate_id
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier
from lbrynet.core.PaymentRateManager import PaymentRateManager
from lbrynet.core.server.BlobAvailabilityHandler import BlobAvailabilityHandlerFactory
from lbrynet.core.server.BlobRequestHandler import BlobRequestHandlerFactory
from lbrynet.core.server.ServerProtocol import ServerProtocolFactory
from lbrynet.core.PTCWallet import PTCWallet
from lbrynet.lbryfile.client.LBRYFileOptions import add_lbry_file_to_sd_identifier
from lbrynet.lbryfile.client.LBRYFileDownloader import LBRYFileOpenerFactory
from lbrynet.lbryfile.StreamDescriptor import LBRYFileStreamType
from lbrynet.lbryfile.LBRYFileMetadataManager import DBLBRYFileMetadataManager, TempLBRYFileMetadataManager
#from lbrynet.lbrylive.PaymentRateManager import LiveStreamPaymentRateManager
from lbrynet.lbrynet_console.ControlHandlers import ApplicationStatusFactory, GetWalletBalancesFactory, ShutDownFactory
#from lbrynet.lbrynet_console.ControlHandlers import AutoFetcherStartFactory, AutoFetcherStopFactory
from lbrynet.lbrynet_console.ControlHandlers import ImmediateAnnounceAllBlobsFactory #, AutoFetcherStatusFactory
from lbrynet.lbrynet_console.ControlHandlers import LBRYFileStatusFactory, DeleteLBRYFileChooserFactory
from lbrynet.lbrynet_console.ControlHandlers import ToggleLBRYFileRunningChooserFactory
from lbrynet.lbrynet_console.ControlHandlers import ModifyApplicationDefaultsFactory
from lbrynet.lbrynet_console.ControlHandlers import CreateLBRYFileFactory, PublishStreamDescriptorChooserFactory
from lbrynet.lbrynet_console.ControlHandlers import ShowPublishedSDHashesChooserFactory
from lbrynet.lbrynet_console.ControlHandlers import CreatePlainStreamDescriptorChooserFactory
from lbrynet.lbrynet_console.ControlHandlers import ShowLBRYFileStreamHashChooserFactory, AddStreamFromHashFactory
from lbrynet.lbrynet_console.ControlHandlers import AddStreamFromSDFactory, AddStreamFromLBRYcrdNameFactory
from lbrynet.lbrynet_console.ControlHandlers import ClaimNameFactory, GetNewWalletAddressFactory
from lbrynet.lbrynet_console.ControlHandlers import ShowServerStatusFactory, ModifyServerSettingsFactory
from lbrynet.lbrynet_console.ControlHandlers import ModifyLBRYFileOptionsChooserFactory, StatusFactory
from lbrynet.lbrynet_console.ControlHandlers import PeerStatsAndSettingsChooserFactory, PublishFactory
from lbrynet.lbrynet_console.ControlHandlers import BlockchainStatusFactory
from lbrynet.core.LBRYcrdWallet import LBRYcrdWallet


log = logging.getLogger(__name__)
alert = logging.getLogger("lbryalert." + __name__)


class LBRYConsole():
    """A class which can upload and download file streams to and from the network"""
    def __init__(self, peer_port, dht_node_port, known_dht_nodes, wallet_type,
                 lbrycrd_conf, lbrycrd_dir, use_upnp, data_dir, created_data_dir,
                 lbrycrdd_path, start_lbrycrdd):
        """
        @param peer_port: the network port on which to listen for peers

        @param dht_node_port: the network port on which to listen for dht node requests

        @param known_dht_nodes: a list of (ip_address, dht_port) which will be used to join the DHT network
        """
        self.peer_port = peer_port
        self.dht_node_port = dht_node_port
        self.known_dht_nodes = known_dht_nodes
        self.wallet_type = wallet_type
        self.lbrycrd_conf = lbrycrd_conf
        self.lbrycrd_dir = lbrycrd_dir
        if not self.lbrycrd_dir:
            self.lbrycrd_dir = os.path.join(os.path.expanduser("~"), ".lbrycrd")
        if not self.lbrycrd_conf:
            self.lbrycrd_conf = os.path.join(self.lbrycrd_dir, "lbrycrd.conf")
        # self.autofetcher_conf = os.path.join(self.lbrycrd_dir, "autofetcher.conf")
        self.lbrycrdd_path = lbrycrdd_path
        self.default_lbrycrdd_path = "./lbrycrdd"
        self.start_lbrycrdd = start_lbrycrdd
        self.use_upnp = use_upnp
        self.lbry_server_port = None
        self.session = None
        self.lbry_file_metadata_manager = None
        self.lbry_file_manager = None
        self.db_dir = data_dir
        self.current_db_revision = 1
        self.blobfile_dir = os.path.join(self.db_dir, "blobfiles")
        self.created_data_dir = created_data_dir
        self.plugin_manager = PluginManager()
        self.plugin_manager.setPluginPlaces([
            os.path.join(self.db_dir, "plugins"),
            os.path.join(os.path.dirname(__file__), "plugins"),
        ])
        self.command_handlers = []
        self.query_handlers = {}

        self.settings = LBRYSettings(self.db_dir)
        self.blob_request_payment_rate_manager = None
        self.lbryid = None
        self.sd_identifier = StreamDescriptorIdentifier()
        self.plugin_objects = []
        self.db_migration_revisions = None
        # self.autofetcher = None

    def start(self):
        """Initialize the session and restore everything to its saved state"""
        d = self._setup_controller()
        d.addCallback(lambda _: threads.deferToThread(self._setup_data_directory))
        d.addCallback(lambda _: self._check_db_migration())
        d.addCallback(lambda _: self._get_settings())
        d.addCallback(lambda _: self._get_session())
        d.addCallback(lambda _: add_lbry_file_to_sd_identifier(self.sd_identifier))
        d.addCallback(lambda _: self._setup_lbry_file_manager())
        d.addCallback(lambda _: self._setup_lbry_file_opener())
        #d.addCallback(lambda _: self._get_autofetcher())
        d.addCallback(lambda _: self._setup_control_handlers())
        d.addCallback(lambda _: self._setup_query_handlers())
        d.addCallback(lambda _: self._load_plugins())
        d.addCallback(lambda _: self._setup_server())
        d.addCallback(lambda _: self._start_controller())
        d.addErrback(self._show_start_error)
        return d

    # def _get_autofetcher(self):
    #     self.autofetcher = AutoFetcher(self.session, self.lbry_file_manager, self.lbry_file_metadata_manager,
    #                                    self.session.wallet, self.sd_identifier, self.autofetcher_conf)

    def _show_start_error(self, error):
        print error.getErrorMessage()
        log.error("An error occurred during start up: %s", error.getTraceback())
        return error

    def _show_shutdown_error(self, error):
        print error.getErrorMessage()
        log.error("An error occurred during shutdown: %s", error.getTraceback())
        return error

    def shut_down(self):
        """Stop the session, all currently running streams, and stop the server"""
        d = self._shut_down()
        if self.session is not None:
            d.addCallback(lambda _: self.session.shut_down())
        d.addErrback(self._show_shutdown_error)
        return d

    def add_control_handlers(self, control_handlers):
        for control_handler in control_handlers:
            self.command_handlers.append(control_handler)

    def add_query_handlers(self, query_handlers):

        def _set_query_handlers(statuses):
            from future_builtins import zip
            for handler, (success, status) in zip(query_handlers, statuses):
                if success is True:
                    self.query_handlers[handler] = status

        ds = []
        for handler in query_handlers:
            ds.append(self.settings.get_query_handler_status(handler.get_primary_query_identifier()))
        dl = defer.DeferredList(ds)
        dl.addCallback(_set_query_handlers)
        return dl

    def _setup_data_directory(self):
        alert.info("Loading databases...")
        if self.created_data_dir:
            db_revision = open(os.path.join(self.db_dir, "db_revision"), mode='w')
            db_revision.write(str(self.current_db_revision))
            db_revision.close()
            log.debug("Created the db revision file: %s", str(os.path.join(self.db_dir, "db_revision")))
        if not os.path.exists(self.blobfile_dir):
            os.mkdir(self.blobfile_dir)
            log.debug("Created the blobfile directory: %s", str(self.blobfile_dir))

    def _check_db_migration(self):
        old_revision = 0
        db_revision_file = os.path.join(self.db_dir, "db_revision")
        if os.path.exists(db_revision_file):
            old_revision = int(open(db_revision_file).read().strip())
        if old_revision < self.current_db_revision:
            from lbrynet.db_migrator import dbmigrator
            print "Upgrading your databases..."
            d = threads.deferToThread(dbmigrator.migrate_db, self.db_dir, old_revision, self.current_db_revision)

            def print_success(old_dirs):
                success_string = "Finished upgrading the databases. It is now safe to delete the"
                success_string += " following directories, if you feel like it. It won't make any"
                success_string += " difference.\nAnyway here they are: "
                for i, old_dir in enumerate(old_dirs):
                    success_string += old_dir
                    if i + 1 < len(old_dir):
                        success_string += ", "
                print success_string

            d.addCallback(print_success)
            return d
        return defer.succeed(True)

    def _get_settings(self):
        d = self.settings.start()
        d.addCallback(lambda _: self.settings.get_lbryid())
        d.addCallback(self.set_lbryid)
        d.addCallback(lambda _: self.get_lbrycrdd_path())
        return d

    def get_lbrycrdd_path(self):

        if not self.start_lbrycrdd:
            return defer.succeed(None)

        def get_lbrycrdd_path_conf_file():
            lbrycrdd_path_conf_path = os.path.join(os.path.expanduser("~"), ".lbrycrddpath.conf")
            if not os.path.exists(lbrycrdd_path_conf_path):
                return ""
            lbrycrdd_path_conf = open(lbrycrdd_path_conf_path)
            lines = lbrycrdd_path_conf.readlines()
            return lines

        d = threads.deferToThread(get_lbrycrdd_path_conf_file)

        def load_lbrycrdd_path(conf):
            for line in conf:
                if len(line.strip()) and line.strip()[0] != "#":
                    self.lbrycrdd_path = line.strip()

        d.addCallback(load_lbrycrdd_path)
        return d

    def set_lbryid(self, lbryid):
        if lbryid is None:
            return self._make_lbryid()
        else:
            self.lbryid = lbryid

    def _make_lbryid(self):
        self.lbryid = generate_id()
        d = self.settings.save_lbryid(self.lbryid)
        return d

    def _get_session(self):
        def get_default_data_rate():
            d = self.settings.get_default_data_payment_rate()
            d.addCallback(lambda rate: {"default_data_payment_rate": rate if rate is not None else MIN_BLOB_DATA_PAYMENT_RATE})
            return d

        def get_wallet():
            if self.wallet_type == "lbrycrd":
                lbrycrdd_path = None
                if self.start_lbrycrdd is True:
                    lbrycrdd_path = self.lbrycrdd_path
                    if not lbrycrdd_path:
                        lbrycrdd_path = self.default_lbrycrdd_path
                d = defer.succeed(LBRYcrdWallet(self.db_dir, wallet_dir=self.lbrycrd_dir,
                                                wallet_conf=self.lbrycrd_conf,
                                                lbrycrdd_path=lbrycrdd_path))
            else:
                d = defer.succeed(PTCWallet(self.db_dir))
            d.addCallback(lambda wallet: {"wallet": wallet})
            return d

        d1 = get_default_data_rate()
        d2 = get_wallet()

        def combine_results(results):
            r = {}
            for success, result in results:
                if success is True:
                    r.update(result)
            return r

        def create_session(results):

            alert.info("Databases loaded.")

            self.session = LBRYSession(results['default_data_payment_rate'], db_dir=self.db_dir, lbryid=self.lbryid,
                                       blob_dir=self.blobfile_dir, dht_node_port=self.dht_node_port,
                                       known_dht_nodes=self.known_dht_nodes, peer_port=self.peer_port,
                                       use_upnp=self.use_upnp, wallet=results['wallet'])

        dl = defer.DeferredList([d1, d2], fireOnOneErrback=True)

        dl.addCallback(combine_results)

        dl.addCallback(create_session)

        dl.addCallback(lambda _: self.session.setup())

        dl.addCallback(lambda _: self.check_first_run())

        dl.addCallback(self._show_first_run_result)

        return dl

    def check_first_run(self):
        d = self.session.wallet.check_first_run()
        d.addCallback(lambda is_first_run: self._do_first_run() if is_first_run else 0.0)
        return d

    def _do_first_run(self):
        d = self.session.wallet.get_new_address()

        def send_request(url, data):
            r = requests.post(url, json=data)
            if r.status_code == 200:
                return r.json()['credits_sent']
            return 0.0

        def log_error(err):
            log.warning("unable to request free credits. %s", err.getErrorMessage())
            return 0.0

        def request_credits(address):
            url = "http://credreq.lbry.io/requestcredits"
            data = {"address": address}
            d = threads.deferToThread(send_request, url, data)
            d.addErrback(log_error)
            return d

        d.addCallback(request_credits)
        return d

    @staticmethod
    def _show_first_run_result(credits_received):
        if credits_received != 0.0:
            points_string = locale.format_string("%.2f LBC", (round(credits_received, 2),),
                                                 grouping=True)
            alert.info("\n\nThank you for testing the alpha version of LBRY!\n\n"
                       "You have been given %s for free because we love you.\n"
                       "Please give them a few minutes to show up while you\n"
                       "catch up with our blockchain.\n", points_string)

    def _setup_lbry_file_manager(self):
        self.lbry_file_metadata_manager = DBLBRYFileMetadataManager(self.db_dir)
        d = self.lbry_file_metadata_manager.setup()

        def set_lbry_file_manager():
            self.lbry_file_manager = LBRYFileManager(self.session, self.lbry_file_metadata_manager, self.sd_identifier)
            return self.lbry_file_manager.setup()

        d.addCallback(lambda _: set_lbry_file_manager())

        return d

    def _setup_lbry_file_opener(self):
        stream_info_manager = TempLBRYFileMetadataManager()
        downloader_factory = LBRYFileOpenerFactory(self.session.peer_finder, self.session.rate_limiter,
                                                   self.session.blob_manager, stream_info_manager,
                                                   self.session.wallet)
        self.sd_identifier.add_stream_downloader_factory(LBRYFileStreamType, downloader_factory)
        return defer.succeed(True)

    def _setup_control_handlers(self):
        handlers = [
            ApplicationStatusFactory(self.session.rate_limiter, self.session.dht_node),
            GetWalletBalancesFactory(self.session.wallet),
            ModifyApplicationDefaultsFactory(self),
            ShutDownFactory(self),
            PeerStatsAndSettingsChooserFactory(self.session.peer_manager),
            LBRYFileStatusFactory(self.lbry_file_manager),
            AddStreamFromSDFactory(self.sd_identifier, self.session.base_payment_rate_manager,
                                   self.session.wallet),
            DeleteLBRYFileChooserFactory(self.lbry_file_metadata_manager, self.session.blob_manager,
                                         self.lbry_file_manager),
            ToggleLBRYFileRunningChooserFactory(self.lbry_file_manager),
            CreateLBRYFileFactory(self.session, self.lbry_file_manager),
            PublishStreamDescriptorChooserFactory(self.lbry_file_metadata_manager,
                                                  self.session.blob_manager),
            ShowPublishedSDHashesChooserFactory(self.lbry_file_metadata_manager,
                                                self.lbry_file_manager),
            CreatePlainStreamDescriptorChooserFactory(self.lbry_file_manager),
            ShowLBRYFileStreamHashChooserFactory(self.lbry_file_manager),
            ModifyLBRYFileOptionsChooserFactory(self.lbry_file_manager),
            AddStreamFromHashFactory(self.sd_identifier, self.session, self.session.wallet),
            StatusFactory(self, self.session.rate_limiter, self.lbry_file_manager,
                          self.session.blob_manager, self.session.wallet if self.wallet_type == 'lbrycrd' else None),
            # AutoFetcherStartFactory(self.autofetcher),
            # AutoFetcherStopFactory(self.autofetcher),
            # AutoFetcherStatusFactory(self.autofetcher),
            ImmediateAnnounceAllBlobsFactory(self.session.blob_manager)
        ]
        self.add_control_handlers(handlers)
        if self.wallet_type == 'lbrycrd':
            lbrycrd_handlers = [
                AddStreamFromLBRYcrdNameFactory(self.sd_identifier, self.session,
                                                self.session.wallet),
                ClaimNameFactory(self.session.wallet, self.lbry_file_manager,
                                 self.session.blob_manager),
                GetNewWalletAddressFactory(self.session.wallet),
                PublishFactory(self.session, self.lbry_file_manager, self.session.wallet),
                BlockchainStatusFactory(self.session.wallet)
            ]
            self.add_control_handlers(lbrycrd_handlers)
        if self.peer_port is not None:
            server_handlers = [
                ShowServerStatusFactory(self),
                ModifyServerSettingsFactory(self),
            ]
            self.add_control_handlers(server_handlers)

    def _setup_query_handlers(self):
        handlers = [
            #CryptBlobInfoQueryHandlerFactory(self.lbry_file_metadata_manager, self.session.wallet,
            #                                 self._server_payment_rate_manager),
            BlobAvailabilityHandlerFactory(self.session.blob_manager),
            #BlobRequestHandlerFactory(self.session.blob_manager, self.session.wallet,
            #                          self._server_payment_rate_manager),
            self.session.wallet.get_wallet_info_query_handler_factory(),
        ]

        def get_blob_request_handler_factory(rate):
            self.blob_request_payment_rate_manager = PaymentRateManager(
                self.session.base_payment_rate_manager, rate
            )
            handlers.append(BlobRequestHandlerFactory(self.session.blob_manager, self.session.wallet,
                                                      self.blob_request_payment_rate_manager))

        d1 = self.settings.get_server_data_payment_rate()
        d1.addCallback(get_blob_request_handler_factory)

        dl = defer.DeferredList([d1])
        dl.addCallback(lambda _: self.add_query_handlers(handlers))
        return dl

    def _load_plugins(self):
        d = threads.deferToThread(self.plugin_manager.collectPlugins)

        def setup_plugins():
            ds = []
            for plugin in self.plugin_manager.getAllPlugins():
                self.plugin_objects.append(plugin.plugin_object)
                ds.append(plugin.plugin_object.setup(self))
            return defer.DeferredList(ds)

        d.addCallback(lambda _: setup_plugins())
        return d

    def _stop_plugins(self):
        ds = []
        for plugin_object in self.plugin_objects:
            ds.append(defer.maybeDeferred(plugin_object.stop))
        return defer.DeferredList(ds)

    def _setup_server(self):

        def restore_running_status(running):
            if running is True:
                return self.start_server()
            return defer.succeed(True)

        dl = self.settings.get_server_running_status()
        dl.addCallback(restore_running_status)
        return dl

    def start_server(self):

        if self.peer_port is not None:

            server_factory = ServerProtocolFactory(self.session.rate_limiter,
                                                   self.query_handlers,
                                                   self.session.peer_manager)
            from twisted.internet import reactor
            try:
                self.lbry_server_port = reactor.listenTCP(self.peer_port, server_factory)
            except error.CannotListenError as e:
                import traceback
                log.error("Couldn't bind to port %d. %s", self.peer_port, traceback.format_exc())
                raise ValueError("%s lbrynet may already be running on your computer.", str(e))
        return defer.succeed(True)

    def stop_server(self):
        if self.lbry_server_port is not None:
            self.lbry_server_port, p = None, self.lbry_server_port
            return defer.maybeDeferred(p.stopListening)
        else:
            return defer.succeed(True)

    def _setup_controller(self):
        self.controller = ConsoleControl()
        stdio.StandardIO(self.controller)
        logger = logging.getLogger()
        formatter = logging.Formatter("%(message)s")
        alert_handler = logging.StreamHandler(self.controller)
        alert_handler.setFormatter(formatter)
        alert_handler.addFilter(logging.Filter("lbryalert"))
        alert_handler.setLevel(logging.DEBUG)
        logger.addHandler(alert_handler)
        return defer.succeed(True)

    def _start_controller(self):
        return self.controller.start(self.command_handlers)

    def _shut_down(self):
        self.plugin_manager = None
        ds = []
        if self.lbry_file_metadata_manager is not None:
            d = self.lbry_file_metadata_manager.stop()
            d.addCallback(lambda _: self.lbry_file_manager.stop())
            ds.append(d)
        ds.append(self.stop_server())
        ds.append(self._stop_plugins())
        dl = defer.DeferredList(ds)
        return dl


def launch_lbry_console():

    from twisted.internet import reactor

    parser = argparse.ArgumentParser(description="Launch a lbrynet console")
    parser.add_argument("--no_listen_peer",
                        help="Don't listen for incoming data connections.",
                        action="store_true")
    parser.add_argument("--peer_port",
                        help="The port on which the console will listen for incoming data connections.",
                        type=int, default=3333)
    parser.add_argument("--no_listen_dht",
                        help="Don't listen for incoming DHT connections.",
                        action="store_true")
    parser.add_argument("--dht_node_port",
                        help="The port on which the console will listen for DHT connections.",
                        type=int, default=4444)
    parser.add_argument("--wallet_type",
                        help="Either 'lbrycrd' or 'ptc'.",
                        type=str, default="lbrycrd")
    parser.add_argument("--lbrycrd_wallet_dir",
                        help="The directory in which lbrycrd data will stored. Used if lbrycrdd is "
                             "launched by this application.")
    parser.add_argument("--lbrycrd_wallet_conf",
                        help="The configuration file for the LBRYcrd wallet. Default: ~/.lbrycrd/lbrycrd.conf",
                        type=str)
    parser.add_argument("--no_dht_bootstrap",
                        help="Don't try to connect to the DHT",
                        action="store_true")
    parser.add_argument("--dht_bootstrap_host",
                        help="The hostname of a known DHT node, to be used to bootstrap into the DHT. "
                             "Must be used with --dht_bootstrap_port",
                        type=str, default='104.236.42.182')
    parser.add_argument("--dht_bootstrap_port",
                        help="The port of a known DHT node, to be used to bootstrap into the DHT. Must "
                             "be used with --dht_bootstrap_host",
                        type=int, default=4000)
    parser.add_argument("--disable_upnp",
                        help="Don't try to use UPnP to enable incoming connections through the firewall",
                        action="store_true")
    parser.add_argument("--data_dir",
                        help=("The full path to the directory in which lbrynet data and metadata will be stored. "
                              "Default: ~/.lbrynet"),
                        type=str)
    parser.add_argument("--lbrycrdd_path",
                        help="The path to lbrycrdd, which will be launched if it isn't running, unless "
                             "launching lbrycrdd is disabled by --disable_launch_lbrycrdd. By default, "
                             "the file ~/.lbrycrddpath.conf will be checked, and if no path is found "
                             "there, it will be ./lbrycrdd")
    parser.add_argument("--disable_launch_lbrycrdd",
                        help="Don't launch lbrycrdd even if it's not running.")

    args = parser.parse_args()

    if args.no_dht_bootstrap:
        bootstrap_nodes = []
    else:
        bootstrap_nodes = [(args.dht_bootstrap_host, args.dht_bootstrap_port)]

    if args.no_listen_peer:
        peer_port = None
    else:
        peer_port = args.peer_port

    if args.no_listen_dht:
        dht_node_port = None
    else:
        dht_node_port = args.dht_node_port

    created_data_dir = False
    if not args.data_dir:
        data_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
    else:
        data_dir = args.data_dir
    if not os.path.exists(data_dir):
        os.mkdir(data_dir)
        created_data_dir = True


    log_format = "(%(asctime)s)[%(filename)s:%(lineno)s] %(funcName)s(): %(message)s"
    formatter = logging.Formatter(log_format)

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    file_handler = logging.FileHandler(os.path.join(data_dir, "console.log"))
    file_handler.setFormatter(formatter)
    file_handler.addFilter(logging.Filter("lbrynet"))
    logger.addHandler(file_handler)

    console = LBRYConsole(peer_port, dht_node_port, bootstrap_nodes, wallet_type=args.wallet_type,
                          lbrycrd_conf=args.lbrycrd_wallet_conf, lbrycrd_dir=args.lbrycrd_wallet_dir,
                          use_upnp=not args.disable_upnp, data_dir=data_dir,
                          created_data_dir=created_data_dir, lbrycrdd_path=args.lbrycrdd_path,
                          start_lbrycrdd=not args.disable_launch_lbrycrdd)

    d = task.deferLater(reactor, 0, console.start)

    d.addErrback(lambda _: reactor.stop())

    reactor.addSystemEventTrigger('before', 'shutdown', console.shut_down)
    reactor.run()

if __name__ == "__main__":
    launch_lbry_console()