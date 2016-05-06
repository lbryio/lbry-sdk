import locale
import os
import sys
import simplejson as json
import binascii
import logging.handlers
import requests
import base58
import platform
import socket

from twisted.web import server
from twisted.internet import defer, threads, error, reactor
from twisted.internet.task import LoopingCall
from txjsonrpc import jsonrpclib
from txjsonrpc.web import jsonrpc
from txjsonrpc.web.jsonrpc import Handler

from datetime import datetime
from decimal import Decimal
from appdirs import user_data_dir
from urllib2 import urlopen

from lbrynet import __version__ as lbrynet_version
from lbryum.version import ELECTRUM_VERSION as lbryum_version
from lbrynet.core.PaymentRateManager import PaymentRateManager
from lbrynet.core.server.BlobAvailabilityHandler import BlobAvailabilityHandlerFactory
from lbrynet.core.server.BlobRequestHandler import BlobRequestHandlerFactory
from lbrynet.core.server.ServerProtocol import ServerProtocolFactory
from lbrynet.core.Error import UnknownNameError, InsufficientFundsError
from lbrynet.lbryfile.StreamDescriptor import LBRYFileStreamType
from lbrynet.lbryfile.client.LBRYFileDownloader import LBRYFileSaverFactory, LBRYFileOpenerFactory
from lbrynet.lbryfile.client.LBRYFileOptions import add_lbry_file_to_sd_identifier
from lbrynet.lbrynet_daemon.LBRYDownloader import GetStream
from lbrynet.lbrynet_daemon.LBRYPublisher import Publisher
from lbrynet.core.utils import generate_id
from lbrynet.lbrynet_console.LBRYSettings import LBRYSettings
from lbrynet.conf import MIN_BLOB_DATA_PAYMENT_RATE, DEFAULT_MAX_SEARCH_RESULTS, KNOWN_DHT_NODES, DEFAULT_MAX_KEY_FEE, \
    DEFAULT_WALLET, DEFAULT_SEARCH_TIMEOUT, DEFAULT_CACHE_TIME
from lbrynet.conf import API_CONNECTION_STRING, API_PORT, API_ADDRESS, DEFAULT_TIMEOUT, UI_ADDRESS
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier, download_sd_blob
from lbrynet.core.Session import LBRYSession
from lbrynet.core.PTCWallet import PTCWallet
from lbrynet.core.LBRYcrdWallet import LBRYcrdWallet, LBRYumWallet
from lbrynet.lbryfilemanager.LBRYFileManager import LBRYFileManager
from lbrynet.lbryfile.LBRYFileMetadataManager import DBLBRYFileMetadataManager, TempLBRYFileMetadataManager


if sys.platform != "darwin":
    log_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
else:
    log_dir = user_data_dir("LBRY")

if not os.path.isdir(log_dir):
    os.mkdir(log_dir)

LOG_FILENAME = os.path.join(log_dir, 'lbrynet-daemon.log')

if os.path.isfile(LOG_FILENAME):
    f = open(LOG_FILENAME, 'r')
    PREVIOUS_LOG = len(f.read())
    f.close()
else:
    PREVIOUS_LOG = 0

log = logging.getLogger(__name__)
handler = logging.handlers.RotatingFileHandler(LOG_FILENAME, maxBytes=2097152, backupCount=5)
log.addHandler(handler)
log.setLevel(logging.INFO)

INITIALIZING_CODE = 'initializing'
LOADING_DB_CODE = 'loading_db'
LOADING_WALLET_CODE = 'loading_wallet'
LOADING_FILE_MANAGER_CODE = 'loading_file_manager'
LOADING_SERVER_CODE = 'loading_server'
STARTED_CODE = 'started'
STARTUP_STAGES = [
                    (INITIALIZING_CODE, 'Initializing...'),
                    (LOADING_DB_CODE, 'Loading databases...'),
                    (LOADING_WALLET_CODE, 'Catching up with the blockchain... %s'),
                    (LOADING_FILE_MANAGER_CODE, 'Setting up file manager'),
                    (LOADING_SERVER_CODE, 'Starting lbrynet'),
                    (STARTED_CODE, 'Started lbrynet')
                  ]

DOWNLOAD_METADATA_CODE = 'downloading_metadata'
DOWNLOAD_TIMEOUT_CODE = 'timeout'
DOWNLOAD_RUNNING_CODE = 'running'
DOWNLOAD_STOPPED_CODE = 'stopped'
STREAM_STAGES = [
                    (INITIALIZING_CODE, 'Initializing...'),
                    (DOWNLOAD_METADATA_CODE, 'Downloading metadata'),
                    (DOWNLOAD_RUNNING_CODE, 'Started %s, got %s/%s blobs, stream status: %s'),
                    (DOWNLOAD_STOPPED_CODE, 'Paused stream'),
                    (DOWNLOAD_TIMEOUT_CODE, 'Stream timed out')
                ]

CONNECT_CODE_VERSION_CHECK = 'version_check'
CONNECT_CODE_NETWORK = 'network_connection'
CONNECT_CODE_WALLET = 'wallet_catchup_lag'
CONNECTION_PROBLEM_CODES = [
        (CONNECT_CODE_VERSION_CHECK, "There was a problem checking for updates on github"),
        (CONNECT_CODE_NETWORK, "Your internet connection appears to have been interrupted"),
        (CONNECT_CODE_WALLET, "Synchronization with the blockchain is lagging... if this continues try restarting LBRY")
        ]

ALLOWED_DURING_STARTUP = ['is_running', 'is_first_run',
                          'get_time_behind_blockchain', 'stop',
                          'daemon_status', 'get_start_notice',
                          'version', 'check_for_new_version']

BAD_REQUEST = 400
NOT_FOUND = 404
OK_CODE = 200

# TODO add login credentials in a conf file
# TODO alert if your copy of a lbry file is out of date with the name record


REMOTE_SERVER = "www.google.com"


