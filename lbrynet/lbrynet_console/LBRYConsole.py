import logging
from lbrynet.core.Session import LBRYSession
import os.path
import argparse
from yapsy.PluginManager import PluginManager
from twisted.internet import defer, threads, stdio, task
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
from lbrynet.lbryfile.client.LBRYFileDownloader import LBRYFileOpenerFactory
from lbrynet.lbryfile.StreamDescriptor import LBRYFileStreamType
from lbrynet.lbryfile.LBRYFileMetadataManager import DBLBRYFileMetadataManager, TempLBRYFileMetadataManager
#from lbrynet.lbrylive.PaymentRateManager import LiveStreamPaymentRateManager
from lbrynet.lbrynet_console.ControlHandlers import ApplicationStatusFactory, GetWalletBalancesFactory, ShutDownFactory
from lbrynet.lbrynet_console.ControlHandlers import LBRYFileStatusFactory, DeleteLBRYFileChooserFactory
from lbrynet.lbrynet_console.ControlHandlers import ToggleLBRYFileRunningChooserFactory
from lbrynet.lbrynet_console.ControlHandlers import ModifyApplicationDefaultsFactory
from lbrynet.lbrynet_console.ControlHandlers import CreateLBRYFileFactory, PublishStreamDescriptorChooserFactory
from lbrynet.lbrynet_console.ControlHandlers import ShowPublishedSDHashesChooserFactory
from lbrynet.lbrynet_console.ControlHandlers import CreatePlainStreamDescriptorChooserFactory
from lbrynet.lbrynet_console.ControlHandlers import ShowLBRYFileStreamHashChooserFactory, AddStreamFromHashFactory
from lbrynet.lbrynet_console.ControlHandlers import AddStreamFromSDFactory, AddStreamFromLBRYcrdNameFactory
from lbrynet.lbrynet_console.ControlHandlers import ClaimNameFactory
from lbrynet.lbrynet_console.ControlHandlers import ShowServerStatusFactory, ModifyServerSettingsFactory
from lbrynet.lbrynet_console.ControlHandlers import ModifyLBRYFileOptionsChooserFactory
from lbrynet.lbrynet_console.ControlHandlers import PeerStatsAndSettingsChooserFactory
from lbrynet.core.LBRYcrdWallet import LBRYcrdWallet