class LBRYDaemon(jsonrpc.JSONRPC):
    """
    LBRYnet daemon, a jsonrpc interface to lbry functions
    """

    isLeaf = True

    def __init__(self, ui_version_info, wallet_type=DEFAULT_WALLET):
        jsonrpc.JSONRPC.__init__(self)
        reactor.addSystemEventTrigger('before', 'shutdown', self._shutdown)

        self.startup_status = STARTUP_STAGES[0]
        self.startup_message = None
        self.announced_startup = False
        self.connected_to_internet = True
        self.connection_problem = None
        self.query_handlers = {}
        self.ui_version = ui_version_info.replace('\n', '')
        self.git_lbrynet_version = None
        self.git_lbryum_version = None
        self.wallet_type = wallet_type
        self.first_run = None
        self.log_file = LOG_FILENAME
        self.current_db_revision = 1
        self.run_server = True
        self.session = None
        self.waiting_on = {}
        self.streams = {}
        self.known_dht_nodes = KNOWN_DHT_NODES
        self.platform_info = {
            "processor": platform.processor(),
            "python_version: ": platform.python_version(),
            "platform": platform.platform(),
            "os_release": platform.release(),
            "os_system": platform.system(),
            "lbrynet_version: ": lbrynet_version,
            "lbryum_version: ": lbryum_version,
            "ui_version": self.ui_version,
        }
        try:
            self.platform_info['ip'] = json.load(urlopen('http://jsonip.com'))['ip']
        except:
            self.platform_info['ip'] = "Could not determine"

        if os.name == "nt":
            from lbrynet.winhelpers.knownpaths import get_path, FOLDERID, UserHandle
            default_download_directory = get_path(FOLDERID.Downloads, UserHandle.current)
            self.db_dir = os.path.join(get_path(FOLDERID.RoamingAppData, UserHandle.current), "lbrynet")
            self.lbrycrdd_path = "lbrycrdd.exe"
            if wallet_type == "lbrycrd":
                self.wallet_dir = os.path.join(get_path(FOLDERID.RoamingAppData, UserHandle.current), "lbrycrd")
            else:
                self.wallet_dir = os.path.join(get_path(FOLDERID.RoamingAppData, UserHandle.current), "lbryum")
        elif sys.platform == "darwin":
            default_download_directory = os.path.join(os.path.expanduser("~"), 'Downloads')
            self.db_dir = user_data_dir("LBRY")
            self.lbrycrdd_path = "./lbrycrdd"
            if wallet_type == "lbrycrd":
                self.wallet_dir = user_data_dir("lbrycrd")
            else:
                self.wallet_dir = user_data_dir("LBRY")
        else:
            default_download_directory = os.getcwd()
            self.db_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
            self.lbrycrdd_path = "./lbrycrdd"
            if wallet_type == "lbrycrd":
                self.wallet_dir = os.path.join(os.path.expanduser("~"), ".lbrycrd")
            else:
                self.wallet_dir = os.path.join(os.path.expanduser("~"), ".lbryum")

        self.created_data_dir = False
        if not os.path.exists(self.db_dir):
            os.mkdir(self.db_dir)
            self.created_data_dir = True

        self.blobfile_dir = os.path.join(self.db_dir, "blobfiles")
        self.lbrycrd_conf = os.path.join(self.wallet_dir, "lbrycrd.conf")
        self.autofetcher_conf = os.path.join(self.wallet_dir, "autofetcher.conf")
        self.daemon_conf = os.path.join(self.db_dir, 'daemon_settings.json')
        self.wallet_conf = os.path.join(self.wallet_dir, "lbrycrd.conf")
        self.wallet_user = None
        self.wallet_password = None

        self.internet_connection_checker = LoopingCall(self._check_network_connection)
        self.version_checker = LoopingCall(self._check_remote_versions)
        self.connection_problem_checker = LoopingCall(self._check_connection_problems)
        # self.lbrynet_connection_checker = LoopingCall(self._check_lbrynet_connection)

        self.sd_identifier = StreamDescriptorIdentifier()
        self.stream_info_manager = TempLBRYFileMetadataManager()
        self.settings = LBRYSettings(self.db_dir)
        self.blob_request_payment_rate_manager = None
        self.lbry_file_metadata_manager = None
        self.lbry_file_manager = None

        self.default_settings = {
            'run_on_startup': False,
            'data_rate': MIN_BLOB_DATA_PAYMENT_RATE,
            'max_key_fee': DEFAULT_MAX_KEY_FEE,
            'download_directory': default_download_directory,
            'max_upload': 0.0,
            'max_download': 0.0,
            'upload_log': True,
            'search_timeout': DEFAULT_SEARCH_TIMEOUT,
            'download_timeout': DEFAULT_TIMEOUT,
            'max_search_results': DEFAULT_MAX_SEARCH_RESULTS,
            'wallet_type': wallet_type,
            'delete_blobs_on_remove': True,
            'peer_port': 3333,
            'dht_node_port': 4444,
            'use_upnp': True,
            'start_lbrycrdd': True,
            'requested_first_run_credits': False,
            'cache_time': DEFAULT_CACHE_TIME
        }

        if os.path.isfile(self.daemon_conf):
            f = open(self.daemon_conf, "r")
            loaded_settings = json.loads(f.read())
            f.close()
            missing_settings = {}
            removed_settings = {}
            for k in self.default_settings.keys():
                if k not in loaded_settings.keys():
                    missing_settings[k] = self.default_settings[k]
            for k in loaded_settings.keys():
                if not k in self.default_settings.keys():
                    log.info("Removing unused setting: " + k + " with value: " + str(loaded_settings[k]))
                    removed_settings[k] = loaded_settings[k]
                    del loaded_settings[k]
            for k in missing_settings.keys():
                log.info("Adding missing setting: " + k + " with default value: " + str(missing_settings[k]))
                loaded_settings[k] = missing_settings[k]
            if missing_settings or removed_settings:
                f = open(self.daemon_conf, "w")
                f.write(json.dumps(loaded_settings))
                f.close()
            else:
                log.info("Loaded lbrynet-daemon configuration")
            settings_dict = loaded_settings
        else:
            log.info(
                "Writing default settings : " + json.dumps(self.default_settings) + " --> " + str(self.daemon_conf))
            f = open(self.daemon_conf, "w")
            f.write(json.dumps(self.default_settings))
            f.close()
            settings_dict = self.default_settings

        self.session_settings = settings_dict

        self.run_on_startup = self.session_settings['run_on_startup']
        self.data_rate = self.session_settings['data_rate']
        self.max_key_fee = self.session_settings['max_key_fee']
        self.download_directory = self.session_settings['download_directory']
        self.max_upload = self.session_settings['max_upload']
        self.max_download = self.session_settings['max_download']
        self.upload_log = self.session_settings['upload_log']
        self.search_timeout = self.session_settings['search_timeout']
        self.download_timeout = self.session_settings['download_timeout']
        self.max_search_results = self.session_settings['max_search_results']
        self.wallet_type = self.session_settings['wallet_type']
        self.delete_blobs_on_remove = self.session_settings['delete_blobs_on_remove']
        self.peer_port = self.session_settings['peer_port']
        self.dht_node_port = self.session_settings['dht_node_port']
        self.use_upnp = self.session_settings['use_upnp']
        self.start_lbrycrdd = self.session_settings['start_lbrycrdd']
        self.requested_first_run_credits = self.session_settings['requested_first_run_credits']
        self.cache_time = self.session_settings['cache_time']

        if os.path.isfile(os.path.join(self.db_dir, "stream_info_cache.json")):
            f = open(os.path.join(self.db_dir, "stream_info_cache.json"), "r")
            self.name_cache = json.loads(f.read())
            f.close()
            log.info("Loaded claim info cache")
        else:
            self.name_cache = {}

    def render(self, request):
        request.content.seek(0, 0)
        # Unmarshal the JSON-RPC data.
        content = request.content.read()
        parsed = jsonrpclib.loads(content)
        functionPath = parsed.get("method")
        args = parsed.get('params')

        #TODO convert args to correct types if possible

        id = parsed.get('id')
        version = parsed.get('jsonrpc')
        if version:
            version = int(float(version))
        elif id and not version:
            version = jsonrpclib.VERSION_1
        else:
            version = jsonrpclib.VERSION_PRE1
        # XXX this all needs to be re-worked to support logic for multiple
        # versions...

        if not self.announced_startup:
            if functionPath not in ALLOWED_DURING_STARTUP:
                return server.failure

        try:
            function = self._getFunction(functionPath)
        except jsonrpclib.Fault, f:
            self._cbRender(f, request, id, version)
        else:
            request.setHeader("Access-Control-Allow-Origin", "*")
            request.setHeader("content-type", "text/json")
            if args == [{}]:
                d = defer.maybeDeferred(function)
            else:
                d = defer.maybeDeferred(function, *args)
            d.addErrback(self._ebRender, id)
            d.addCallback(self._cbRender, request, id, version)
        return server.NOT_DONE_YET

    def _cbRender(self, result, request, id, version):
        if isinstance(result, Handler):
            result = result.result

        if isinstance(result, dict):
            result = result['result']

        if version == jsonrpclib.VERSION_PRE1:
            if not isinstance(result, jsonrpclib.Fault):
                result = (result,)
            # Convert the result (python) to JSON-RPC
        try:
            s = jsonrpclib.dumps(result, version=version)
        except:
            f = jsonrpclib.Fault(self.FAILURE, "can't serialize output")
            s = jsonrpclib.dumps(f, version=version)
        request.setHeader("content-length", str(len(s)))
        request.write(s)
        request.finish()

    def _ebRender(self, failure, id):
        if isinstance(failure.value, jsonrpclib.Fault):
            return failure.value
        log.error(failure)
        return jsonrpclib.Fault(self.FAILURE, "error")

    def setup(self):
        def _log_starting_vals():
            d = self._get_lbry_files()
            d.addCallback(lambda r: json.dumps([d[1] for d in r]))
            d.addCallback(lambda r: log.info("LBRY Files: " + r))
            d.addCallback(lambda _: log.info("Starting balance: " + str(self.session.wallet.wallet_balance)))
            return d

        def _announce_startup():
            def _announce():
                self.announced_startup = True
                self.startup_status = STARTUP_STAGES[5]
                log.info("[" + str(datetime.now()) + "] Started lbrynet-daemon")
                # self.lbrynet_connection_checker.start(3600)

            if self.first_run:
                d = self._upload_log(name_prefix="fr")
            else:
                d = self._upload_log(exclude_previous=True, name_prefix="start")

            if float(self.session.wallet.wallet_balance) == 0.0:
                d.addCallback(lambda _: self._check_first_run())
                d.addCallback(self._show_first_run_result)

            d.addCallback(lambda _: _announce())
            return d

        log.info("[" + str(datetime.now()) + "] Starting lbrynet-daemon")

        self.internet_connection_checker.start(3600)
        self.version_checker.start(3600 * 12)
        self.connection_problem_checker.start(1)

        d = defer.Deferred()
        d.addCallback(lambda _: self._initial_setup())
        d.addCallback(lambda _: threads.deferToThread(self._setup_data_directory))
        d.addCallback(lambda _: self._check_db_migration())
        d.addCallback(lambda _: self._get_settings())
        d.addCallback(lambda _: self._get_lbrycrdd_path())
        d.addCallback(lambda _: self._get_session())
        d.addCallback(lambda _: add_lbry_file_to_sd_identifier(self.sd_identifier))
        d.addCallback(lambda _: self._setup_stream_identifier())
        d.addCallback(lambda _: self._setup_lbry_file_manager())
        d.addCallback(lambda _: self._setup_lbry_file_opener())
        d.addCallback(lambda _: self._setup_query_handlers())
        d.addCallback(lambda _: self._setup_server())
        d.addCallback(lambda _: _log_starting_vals())
        d.addCallback(lambda _: _announce_startup())
        d.callback(None)

        return defer.succeed(None)

    def _initial_setup(self):
        def _log_platform():
            log.info("Platform: " + json.dumps(self.platform_info))
            return defer.succeed(None)

        d = _log_platform()

        return d

    def _check_network_connection(self):
        try:
            host = socket.gethostbyname(REMOTE_SERVER)
            s = socket.create_connection((host, 80), 2)
            self.connected_to_internet = True
        except:
            log.info("[" + str(datetime.now()) + "] Internet connection not working")
            self.connected_to_internet = False

    def _check_lbrynet_connection(self):
        def _log_success():
            log.info("[" + str(datetime.now()) + "] lbrynet connectivity test passed")
        def _log_failure():
            log.info("[" + str(datetime.now()) + "] lbrynet connectivity test failed")

        wonderfullife_sh = "6f3af0fa3924be98a54766aa2715d22c6c1509c3f7fa32566df4899a41f3530a9f97b2ecb817fa1dcbf1b30553aefaa7"
        d = download_sd_blob(self.session, wonderfullife_sh, self.session.base_payment_rate_manager)
        d.addCallbacks(lambda _: _log_success, lambda _: _log_failure)

    def _check_remote_versions(self):
        def _get_lbryum_version():
            try:
                r = urlopen("https://raw.githubusercontent.com/lbryio/lbryum/master/lib/version.py").read().split('\n')
                version = next(line.split("=")[1].split("#")[0].replace(" ", "")
                               for line in r if "ELECTRUM_VERSION" in line)
                version = version.replace("'", "")
                log.info("remote lbryum " + str(version) + " > local lbryum " + str(lbryum_version) + " = " + str(
                    version > lbryum_version))
                self.git_lbryum_version = version
                return defer.succeed(None)
            except:
                log.info("[" + str(datetime.now()) + "] Failed to get lbryum version from git")
                self.git_lbryum_version = None
                return defer.fail(None)

        def _get_lbrynet_version():
            try:
                r = urlopen("https://raw.githubusercontent.com/lbryio/lbry/master/lbrynet/__init__.py").read().split('\n')
                vs = next(i for i in r if 'version =' in i).split("=")[1].replace(" ", "")
                vt = tuple(int(x) for x in vs[1:-1].split(','))
                vr = ".".join([str(x) for x in vt])
                log.info("remote lbrynet " + str(vr) + " > local lbrynet " + str(lbrynet_version) + " = " + str(
                    vr > lbrynet_version))
                self.git_lbrynet_version = vr
                return defer.succeed(None)
            except:
                log.info("[" + str(datetime.now()) + "] Failed to get lbrynet version from git")
                self.git_lbrynet_version = None
                return defer.fail(None)

        d = _get_lbrynet_version()
        d.addCallback(lambda _: _get_lbryum_version())

    def _check_connection_problems(self):
        if not self.git_lbrynet_version or not self.git_lbryum_version:
            self.connection_problem = CONNECTION_PROBLEM_CODES[0]

        elif self.startup_status[0] == 'loading_wallet':
            if self.session.wallet.is_lagging:
                self.connection_problem = CONNECTION_PROBLEM_CODES[2]
        else:
            self.connection_problem = None

        if not self.connected_to_internet:
            self.connection_problem = CONNECTION_PROBLEM_CODES[1]

    def _start_server(self):
        if self.peer_port is not None:

            server_factory = ServerProtocolFactory(self.session.rate_limiter,
                                                   self.query_handlers,
                                                   self.session.peer_manager)
            try:
                self.lbry_server_port = reactor.listenTCP(self.peer_port, server_factory)
            except error.CannotListenError as e:
                import traceback
                log.error("Couldn't bind to port %d. %s", self.peer_port, traceback.format_exc())
                raise ValueError("%s lbrynet may already be running on your computer.", str(e))
        return defer.succeed(True)

    def _stop_server(self):
        if self.lbry_server_port is not None:
            self.lbry_server_port, p = None, self.lbry_server_port
            return defer.maybeDeferred(p.stopListening)
        else:
            return defer.succeed(True)

    def _setup_server(self):
        def restore_running_status(running):
            if running is True:
                return self._start_server()
            return defer.succeed(True)

        self.startup_status = STARTUP_STAGES[4]

        dl = self.settings.get_server_running_status()
        dl.addCallback(restore_running_status)
        return dl

    def _setup_query_handlers(self):
        handlers = [
            # CryptBlobInfoQueryHandlerFactory(self.lbry_file_metadata_manager, self.session.wallet,
            #                                 self._server_payment_rate_manager),
            BlobAvailabilityHandlerFactory(self.session.blob_manager),
            # BlobRequestHandlerFactory(self.session.blob_manager, self.session.wallet,
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
        dl.addCallback(lambda _: self._add_query_handlers(handlers))
        return dl

    def _add_query_handlers(self, query_handlers):
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

    def _upload_log(self, name_prefix=None, exclude_previous=False, force=False):
        if name_prefix:
            name_prefix = name_prefix + "-" + platform.system()
        else:
            name_prefix = platform.system()

        if self.upload_log or force:
            LOG_URL = "https://lbry.io/log-upload"
            if exclude_previous:
                f = open(self.log_file, "r")
                f.seek(PREVIOUS_LOG)
                log_contents = f.read()
                f.close()
            else:
                f = open(self.log_file, "r")
                log_contents = f.read()
                f.close()
            t = datetime.now()
            log_name = name_prefix + "-" + base58.b58encode(self.lbryid)[:20] + "-" + str(t.month) + "-" + str(t.day) + "-" + str(t.year) + "-" + str(t.hour) + "-" + str(t.minute)
            params = {'name': log_name, 'log': log_contents}

            requests.post(LOG_URL, params)
            return defer.succeed(None)
        else:
            return defer.succeed(None)

    def _shutdown(self):
        log.info("Closing lbrynet session")
        log.info("Status at time of shutdown: " + self.startup_status[0])

        d = self._upload_log(name_prefix="close", exclude_previous=False if self.first_run else True)
        d.addCallback(lambda _: self._stop_server())
        d.addErrback(lambda err: log.info("Bad server shutdown: " + err.getTraceback()))
        if self.session is not None:
            d.addCallback(lambda _: self.session.shut_down())
            d.addErrback(lambda err: log.info("Bad session shutdown: " + err.getTraceback()))
        return d

    def _update_settings(self, settings):
        for k in settings.keys():
            if k == 'run_on_startup':
                if type(settings['run_on_startup']) is bool:
                    self.session_settings['run_on_startup'] = settings['run_on_startup']
                else:
                    return defer.fail()
            elif k == 'data_rate':
                if type(settings['data_rate']) is float:
                    self.session_settings['data_rate'] = settings['data_rate']
                elif type(settings['data_rate']) is int:
                    self.session_settings['data_rate'] = float(settings['data_rate'])
                else:
                    return defer.fail()
            elif k == 'max_key_fee':
                if type(settings['max_key_fee']) is float:
                    self.session_settings['max_key_fee'] = settings['max_key_fee']
                elif type(settings['max_key_fee']) is int:
                    self.session_settings['max_key_fee'] = float(settings['max_key_fee'])
                else:
                    return defer.fail()
            elif k == 'download_directory':
                if type(settings['download_directory']) is unicode:
                    if os.path.isdir(settings['download_directory']):
                        self.session_settings['download_directory'] = settings['download_directory']
                    else:
                        pass
                else:
                    return defer.fail()
            elif k == 'max_upload':
                if type(settings['max_upload']) is float:
                    self.session_settings['max_upload'] = settings['max_upload']
                elif type(settings['max_upload']) is int:
                    self.session_settings['max_upload'] = float(settings['max_upload'])
                else:
                    return defer.fail()
            elif k == 'max_download':
                if type(settings['max_download']) is float:
                    self.session_settings['max_download'] = settings['max_download']
                if type(settings['max_download']) is int:
                    self.session_settings['max_download'] = float(settings['max_download'])
                else:
                    return defer.fail()
            elif k == 'upload_log':
                if type(settings['upload_log']) is bool:
                    self.session_settings['upload_log'] = settings['upload_log']
                else:
                    return defer.fail()
            elif k == 'download_timeout':
                if type(settings['download_timeout']) is int:
                    self.session_settings['download_timeout'] = settings['download_timeout']
                else:
                    return defer.fail()
            elif k == 'search_timeout':
                if type(settings['search_timeout']) is float:
                    self.session_settings['search_timeout'] = settings['search_timeout']
                else:
                    return defer.fail()
            elif k == 'cache_time':
                if type(settings['cache_time']) is int:
                    self.session_settings['cache_time'] = settings['cache_time']
                else:
                    return defer.fail()
        self.run_on_startup = self.session_settings['run_on_startup']
        self.data_rate = self.session_settings['data_rate']
        self.max_key_fee = self.session_settings['max_key_fee']
        self.download_directory = self.session_settings['download_directory']
        self.max_upload = self.session_settings['max_upload']
        self.max_download = self.session_settings['max_download']
        self.upload_log = self.session_settings['upload_log']
        self.download_timeout = self.session_settings['download_timeout']
        self.search_timeout = self.session_settings['search_timeout']
        self.cache_time = self.session_settings['cache_time']

        f = open(self.daemon_conf, "w")
        f.write(json.dumps(self.session_settings))
        f.close()

        return defer.succeed(True)

    def _setup_data_directory(self):
        self.startup_status = STARTUP_STAGES[1]
        log.info("Loading databases...")
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
            log.info("Upgrading your databases...")
            d = threads.deferToThread(dbmigrator.migrate_db, self.db_dir, old_revision, self.current_db_revision)

            def print_success(old_dirs):
                success_string = "Finished upgrading the databases. It is now safe to delete the"
                success_string += " following directories, if you feel like it. It won't make any"
                success_string += " difference.\nAnyway here they are: "
                for i, old_dir in enumerate(old_dirs):
                    success_string += old_dir
                    if i + 1 < len(old_dir):
                        success_string += ", "
                log.info(success_string)

            d.addCallback(print_success)
            return d
        return defer.succeed(True)

    def _get_settings(self):
        d = self.settings.start()
        d.addCallback(lambda _: self.settings.get_lbryid())
        d.addCallback(self._set_lbryid)
        d.addCallback(lambda _: self._get_lbrycrdd_path())
        return d

    def _set_lbryid(self, lbryid):
        if lbryid is None:
            return self._make_lbryid()
        else:
            log.info("LBRY ID: " + base58.b58encode(lbryid))
            self.lbryid = lbryid

    def _make_lbryid(self):
        self.lbryid = generate_id()
        log.info("Generated new LBRY ID: " + base58.b58encode(self.lbryid))
        d = self.settings.save_lbryid(self.lbryid)
        return d

    def _setup_lbry_file_manager(self):
        self.startup_status = STARTUP_STAGES[3]
        self.lbry_file_metadata_manager = DBLBRYFileMetadataManager(self.db_dir)
        d = self.lbry_file_metadata_manager.setup()

        def set_lbry_file_manager():
            self.lbry_file_manager = LBRYFileManager(self.session,
                                                     self.lbry_file_metadata_manager,
                                                     self.sd_identifier,
                                                     download_directory=self.download_directory)
            return self.lbry_file_manager.setup()

        d.addCallback(lambda _: set_lbry_file_manager())

        return d

    def _get_session(self):
        def get_default_data_rate():
            d = self.settings.get_default_data_payment_rate()
            d.addCallback(lambda rate: {"default_data_payment_rate": rate if rate is not None else
                                                                    MIN_BLOB_DATA_PAYMENT_RATE})
            return d

        def get_wallet():
            if self.wallet_type == "lbrycrd":
                log.info("Using lbrycrd wallet")
                lbrycrdd_path = None
                if self.start_lbrycrdd is True:
                    lbrycrdd_path = self.lbrycrdd_path
                    if not lbrycrdd_path:
                        lbrycrdd_path = self.default_lbrycrdd_path
                d = defer.succeed(LBRYcrdWallet(self.db_dir, wallet_dir=self.wallet_dir, wallet_conf=self.lbrycrd_conf,
                                                lbrycrdd_path=lbrycrdd_path))
            elif self.wallet_type == "lbryum":
                log.info("Using lbryum wallet")
                d = defer.succeed(LBRYumWallet(self.db_dir))
            elif self.wallet_type == "ptc":
                log.info("Using PTC wallet")
                d = defer.succeed(PTCWallet(self.db_dir))
            else:
                d = defer.fail()

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
            self.session = LBRYSession(results['default_data_payment_rate'], db_dir=self.db_dir, lbryid=self.lbryid,
                                       blob_dir=self.blobfile_dir, dht_node_port=self.dht_node_port,
                                       known_dht_nodes=self.known_dht_nodes, peer_port=self.peer_port,
                                       use_upnp=self.use_upnp, wallet=results['wallet'])
            self.startup_status = STARTUP_STAGES[2]

        dl = defer.DeferredList([d1, d2], fireOnOneErrback=True)
        dl.addCallback(combine_results)
        dl.addCallback(create_session)
        dl.addCallback(lambda _: self.session.setup())

        return dl

    def _check_first_run(self):
        def _set_first_run_false():
            log.info("Not first run")
            self.first_run = False
            return 0.0

        d = self.session.wallet.is_first_run()
        d.addCallback(lambda is_first_run: self._do_first_run() if is_first_run or not self.requested_first_run_credits
                                            else _set_first_run_false())
        return d

    def _do_first_run(self):
        def send_request(url, data):
            log.info("Requesting first run credits")
            r = requests.post(url, json=data)
            if r.status_code == 200:
                self.requested_first_run_credits = True
                f = open(self.daemon_conf, "w")
                f.write(json.dumps(self.session_settings))
                f.close()
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

        self.first_run = True
        d = self.session.wallet.get_new_address()
        d.addCallback(request_credits)

        return d

    def _show_first_run_result(self, credits_received):
        if credits_received != 0.0:
            points_string = locale.format_string("%.2f LBC", (round(credits_received, 2),), grouping=True)
            self.startup_message = "Thank you for testing the alpha version of LBRY! You have been given %s for free because we love you. Please hang on for a few minutes for the next block to be mined. When you refresh this page and see your credits you're ready to go!." % points_string
        else:
            self.startup_message = None

    def _get_lbrycrdd_path(self):
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

    def _setup_stream_identifier(self):
        file_saver_factory = LBRYFileSaverFactory(self.session.peer_finder, self.session.rate_limiter,
                                                  self.session.blob_manager, self.stream_info_manager,
                                                  self.session.wallet, self.download_directory)
        self.sd_identifier.add_stream_downloader_factory(LBRYFileStreamType, file_saver_factory)
        file_opener_factory = LBRYFileOpenerFactory(self.session.peer_finder, self.session.rate_limiter,
                                                    self.session.blob_manager, self.stream_info_manager,
                                                    self.session.wallet)
        self.sd_identifier.add_stream_downloader_factory(LBRYFileStreamType, file_opener_factory)
        return defer.succeed(None)

    def _setup_lbry_file_opener(self):

        downloader_factory = LBRYFileOpenerFactory(self.session.peer_finder, self.session.rate_limiter,
                                                   self.session.blob_manager, self.stream_info_manager,
                                                   self.session.wallet)
        self.sd_identifier.add_stream_downloader_factory(LBRYFileStreamType, downloader_factory)
        return defer.succeed(True)

    def _download_name(self, name, timeout=DEFAULT_TIMEOUT, download_directory=None, file_name=None, stream_info=None):
        """
        Add a lbry file to the file manager, start the download, and return the new lbry file.
        If it already exists in the file manager, return the existing lbry file
        """

        if not download_directory:
            download_directory = self.download_directory
        elif not os.path.isdir(download_directory):
            download_directory = self.download_directory

        def _remove_from_wait(r):
            del self.waiting_on[name]
            return r

        def _setup_stream(stream_info):
            if 'sources' in stream_info.keys():
                stream_hash = stream_info['sources']['lbry_sd_hash']
            else:
                stream_hash = stream_info['stream_hash']

            d = self._get_lbry_file_by_sd_hash(stream_hash)
            def _add_results(l):
                return defer.succeed((stream_info, l))
            d.addCallback(_add_results)
            return d

        def _disp_file(f):
            file_path = os.path.join(self.download_directory, f.file_name)
            log.info("[" + str(datetime.now()) + "] Already downloaded: " + str(f.sd_hash) + " --> " + file_path)
            return f

        def _get_stream(stream_info):
            self.streams[name] = GetStream(self.sd_identifier, self.session, self.session.wallet,
                                           self.lbry_file_manager, max_key_fee=self.max_key_fee,
                                           data_rate=self.data_rate, timeout=timeout,
                                           download_directory=download_directory, file_name=file_name)
            d = self.streams[name].start(stream_info, name)
            d.addCallback(lambda _: self.streams[name].downloader)

            return d

        if not stream_info:
            self.waiting_on[name] = True
            d = self._resolve_name(name)
        else:
            d = defer.succeed(stream_info)
        d.addCallback(_setup_stream)
        d.addCallback(lambda (stream_info, lbry_file): _get_stream(stream_info) if not lbry_file else _disp_file(lbry_file))
        if not stream_info:
            d.addCallback(_remove_from_wait)

        return d

    def _get_long_count_timestamp(self):
        return int((datetime.utcnow() - (datetime(year=2012, month=12, day=21))).total_seconds())

    def _update_claim_cache(self):
        f = open(os.path.join(self.db_dir, "stream_info_cache.json"), "w")
        f.write(json.dumps(self.name_cache))
        f.close()
        return defer.succeed(True)

    def _resolve_name(self, name):
        def _cache_stream_info(stream_info):
            self.name_cache[name] = {'claim_metadata': stream_info, 'timestamp': self._get_long_count_timestamp()}
            d = self._update_claim_cache()
            d.addCallback(lambda _: self.name_cache[name]['claim_metadata'])
            return d

        if name in self.name_cache.keys():
            if (self._get_long_count_timestamp() - self.name_cache[name]['timestamp']) < self.cache_time:
                log.info("[" + str(datetime.now()) + "] Returning cached stream info for lbry://" + name)
                d = defer.succeed(self.name_cache[name]['claim_metadata'])
            else:
                log.info("[" + str(datetime.now()) + "] Refreshing stream info for lbry://" + name)
                d = self.session.wallet.get_stream_info_for_name(name)
                d.addCallbacks(_cache_stream_info, lambda _: defer.fail(UnknownNameError))
        else:
            log.info("[" + str(datetime.now()) + "] Resolving stream info for lbry://" + name)
            d = self.session.wallet.get_stream_info_for_name(name)
            d.addCallbacks(_cache_stream_info, lambda _: defer.fail(UnknownNameError))

        return d

    def _delete_lbry_file(self, lbry_file):
        d = self.lbry_file_manager.delete_lbry_file(lbry_file)

        def finish_deletion(lbry_file):
            d = lbry_file.delete_data()
            d.addCallback(lambda _: _delete_stream_data(lbry_file))
            return d

        def _delete_stream_data(lbry_file):
            s_h = lbry_file.stream_hash
            d = self.lbry_file_manager.get_count_for_stream_hash(s_h)
            # TODO: could possibly be a timing issue here
            d.addCallback(lambda c: self.stream_info_manager.delete_stream(s_h) if c == 0 else True)
            d.addCallback(lambda _: os.remove(os.path.join(self.download_directory, lbry_file.file_name)) if
                          os.path.isfile(os.path.join(self.download_directory, lbry_file.file_name)) else defer.succeed(None))
            return d

        d.addCallback(lambda _: finish_deletion(lbry_file))
        d.addCallback(lambda _: log.info("[" + str(datetime.now()) + "] Delete lbry file"))
        return d

    def _get_est_cost(self, name):
        def _check_est(d, name):
            if isinstance(d.result, float):
                log.info("[" + str(datetime.now()) + "] Cost est for lbry://" + name + ": " + str(d.result) + "LBC")
            else:
                log.info("[" + str(datetime.now()) + "] Timeout estimating cost for lbry://" + name + ", using key fee")
                d.cancel()
            return defer.succeed(None)

        def _add_key_fee(data_cost):
            d = self._resolve_name(name)
            d.addCallback(lambda info: data_cost + info['key_fee'] if 'key_fee' in info.keys() else data_cost)
            return d

        d = self._resolve_name(name)
        d.addCallback(lambda info: info['stream_hash'] if isinstance(info['stream_hash'], str)
                                    else info['stream_hash']['sd_hash'])
        d.addCallback(lambda sd_hash: download_sd_blob(self.session, sd_hash,
                                                    self.blob_request_payment_rate_manager))
        d.addCallback(self.sd_identifier.get_metadata_for_sd_blob)
        d.addCallback(lambda metadata: metadata.validator.info_to_show())
        d.addCallback(lambda info: int(dict(info)['stream_size']) / 1000000 * self.data_rate)
        d.addCallback(_add_key_fee)
        d.addErrback(lambda _: _add_key_fee(0.0))
        reactor.callLater(self.search_timeout, _check_est, d, name)

        return d

    def _get_lbry_file_by_uri(self, name):
        def _get_file(stream_info):
            if isinstance(stream_info['stream_hash'], str) or isinstance(stream_info['stream_hash'], unicode):
                sd = stream_info['stream_hash']
            elif isinstance(stream_info['stream_hash'], dict):
                sd = stream_info['stream_hash']['sd_hash']

            for l in self.lbry_file_manager.lbry_files:
                if l.sd_hash == sd:
                    return defer.succeed(l)
            return defer.succeed(None)

        d = self._resolve_name(name)
        d.addCallback(_get_file)

        return d

    def _get_lbry_file_by_sd_hash(self, sd_hash):
        for l in self.lbry_file_manager.lbry_files:
            if l.sd_hash == sd_hash:
                return defer.succeed(l)
        return defer.succeed(None)

    def _get_lbry_file_by_file_name(self, file_name):
        for l in self.lbry_file_manager.lbry_files:
            if l.file_name == file_name:
                return defer.succeed(l)
        return defer.succeed(None)

    def _get_lbry_file(self, search_by, val, return_json=True):
        def _log_get_lbry_file(f):
            if f and val:
                log.info("Found LBRY file for " + search_by + ": " + val)
            elif val:
                log.info("Did not find LBRY file for " + search_by + ": " + val)
            return f

        def _get_json_for_return(f):
            def _get_file_status(file_status):
                message = STREAM_STAGES[2][1] % (file_status.name, file_status.num_completed, file_status.num_known, file_status.running_status)
                return defer.succeed(message)

            def _generate_reply(size):
                if f.key:
                    key = binascii.b2a_hex(f.key)
                else:
                    key = None

                if os.path.isfile(os.path.join(self.download_directory, f.file_name)):
                    written_file = file(os.path.join(self.download_directory, f.file_name))
                    written_file.seek(0, os.SEEK_END)
                    written_bytes = written_file.tell()
                    written_file.close()
                else:
                    written_bytes = False

                if search_by == "name":
                    if val in self.streams.keys():
                        status = self.streams[val].code
                    elif f in self.lbry_file_manager.lbry_files:
                        # if f.stopped:
                        #     status = STREAM_STAGES[3]
                        # else:
                        status = STREAM_STAGES[2]
                    else:
                        status = [False, False]
                else:
                    status = [False, False]

                if status[0] == DOWNLOAD_RUNNING_CODE:
                    d = f.status()
                    d.addCallback(_get_file_status)
                    d.addCallback(lambda message: {'completed': f.completed, 'file_name': f.file_name, 'key': key,
                                                   'points_paid': f.points_paid, 'stopped': f.stopped,
                                                   'stream_hash': f.stream_hash,
                                                   'stream_name': f.stream_name,
                                                   'suggested_file_name': f.suggested_file_name,
                                                   'upload_allowed': f.upload_allowed, 'sd_hash': f.sd_hash,
                                                   'total_bytes': size,
                                                   'written_bytes': written_bytes, 'code': status[0],
                                                   'message': message})
                else:
                    d = defer.succeed({'completed': f.completed, 'file_name': f.file_name, 'key': key,
                                       'points_paid': f.points_paid, 'stopped': f.stopped, 'stream_hash': f.stream_hash,
                                       'stream_name': f.stream_name, 'suggested_file_name': f.suggested_file_name,
                                       'upload_allowed': f.upload_allowed, 'sd_hash': f.sd_hash, 'total_bytes': size,
                                       'written_bytes': written_bytes, 'code': status[0], 'message': status[1]})

                return d

            if f:
                d = f.get_total_bytes()
                d.addCallback(_generate_reply)
                return d
            else:
                return False

        if search_by == "name":
            d = self._get_lbry_file_by_uri(val)
        elif search_by == "sd_hash":
            d = self._get_lbry_file_by_sd_hash(val)
        elif search_by == "file_name":
            d = self._get_lbry_file_by_file_name(val)
        d.addCallback(_log_get_lbry_file)
        if return_json:
            d.addCallback(_get_json_for_return)
        return d

    def _get_lbry_files(self):
        d = defer.DeferredList([self._get_lbry_file('sd_hash', l.sd_hash) for l in self.lbry_file_manager.lbry_files])
        return d

    def _log_to_slack(self, msg):
        URL = "https://hooks.slack.com/services/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"
        msg = platform.platform() + ": " + base58.b58encode(self.lbryid)[:20] + ", " + msg
        requests.post(URL, json.dumps({"text": msg}))
        return defer.succeed(None)

    def _render_response(self, result, code):
        return defer.succeed({'result': result, 'code': code})

    def jsonrpc_is_running(self):
        """
        Check if lbrynet daemon is running

        Args:
            None
        Returns: true if daemon completed startup, otherwise false
        """

        log.info("[" + str(datetime.now()) + "] is_running: " + str(self.announced_startup))

        if self.announced_startup:
            return self._render_response(True, OK_CODE)
        else:
            return self._render_response(False, OK_CODE)

    def jsonrpc_daemon_status(self):
        """
        Get lbrynet daemon status information

        Args:
            None
        Returns:
            'message': startup status message
            'code': status_code
            'progress': progress, only used in loading_wallet
            'is_lagging': flag set to indicate lag, if set message will contain relevant message
        """

        r = {'code': self.startup_status[0], 'message': self.startup_status[1],
             'progress': None, 'is_lagging': None, 'problem_code': None}

        if self.connection_problem:
            r['problem_code'] = self.connection_problem[0]
            r['message'] = self.connection_problem[1]
            r['is_lagging'] = True
        elif self.startup_status[0] == LOADING_WALLET_CODE:
            if self.session.wallet.blocks_behind_alert != 0:
                r['message'] = r['message'] % (str(self.session.wallet.blocks_behind_alert) + " blocks behind")
                r['progress'] = self.session.wallet.catchup_progress
            else:
                r['message'] = "Catching up with the blockchain"
                r['progress'] = 0
        log.info("[" + str(datetime.now()) + "] daemon status: " + str(r))
        return self._render_response(r, OK_CODE)

    def jsonrpc_is_first_run(self):
        """
        Check if this is the first time lbrynet daemon has been run

        Args:
            None
        Returns:
            True if first run, otherwise False
        """

        log.info("[" + str(datetime.now()) + "] Check if is first run")
        try:
            d = self.session.wallet.is_first_run()
        except:
            d = defer.fail(None)

        d.addCallbacks(lambda r: self._render_response(r, OK_CODE), lambda _: self._render_response(None, OK_CODE))

        return d

    def jsonrpc_get_start_notice(self):
        """
        Get special message to be displayed at startup

        Args:
            None
        Returns:
            Startup message, such as first run notification
        """

        log.info("[" + str(datetime.now()) + "] Get startup notice")

        if self.first_run and not self.session.wallet.wallet_balance:
            return self._render_response(self.startup_message, OK_CODE)
        elif self.first_run:
            return self._render_response(None, OK_CODE)
        else:
            self._render_response(self.startup_message, OK_CODE)

    def jsonrpc_version(self):
        """
        Get lbry version information

        Args:
            None
        Returns:
            "platform": platform string
            "os_release": os release string
            "os_system": os name
            "lbrynet_version: ": lbrynet_version,
            "lbryum_version: ": lbryum_version,
            "ui_version": commit hash of ui version being used
            "remote_lbrynet": most recent lbrynet version available from github
            "remote_lbryum": most recent lbryum version available from github
        """

        msg = {
            'platform': self.platform_info['platform'],
            'os_release': self.platform_info['os_release'],
            'os_system': self.platform_info['os_system'],
            'lbrynet_version': lbrynet_version,
            'lbryum_version': lbryum_version,
            'ui_version': self.ui_version,
            'remote_lbrynet': self.git_lbrynet_version,
            'remote_lbryum': self.git_lbryum_version
        }

        log.info("[" + str(datetime.now()) + "] Get version info: " + json.dumps(msg))
        return self._render_response(msg, OK_CODE)

    def jsonrpc_get_settings(self):
        """
        Get lbrynet daemon settings

        Args:
            None
        Returns:
            'run_on_startup': bool,
            'data_rate': float,
            'max_key_fee': float,
            'download_directory': string,
            'max_upload': float, 0.0 for unlimited
            'max_download': float, 0.0 for unlimited
            'upload_log': bool,
            'search_timeout': float,
            'download_timeout': int
            'max_search_results': int,
            'wallet_type': string,
            'delete_blobs_on_remove': bool,
            'peer_port': int,
            'dht_node_port': int,
            'use_upnp': bool,
            'start_lbrycrdd': bool,
        """

        log.info("[" + str(datetime.now()) + "] Get daemon settings")
        return self._render_response(self.session_settings, OK_CODE)

    def jsonrpc_set_settings(self, p):
        """
        Set lbrynet daemon settings

        Args:
            'run_on_startup': bool,
            'data_rate': float,
            'max_key_fee': float,
            'download_directory': string,
            'max_upload': float, 0.0 for unlimited
            'max_download': float, 0.0 for unlimited
            'upload_log': bool,
            'download_timeout': int
        Returns:
            settings dict
        """

        def _log_settings_change():
            log.info("[" + str(datetime.now()) + "] Set daemon settings to " + json.dumps(self.session_settings))

        d = self._update_settings(p)
        d.addCallback(lambda _: _log_settings_change())
        d.addCallback(lambda _: self._render_response(self.session_settings, OK_CODE))

        return d

    def jsonrpc_help(self, p=None):
        """
        Function to retrieve docstring for API function

        Args:
            optional 'function': function to retrieve documentation for
            optional 'callable_during_startup':
        Returns:
            if given a function, returns given documentation
            if given callable_during_startup flag, returns list of functions callable during the startup sequence
            if no params are given, returns the list of callable functions
        """

        if not p:
            return self._render_response(self._listFunctions(), OK_CODE)
        elif 'callable_during_start' in p.keys():
            return self._render_response(ALLOWED_DURING_STARTUP, OK_CODE)
        elif 'function' in p.keys():
            func_path = p['function']
            function = self._getFunction(func_path)
            return self._render_response(function.__doc__, OK_CODE)
        else:
            return self._render_response(self.jsonrpc_help.__doc__, OK_CODE)

    def jsonrpc_get_balance(self):
        """
        Get balance

        Args:
            None
        Returns:
            balance, float
        """

        log.info("[" + str(datetime.now()) + "] Get balance")
        return self._render_response(float(self.session.wallet.wallet_balance), OK_CODE)

    def jsonrpc_stop(self):
        """
        Stop lbrynet-daemon

        Args:
            None
        Returns:
            shutdown message
        """

        def _disp_shutdown():
            log.info("Shutting down lbrynet daemon")

        d = self._shutdown()
        d.addCallback(lambda _: _disp_shutdown())
        d.addCallback(lambda _: reactor.callLater(0.0, reactor.stop))

        return self._render_response("Shutting down", OK_CODE)

    def jsonrpc_get_lbry_files(self):
        """
        Get LBRY files

        Args:
            None
        Returns:
            List of lbry files:
            'completed': bool
            'file_name': string
            'key': hex string
            'points_paid': float
            'stopped': bool
            'stream_hash': base 58 string
            'stream_name': string
            'suggested_file_name': string
            'upload_allowed': bool
            'sd_hash': string
        """

        d = self._get_lbry_files()
        d.addCallback(lambda r: [d[1] for d in r])
        d.addCallback(lambda r: self._render_response(r, OK_CODE) if len(r) else self._render_response(False, OK_CODE))

        return d

    def jsonrpc_get_lbry_file(self, p):
        """
        Get lbry file

        Args:
            'name': get file by lbry uri,
            'sd_hash': get file by the hash in the name claim,
            'file_name': get file by its name in the downloads folder,
        Returns:
            'completed': bool
            'file_name': string
            'key': hex string
            'points_paid': float
            'stopped': bool
            'stream_hash': base 58 string
            'stream_name': string
            'suggested_file_name': string
            'upload_allowed': bool
            'sd_hash': string
        """

        if p.keys()[0] in ['name', 'sd_hash', 'file_name']:
            search_type = p.keys()[0]
            d = self._get_lbry_file(search_type, p[search_type])
        else:
            d = defer.fail()
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def jsonrpc_resolve_name(self, p):
        """
        Resolve stream info from a LBRY uri

        Args:
            'name': name to look up, string, do not include lbry:// prefix
        Returns:
            metadata from name claim
        """

        if 'name' in p.keys():
            name = p['name']
        else:
            return self._render_response(None, BAD_REQUEST)

        d = self._resolve_name(name)
        d.addCallbacks(lambda info: self._render_response(info, OK_CODE), lambda _: server.failure)
        return d

    def jsonrpc_get(self, p):
        """
        Download stream from a LBRY uri

        Args:
            'name': name to download, string
            'download_directory': optional, path to directory where file will be saved, string
            'file_name': optional, a user specified name for the downloaded file
            'stream_info': optional, specified stream info overrides name
        Returns:
            'stream_hash': hex string
            'path': path of download
        """

        if 'timeout' not in p.keys():
            timeout = self.download_timeout
        else:
            timeout = p['timeout']

        if 'download_directory' not in p.keys():
            download_directory = self.download_directory
        else:
            download_directory = p['download_directory']

        if 'file_name' in p.keys():
            file_name = p['file_name']
        else:
            file_name = None

        if 'stream_info' in p.keys():
            stream_info = p['stream_info']
            if 'sources' in stream_info.keys():
                sd_hash = stream_info['sources']['lbry_sd_hash']
            else:
                sd_hash = stream_info['stream_hash']
        else:
            stream_info = None

        if 'name' in p.keys():
            name = p['name']
            if p['name'] not in self.waiting_on.keys():
                d = self._download_name(name=name, timeout=timeout, download_directory=download_directory,
                                                                stream_info=stream_info, file_name=file_name)
                d.addCallback(lambda l: {'stream_hash': sd_hash,
                                         'path': os.path.join(self.download_directory, l.file_name)}
                                         if stream_info else
                                         {'stream_hash': l.sd_hash,
                                         'path': os.path.join(self.download_directory, l.file_name)})
                d.addCallback(lambda message: self._render_response(message, OK_CODE))
            else:
                d = server.failure
        else:
            d = server.failure

        return d

    def jsonrpc_stop_lbry_file(self, p):
        """
        Stop lbry file

        Args:
            'name': stop file by lbry uri,
            'sd_hash': stop file by the hash in the name claim,
            'file_name': stop file by its name in the downloads folder,
        Returns:
            confirmation message
        """

        def _stop_file(f):
            d =  self.lbry_file_manager.toggle_lbry_file_running(f)
            d.addCallback(lambda _: "Stopped LBRY file")
            return d

        if p.keys()[0] in ['name', 'sd_hash', 'file_name']:
            search_type = p.keys()[0]
            d = self._get_lbry_file(search_type, p[search_type], return_json=False)
            d.addCallback(lambda l: _stop_file(l) if not l.stopped else "LBRY file wasn't running")

        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def jsonrpc_start_lbry_file(self, p):
        """
        Stop lbry file

        Args:
            'name': stop file by lbry uri,
            'sd_hash': stop file by the hash in the name claim,
            'file_name': stop file by its name in the downloads folder,
        Returns:
            confirmation message
        """

        def _start_file(f):
            d = self.lbry_file_manager.toggle_lbry_file_running(f)
            return defer.succeed("Started LBRY file")

        if p.keys()[0] in ['name', 'sd_hash', 'file_name']:
            search_type = p.keys()[0]
            d = self._get_lbry_file(search_type, p[search_type], return_json=False)
            d.addCallback(lambda l: _start_file(l) if l.stopped else "LBRY file was already running")

        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def jsonrpc_search_nametrie(self, p):
        """
        Search the nametrie for claims beginning with search (yes, this is a dumb search, it'll be made better)

        Args:
            'search': search query, string
        Returns:
            List of search results
        """

        if 'search' in p.keys():
            search = p['search']
        else:
            return self._render_response(None, BAD_REQUEST)

        def _clean(n):
            t = []
            for i in n:
                if i[0]:
                    if i[1][0][0] and i[1][1][0] and i[1][2][0]:
                        i[1][0][1]['value'] = str(i[1][0][1]['value'])
                        t.append([i[1][0][1], i[1][1][1], i[1][2][1]])
            return t

        def resolve_claims(claims):
            ds = []
            for claim in claims:
                d1 = defer.succeed(claim)
                d2 = self._resolve_name(claim['name'])
                d3 = self._get_est_cost(claim['name'])
                dl = defer.DeferredList([d1, d2, d3], consumeErrors=True)
                ds.append(dl)
            return defer.DeferredList(ds)

        def _disp(results):
            log.info('[' + str(datetime.now()) + '] Found ' + str(len(results)) + ' search results')
            consolidated_results = []
            for r in results:
                t = {}
                t.update(r[0])
                if 'name' in r[1].keys():
                    r[1]['stream_name'] = r[1]['name']
                    del r[1]['name']
                t.update(r[1])
                t['cost_est'] = r[2]
                if not 'thumbnail' in t.keys():
                    t['thumbnail'] = "img/Free-speech-flag.svg"
                consolidated_results.append(t)
                # log.info(str(t))
            return consolidated_results

        log.info('[' + str(datetime.now()) + '] Search nametrie: ' + search)

        d = self.session.wallet.get_nametrie()
        d.addCallback(lambda trie: [claim for claim in trie if claim['name'].startswith(search) and 'txid' in claim])
        d.addCallback(lambda claims: claims[:self.max_search_results])
        d.addCallback(resolve_claims)
        d.addCallback(_clean)
        d.addCallback(_disp)
        d.addCallback(lambda results: self._render_response(results, OK_CODE))

        return d

    def jsonrpc_delete_lbry_file(self, p):
        """
        Delete a lbry file

        Args:
            'file_name': downloaded file name, string
        Returns:
            confirmation message
        """

        def _delete_file(f):
            file_name = f.file_name
            d = self._delete_lbry_file(f)
            d.addCallback(lambda _: "Deleted LBRY file" + file_name)
            return d

        if p.keys()[0] in ['name', 'sd_hash', 'file_name']:
            search_type = p.keys()[0]
            d = self._get_lbry_file(search_type, p[search_type], return_json=False)
            d.addCallback(lambda l: _delete_file(l) if l else False)

        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def jsonrpc_publish(self, p):
        """
        Make a new name claim

        Args:
            'name': name to be claimed, string
            'file_path': path to file to be associated with name, string
            'bid': amount of credits to commit in this claim, float
            optional 'author': author, string
            optional 'title': title, description
            optional 'description': content description, string
            optional 'thumbnail': thumbnail image url
            optional 'key_fee': key fee to be paid to publisher, float (default 0.0)
            optional 'key_fee_address': address for key fee to be sent to, string (defaults on new address)
            optional 'content_license': content license string
            optional 'sources': alternative sources dict, keys 'lbry_sd_hash', 'btih', 'url'
        Returns:
            Confirmation message
        """

        metadata_fields = ["name", "file_path", "bid", "author", "title",
                           "description", "thumbnail", "key_fee", "key_fee_address",
                           "content_license", "sources"]

        for k in metadata_fields:
            if k not in p.keys():
                p[k] = None

        pub = Publisher(self.session, self.lbry_file_manager, self.session.wallet)

        d = pub.start(p['name'],
                      p['file_path'],
                      p['bid'],
                      title=p['title'],
                      description=p['description'],
                      thumbnail=p['thumbnail'],
                      key_fee=p['key_fee'],
                      key_fee_address=p['key_fee_address'],
                      content_license=p['content_license'],
                      author=p['author'],
                      sources=p['sources'])

        d.addCallbacks(lambda msg: self._render_response(msg, OK_CODE),
                       lambda err: self._render_response(err.getTraceback(), BAD_REQUEST))

        return d

    def jsonrpc_abandon_name(self, p):
        """
        Abandon a name and reclaim credits from the claim

        Args:
            'txid': txid of claim, string
        Return:
            Confirmation message
        """

        if 'txid' in p.keys():
            txid = p['txid']
        else:
            return server.failure

        def _disp(x):
            log.info("[" + str(datetime.now()) + "] Abandoned name claim tx " + str(x))
            return self._render_response(x, OK_CODE)

        d = defer.Deferred()
        d.addCallback(lambda _: self.session.wallet.abandon_name(txid))
        d.addCallback(_disp)
        d.callback(None)

        return d

    def jsonrpc_get_name_claims(self):
        """
        Get my name claims

        Args:
            None
        Returns
            list of name claims
        """

        def _clean(claims):
            for c in claims:
                for k in c.keys():
                    if isinstance(c[k], Decimal):
                        c[k] = float(c[k])
            return defer.succeed(claims)

        d = self.session.wallet.get_name_claims()
        d.addCallback(_clean)
        d.addCallback(lambda claims: self._render_response(claims, OK_CODE))

        return d

    def jsonrpc_get_transaction_history(self):
        """
        Get transaction history

        Args:
            None
        Returns:
            list of transactions
        """

        d = self.session.wallet.get_history()
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def jsonrpc_get_transaction(self, p):
        """
        Get a decoded transaction from a txid

        Args:
            txid: txid hex string
        Returns:
            JSON formatted transaction
        """


        txid = p['txid']
        d = self.session.wallet.get_tx_json(txid)
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def jsonrpc_get_public_key_from_wallet(self, p):
        """
        Get public key from wallet address

        Args:
            wallet: wallet address, base58
        Returns:
            public key
        """

        wallet = p['wallet']
        d = self.session.wallet.get_pub_keys(wallet)
        d.addCallback(lambda r: self._render_response(r, OK_CODE))

    def jsonrpc_get_time_behind_blockchain(self):
        """
        Get number of blocks behind the blockchain

        Args:
            None
        Returns:
            number of blocks behind blockchain, int
        """

        def _get_time_behind():
            try:
                local_height = self.session.wallet.network.get_local_height()
                remote_height = self.session.wallet.network.get_server_height()
                return defer.succeed(remote_height - local_height)
            except:
                return defer.fail()

        d = _get_time_behind()
        d.addCallback(lambda r: self._render_response(r, OK_CODE))

        return d

    def jsonrpc_get_new_address(self):
        """
        Generate a new wallet address

        Args:
            None
        Returns:
            new wallet address, base 58 string
        """

        def _disp(address):
            log.info("[" + str(datetime.now()) + "] Got new wallet address: " + address)
            return defer.succeed(address)

        d = self.session.wallet.get_new_address()
        d.addCallback(_disp)
        d.addCallback(lambda address: self._render_response(address, OK_CODE))
        return d

    def jsonrpc_send_amount_to_address(self, p):
        """
            Send credits to an address

            Args:
                amount: the amount to send
                address: the address of the recipient
            Returns:
                True if payment successfully scheduled
        """

        if 'amount' in p.keys() and 'address' in p.keys():
            amount = p['amount']
            address = p['address']
        else:
            return server.failure

        reserved_points = self.session.wallet.reserve_points(address, amount)
        if reserved_points is None:
            return defer.fail(InsufficientFundsError())
        d = self.session.wallet.send_points_to_address(reserved_points, amount)
        d.addCallback(lambda _: self._render_response(True, OK_CODE))
        return d

    def jsonrpc_get_best_blockhash(self):
        """
            Get hash of most recent block

            Args:
                None
            Returns:
                Hash of most recent block
        """

        d = self.session.wallet.get_best_blockhash()
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def jsonrpc_get_block(self, p):
        """
            Get contents of a block

            Args:
                blockhash: hash of the block to look up
            Returns:
                requested block
        """

        if 'blockhash' in p.keys():
            blockhash = p['blockhash']
        else:
            return server.failure

        d = self.session.wallet.get_block(blockhash)
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def jsonrpc_get_claims_for_tx(self, p):
        """
            Get claims for tx

            Args:
                txid: txid of a name claim transaction
            Returns:
                any claims contained in the requested tx
        """

        if 'txid' in p.keys():
            txid = p['txid']
        else:
            return server.failure

        d = self.session.wallet.get_claims_from_tx(txid)
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def jsonrpc_get_nametrie(self):
        """
            Get the nametrie

            Args:
                None
            Returns:
                Name claim trie
        """

        d = self.session.wallet.get_nametrie()
        d.addCallback(lambda r: [i for i in r if 'txid' in i.keys()])
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    # def jsonrpc_update_name(self, metadata):
    #     def _disp(x):
    #         print x
    #         return x
    #
    #     metadata = json.loads(metadata)
    #
    #     required = ['name', 'file_path', 'bid']
    #
    #     for r in required:
    #         if not r in metadata.keys():
    #             return defer.fail()
    #
    #     d = defer.Deferred()
    #     d.addCallback(lambda _: self.session.wallet.update_name(metadata))
    #     d.addCallback(_disp)
    #     d.callback(None)
    #
    #     return d

    def jsonrpc_check_for_new_version(self):
        """
        Checks local version against versions in __init__.py and version.py in the lbrynet and lbryum repos

        Args:
            None
        Returns:
            true/false, true meaning that there is a new version available
        """

        def _check_version():
            if (lbrynet_version >= self.git_lbrynet_version) and (lbryum_version >= self.git_lbryum_version):
                log.info("[" + str(datetime.now()) + "] Up to date")
                return self._render_response(False, OK_CODE)
            else:
                log.info("[" + str(datetime.now()) + "] Updates available")
                return self._render_response(True, OK_CODE)

        return _check_version()

    def jsonrpc_upload_log(self, p=None):
        """
        Upload log

        Args, optional:
            'name_prefix': prefix to indicate what is requesting the log upload
            'exclude_previous': true/false, whether or not to exclude previous sessions from upload, defaults on true
        Returns
            True
        """

        if p:
            if 'name_prefix' in p.keys():
                prefix = p['name_prefix'] + '_api'
            else:
                prefix = None

            if 'exclude_previous' in p.keys():
                exclude_previous = p['exclude_previous']
            else:
                exclude_previous = True

            if 'message' in p.keys():
                log.info("[" + str(datetime.now()) + "] Upload log message: " + str(p['message']))

            if 'force' in p.keys():
                force = p['force']
            else:
                force = False
        else:
            prefix = "api"
            exclude_previous = True

        d = self._upload_log(name_prefix=prefix, exclude_previous=exclude_previous, force=force)
        if 'message' in p.keys():
            d.addCallback(lambda _: self._log_to_slack(p['message']))
        d.addCallback(lambda _: self._render_response(True, OK_CODE))
        return d