class LBRYConsole():
    """A class which can upload and download file streams to and from the network"""
    def __init__(self, peer_port, dht_node_port, known_dht_nodes, control_class, wallet_type, lbrycrd_rpc_port,
                 use_upnp, conf_dir, data_dir):
        """
        @param peer_port: the network port on which to listen for peers

        @param dht_node_port: the network port on which to listen for dht node requests

        @param known_dht_nodes: a list of (ip_address, dht_port) which will be used to join the DHT network
        """
        self.peer_port = peer_port
        self.dht_node_port = dht_node_port
        self.known_dht_nodes = known_dht_nodes
        self.wallet_type = wallet_type
        self.wallet_rpc_port = lbrycrd_rpc_port
        self.use_upnp = use_upnp
        self.lbry_server_port = None
        self.control_class = control_class
        self.session = None
        self.lbry_file_metadata_manager = None
        self.lbry_file_manager = None
        self.conf_dir = conf_dir
        self.data_dir = data_dir
        self.plugin_manager = PluginManager()
        self.plugin_manager.setPluginPlaces([
            os.path.join(self.conf_dir, "plugins"),
            os.path.join(os.path.dirname(__file__), "plugins"),
        ])
        self.control_handlers = []
        self.query_handlers = {}

        self.settings = LBRYSettings(self.conf_dir)
        self.blob_request_payment_rate_manager = None
        self.lbryid = None
        self.sd_identifier = StreamDescriptorIdentifier()

    def start(self):
        """Initialize the session and restore everything to its saved state"""
        d = threads.deferToThread(self._create_directory)
        d.addCallback(lambda _: self._get_settings())
        d.addCallback(lambda _: self._get_session())
        d.addCallback(lambda _: self._setup_lbry_file_manager())
        d.addCallback(lambda _: self._setup_lbry_file_opener())
        d.addCallback(lambda _: self._setup_control_handlers())
        d.addCallback(lambda _: self._setup_query_handlers())
        d.addCallback(lambda _: self._load_plugins())
        d.addCallback(lambda _: self._setup_server())
        d.addCallback(lambda _: self._start_controller())
        return d

    def shut_down(self):
        """Stop the session, all currently running streams, and stop the server"""
        d = self.session.shut_down()
        d.addCallback(lambda _: self._shut_down())
        return d

    def add_control_handlers(self, control_handlers):
        for control_handler in control_handlers:
            self.control_handlers.append(control_handler)

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

    def _create_directory(self):
        if not os.path.exists(self.conf_dir):
            os.makedirs(self.conf_dir)
            logging.debug("Created the configuration directory: %s", str(self.conf_dir))
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            logging.debug("Created the data directory: %s", str(self.data_dir))

    def _get_settings(self):
        d = self.settings.start()
        d.addCallback(lambda _: self.settings.get_lbryid())
        d.addCallback(self.set_lbryid)
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
        d = self.settings.get_default_data_payment_rate()

        def create_session(default_data_payment_rate):
            if default_data_payment_rate is None:
                default_data_payment_rate = MIN_BLOB_DATA_PAYMENT_RATE
            if self.wallet_type == "lbrycrd":
                wallet = LBRYcrdWallet("rpcuser", "rpcpassword", "127.0.0.1", self.wallet_rpc_port)
            else:
                wallet = PTCWallet(self.conf_dir)
            self.session = LBRYSession(default_data_payment_rate, db_dir=self.conf_dir, lbryid=self.lbryid,
                                       blob_dir=self.data_dir, dht_node_port=self.dht_node_port,
                                       known_dht_nodes=self.known_dht_nodes, peer_port=self.peer_port,
                                       use_upnp=self.use_upnp, wallet=wallet)

        d.addCallback(create_session)

        d.addCallback(lambda _: self.session.setup())

        return d

    def _setup_lbry_file_manager(self):
        self.lbry_file_metadata_manager = DBLBRYFileMetadataManager(self.conf_dir)
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
            ('General',
             ApplicationStatusFactory(self.session.rate_limiter, self.session.dht_node)),
            ('General',
             GetWalletBalancesFactory(self.session.wallet)),
            ('General',
             ModifyApplicationDefaultsFactory(self)),
            ('General',
             ShutDownFactory(self)),
            ('General',
             PeerStatsAndSettingsChooserFactory(self.session.peer_manager)),
            ('lbryfile',
             LBRYFileStatusFactory(self.lbry_file_manager)),
            ('Stream Downloading',
             AddStreamFromSDFactory(self.sd_identifier, self.session.base_payment_rate_manager)),
            ('lbryfile',
             DeleteLBRYFileChooserFactory(self.lbry_file_metadata_manager, self.session.blob_manager,
                                          self.lbry_file_manager)),
            ('lbryfile',
             ToggleLBRYFileRunningChooserFactory(self.lbry_file_manager)),
            ('lbryfile',
             CreateLBRYFileFactory(self.session, self.lbry_file_manager)),
            ('lbryfile',
             PublishStreamDescriptorChooserFactory(self.lbry_file_metadata_manager,
                                                   self.session.blob_manager,
                                                   self.lbry_file_manager)),
            ('lbryfile',
             ShowPublishedSDHashesChooserFactory(self.lbry_file_metadata_manager,
                                                 self.lbry_file_manager)),
            ('lbryfile',
             CreatePlainStreamDescriptorChooserFactory(self.lbry_file_manager)),
            ('lbryfile',
             ShowLBRYFileStreamHashChooserFactory(self.lbry_file_manager)),
            ('lbryfile',
             ModifyLBRYFileOptionsChooserFactory(self.lbry_file_manager)),
            ('Stream Downloading',
             AddStreamFromHashFactory(self.sd_identifier, self.session))
        ]
        self.add_control_handlers(handlers)
        if self.wallet_type == 'lbrycrd':
            lbrycrd_handlers = [
                ('Stream Downloading',
                 AddStreamFromLBRYcrdNameFactory(self.sd_identifier, self.session,
                                                 self.session.wallet)),
                ('General',
                 ClaimNameFactory(self.session.wallet)),
            ]
            self.add_control_handlers(lbrycrd_handlers)
        if self.peer_port is not None:
            server_handlers = [
                ('Server',
                 ShowServerStatusFactory(self)),
                ('Server',
                 ModifyServerSettingsFactory(self)),
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
                ds.append(plugin.plugin_object.setup(self))
            return defer.DeferredList(ds)

        d.addCallback(lambda _: setup_plugins())
        return d

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
            self.lbry_server_port = reactor.listenTCP(self.peer_port, server_factory)
        return defer.succeed(True)

    def stop_server(self):
        if self.lbry_server_port is not None:
            self.lbry_server_port, p = None, self.lbry_server_port
            return defer.maybeDeferred(p.stopListening)
        else:
            return defer.succeed(True)

    def _start_controller(self):
        self.control_class(self.control_handlers)
        return defer.succeed(True)

    def _shut_down(self):
        self.plugin_manager = None
        d1 = self.lbry_file_metadata_manager.stop()
        d1.addCallback(lambda _: self.lbry_file_manager.stop())
        d2 = self.stop_server()
        dl = defer.DeferredList([d1, d2])
        return dl


class StdIOControl():
    def __init__(self, control_handlers):
        stdio.StandardIO(ConsoleControl(control_handlers))


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
    parser.add_argument("--lbrycrd_wallet_rpc_port",
                        help="The rpc port on which the LBRYcrd wallet is listening",
                        type=int, default=8332)
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
    parser.add_argument("--use_upnp",
                        help="Try to use UPnP to enable incoming connections through the firewall",
                        action="store_true")
    parser.add_argument("--conf_dir",
                        help=("The full path to the directory in which to store configuration "
                              "options and user added plugins. Default: ~/.lbrynet"),
                        type=str)
    parser.add_argument("--data_dir",
                        help=("The full path to the directory in which to store data chunks "
                              "downloaded from lbrynet. Default: <conf_dir>/blobfiles"),
                        type=str)

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

    if not args.conf_dir:
        conf_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
    else:
        conf_dir = args.conf_dir
    if not os.path.exists(conf_dir):
        os.mkdir(conf_dir)
    if not args.data_dir:
        data_dir = os.path.join(conf_dir, "blobfiles")
    else:
        data_dir = args.data_dir
    if not os.path.exists(data_dir):
        os.mkdir(data_dir)

    log_format = "(%(asctime)s)[%(filename)s:%(lineno)s] %(funcName)s(): %(message)s"
    logging.basicConfig(level=logging.DEBUG, filename=os.path.join(conf_dir, "console.log"),
                        format=log_format)

    console = LBRYConsole(peer_port, dht_node_port, bootstrap_nodes, StdIOControl, wallet_type=args.wallet_type,
                          lbrycrd_rpc_port=args.lbrycrd_wallet_rpc_port, use_upnp=args.use_upnp,
                          conf_dir=conf_dir, data_dir=data_dir)

    d = task.deferLater(reactor, 0, console.start)
    reactor.addSystemEventTrigger('before', 'shutdown', console.shut_down)
    reactor.run()