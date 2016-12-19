import binascii
import logging.handlers
import mimetypes
import os
import random
import re
import subprocess
import sys
import base58
import requests
import simplejson as json
from urllib2 import urlopen
from datetime import datetime
from decimal import Decimal

from twisted.web import server
from twisted.internet import defer, threads, error, reactor, task
from twisted.internet.task import LoopingCall
from twisted.python.failure import Failure
from jsonschema import ValidationError

# TODO: importing this when internet is disabled raises a socket.gaierror
from lbryum.version import LBRYUM_VERSION as lbryum_version
from lbrynet import __version__ as lbrynet_version
from lbrynet import conf, reflector, analytics
from lbrynet.conf import LBRYCRD_WALLET, LBRYUM_WALLET, PTC_WALLET
from lbrynet.metadata.Fee import FeeValidator
from lbrynet.metadata.Metadata import Metadata, verify_name_characters
from lbrynet.lbryfile.client.EncryptedFileDownloader import EncryptedFileSaverFactory
from lbrynet.lbryfile.client.EncryptedFileDownloader import EncryptedFileOpenerFactory
from lbrynet.lbryfile.client.EncryptedFileOptions import add_lbry_file_to_sd_identifier
from lbrynet.lbryfile.EncryptedFileMetadataManager import DBEncryptedFileMetadataManager
from lbrynet.lbryfile.EncryptedFileMetadataManager import TempEncryptedFileMetadataManager
from lbrynet.lbryfile.StreamDescriptor import EncryptedFileStreamType
from lbrynet.lbryfilemanager.EncryptedFileManager import EncryptedFileManager
from lbrynet.lbrynet_daemon.UIManager import UIManager
from lbrynet.lbrynet_daemon.Downloader import GetStream
from lbrynet.lbrynet_daemon.Publisher import Publisher
from lbrynet.lbrynet_daemon.ExchangeRateManager import ExchangeRateManager
from lbrynet.lbrynet_daemon.auth.server import AuthJSONRPCServer
from lbrynet.core import log_support, utils
from lbrynet.core import system_info
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier, download_sd_blob
from lbrynet.core.StreamDescriptor import BlobStreamDescriptorReader
from lbrynet.core.Session import Session
from lbrynet.core.Wallet import LBRYumWallet
from lbrynet.core.looping_call_manager import LoopingCallManager
from lbrynet.core.server.BlobRequestHandler import BlobRequestHandlerFactory
from lbrynet.core.server.ServerProtocol import ServerProtocolFactory
from lbrynet.core.Error import InsufficientFundsError


log = logging.getLogger(__name__)


INITIALIZING_CODE = 'initializing'
LOADING_DB_CODE = 'loading_db'
LOADING_wallet_CODE = 'loading_wallet'
LOADING_FILE_MANAGER_CODE = 'loading_file_manager'
LOADING_SERVER_CODE = 'loading_server'
STARTED_CODE = 'started'
WAITING_FOR_FIRST_RUN_CREDITS = 'waiting_for_credits'
STARTUP_STAGES = [
                    (INITIALIZING_CODE, 'Initializing...'),
                    (LOADING_DB_CODE, 'Loading databases...'),
                    (LOADING_wallet_CODE, 'Catching up with the blockchain... %s'),
                    (LOADING_FILE_MANAGER_CODE, 'Setting up file manager'),
                    (LOADING_SERVER_CODE, 'Starting lbrynet'),
                    (STARTED_CODE, 'Started lbrynet'),
                    (WAITING_FOR_FIRST_RUN_CREDITS, 'Waiting for first run credits...')
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
CONNECT_CODE_wallet = 'wallet_catchup_lag'
CONNECTION_PROBLEM_CODES = [
        (CONNECT_CODE_VERSION_CHECK, "There was a problem checking for updates on github"),
        (CONNECT_CODE_NETWORK, "Your internet connection appears to have been interrupted"),
        (CONNECT_CODE_wallet,
         "Synchronization with the blockchain is lagging... if this continues try restarting LBRY")
        ]

BAD_REQUEST = 400
NOT_FOUND = 404
OK_CODE = 200

PENDING_ID = "not set"
SHORT_ID_LEN = 20


class Checker:
    """The looping calls the daemon runs"""
    INTERNET_CONNECTION = 'internet_connection_checker'
    VERSION = 'version_checker'
    CONNECTION_PROBLEM = 'connection_problem_checker'
    PENDING_CLAIM = 'pending_claim_checker'


class FileID:
    """The different ways a file can be identified"""
    NAME = 'name'
    SD_HASH = 'sd_hash'
    FILE_NAME = 'file_name'


# TODO add login credentials in a conf file
# TODO alert if your copy of a lbry file is out of date with the name record

REMOTE_SERVER = "www.lbry.io"


class NoValidSearch(Exception):
    pass


class Parameters(object):
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class CheckInternetConnection(object):
    def __init__(self, daemon):
        self.daemon = daemon

    def __call__(self):
        self.daemon.connected_to_internet = utils.check_connection()


class CheckRemoteVersions(object):
    def __init__(self, daemon):
        self.daemon = daemon

    def __call__(self):
        d = self._get_lbrynet_version()
        d.addCallback(lambda _: self._get_lbryum_version())

    def _get_lbryum_version(self):
        try:
            version = get_lbryum_version_from_github()
            log.info(
                "remote lbryum %s > local lbryum %s = %s",
                version, lbryum_version,
                utils.version_is_greater_than(version, lbryum_version)
            )
            self.daemon.git_lbryum_version = version
            return defer.succeed(None)
        except Exception:
            log.info("Failed to get lbryum version from git")
            self.daemon.git_lbryum_version = None
            return defer.fail(None)

    def _get_lbrynet_version(self):
        try:
            version = get_lbrynet_version_from_github()
            log.info(
                "remote lbrynet %s > local lbrynet %s = %s",
                version, lbrynet_version,
                utils.version_is_greater_than(version, lbrynet_version)
            )
            self.daemon.git_lbrynet_version = version
            return defer.succeed(None)
        except Exception:
            log.info("Failed to get lbrynet version from git")
            self.daemon.git_lbrynet_version = None
            return defer.fail(None)


class AlwaysSend(object):
    def __init__(self, value_generator, *args, **kwargs):
        self.value_generator = value_generator
        self.args = args
        self.kwargs = kwargs

    def __call__(self):
        d = defer.maybeDeferred(self.value_generator, *self.args, **self.kwargs)
        d.addCallback(lambda v: (True, v))
        return d


def calculate_available_blob_size(blob_manager):
    d = blob_manager.get_all_verified_blobs()
    d.addCallback(
        lambda blobs: defer.DeferredList([blob_manager.get_blob_length(b) for b in blobs]))
    d.addCallback(lambda blob_lengths: sum(val for success, val in blob_lengths if success))
    return d


class Daemon(AuthJSONRPCServer):
    """
    LBRYnet daemon, a jsonrpc interface to lbry functions
    """

    def __init__(self, root, analytics_manager):
        AuthJSONRPCServer.__init__(self, conf.settings.use_auth_http)
        reactor.addSystemEventTrigger('before', 'shutdown', self._shutdown)

        self.allowed_during_startup = [
            'is_running', 'is_first_run',
            'get_time_behind_blockchain', 'stop',
            'daemon_status', 'get_start_notice',
            'version'
        ]
        last_version = {'last_version': {'lbrynet': lbrynet_version, 'lbryum': lbryum_version}}
        conf.settings.update(last_version)
        self.db_dir = conf.settings.data_dir
        self.download_directory = conf.settings.download_directory
        self.created_data_dir = False
        if not os.path.exists(self.db_dir):
            os.mkdir(self.db_dir)
            self.created_data_dir = True
        if conf.settings.BLOBFILES_DIR == "blobfiles":
            self.blobfile_dir = os.path.join(self.db_dir, "blobfiles")
        else:
            log.info("Using non-default blobfiles directory: %s", conf.settings.BLOBFILES_DIR)
            self.blobfile_dir = conf.settings.BLOBFILES_DIR

        self.run_on_startup = conf.settings.run_on_startup
        self.data_rate = conf.settings.data_rate
        self.max_key_fee = conf.settings.max_key_fee
        self.max_upload = conf.settings.max_upload
        self.max_download = conf.settings.max_download
        self.upload_log = conf.settings.upload_log
        self.search_timeout = conf.settings.search_timeout
        self.download_timeout = conf.settings.download_timeout
        self.max_search_results = conf.settings.max_search_results
        self.run_reflector_server = conf.settings.run_reflector_server
        self.wallet_type = conf.settings.wallet
        self.delete_blobs_on_remove = conf.settings.delete_blobs_on_remove
        self.peer_port = conf.settings.peer_port
        self.reflector_port = conf.settings.reflector_port
        self.dht_node_port = conf.settings.dht_node_port
        self.use_upnp = conf.settings.use_upnp
        self.cache_time = conf.settings.cache_time
        self.startup_scripts = conf.settings.startup_scripts

        self.startup_status = STARTUP_STAGES[0]
        self.startup_message = None
        self.connected_to_internet = True
        self.connection_problem = None
        self.git_lbrynet_version = None
        self.git_lbryum_version = None
        self.ui_version = None
        self.platform = None
        self.first_run = None
        self.log_file = conf.settings.get_log_filename()
        self.current_db_revision = 2
        self.db_revision_file = conf.settings.get_db_revision_filename()
        self.session = None
        self.uploaded_temp_files = []
        self._session_id = base58.b58encode(utils.generate_id())
        # TODO: this should probably be passed into the daemon, or
        # possibly have the entire log upload functionality taken out
        # of the daemon, but I don't want to deal with that now
        self.log_uploader = log_support.LogUploader.load('lbrynet', self.log_file)

        self.analytics_manager = analytics_manager
        self.lbryid = PENDING_ID
        self.daemon_conf = conf.settings.get_conf_filename()

        self.wallet_user = None
        self.wallet_password = None
        self.query_handlers = {}
        self.waiting_on = {}
        self.streams = {}
        self.pending_claims = {}
        self.name_cache = {}
        self.exchange_rate_manager = ExchangeRateManager()
        calls = {
            Checker.INTERNET_CONNECTION: LoopingCall(CheckInternetConnection(self)),
            Checker.VERSION: LoopingCall(CheckRemoteVersions(self)),
            Checker.CONNECTION_PROBLEM: LoopingCall(self._check_connection_problems),
            Checker.PENDING_CLAIM: LoopingCall(self._check_pending_claims),
        }
        self.looping_call_manager = LoopingCallManager(calls)
        self.sd_identifier = StreamDescriptorIdentifier()
        self.stream_info_manager = TempEncryptedFileMetadataManager()
        self.lbry_ui_manager = UIManager(root)
        self.lbry_file_metadata_manager = None
        self.lbry_file_manager = None

    def setup(self):
        self._modify_loggly_formatter()

        def _log_starting_vals():
            log.info("Starting balance: " + str(self.session.wallet.wallet_balance))
            return defer.succeed(None)

        def _announce_startup():
            def _wait_for_credits():
                if float(self.session.wallet.wallet_balance) == 0.0:
                    self.startup_status = STARTUP_STAGES[6]
                    return reactor.callLater(1, _wait_for_credits)
                else:
                    return _announce()

            def _announce():
                self.announced_startup = True
                self.startup_status = STARTUP_STAGES[5]
                log.info("Started lbrynet-daemon")
                if len(self.startup_scripts):
                    log.info("Scheduling scripts")
                    reactor.callLater(3, self._run_scripts)

            if self.first_run:
                d = self._upload_log(log_type="first_run")
            elif self.upload_log:
                d = self._upload_log(exclude_previous=True, log_type="start")
            else:
                d = defer.succeed(None)

            d.addCallback(lambda _: _announce())
            return d

        log.info("Starting lbrynet-daemon")

        self.looping_call_manager.start(Checker.INTERNET_CONNECTION, 3600)
        self.looping_call_manager.start(Checker.VERSION, 3600 * 12)
        self.looping_call_manager.start(Checker.CONNECTION_PROBLEM, 1)
        self.exchange_rate_manager.start()

        d = defer.Deferred()
        if conf.settings.host_ui:
            self.lbry_ui_manager.update_checker.start(1800, now=False)
            d.addCallback(lambda _: self.lbry_ui_manager.setup())
        d.addCallback(lambda _: self._initial_setup())
        d.addCallback(lambda _: threads.deferToThread(self._setup_data_directory))
        d.addCallback(lambda _: self._check_db_migration())
        d.addCallback(lambda _: self._load_caches())
        d.addCallback(lambda _: self._set_events())
        d.addCallback(lambda _: self._get_session())
        d.addCallback(lambda _: self._get_analytics())
        d.addCallback(lambda _: add_lbry_file_to_sd_identifier(self.sd_identifier))
        d.addCallback(lambda _: self._setup_stream_identifier())
        d.addCallback(lambda _: self._setup_lbry_file_manager())
        d.addCallback(lambda _: self._setup_query_handlers())
        d.addCallback(lambda _: self._setup_server())
        d.addCallback(lambda _: _log_starting_vals())
        d.addCallback(lambda _: _announce_startup())
        d.callback(None)
        return d

    def _get_platform(self):
        if self.platform is None:
            self.platform = system_info.get_platform()
            self.platform["ui_version"] = self.lbry_ui_manager.loaded_git_version
        return self.platform

    def _initial_setup(self):
        def _log_platform():
            log.info("Platform: %s", json.dumps(self._get_platform()))
            return defer.succeed(None)

        d = _log_platform()
        return d

    def _load_caches(self):
        name_cache_filename = os.path.join(self.db_dir, "stream_info_cache.json")
        lbry_id_filename = os.path.join(self.db_dir, "lbry_id")

        if os.path.isfile(name_cache_filename):
            with open(name_cache_filename, "r") as name_cache:
                self.name_cache = json.loads(name_cache.read())
            log.info("Loaded claim info cache")

        if os.path.isfile(lbry_id_filename):
            with open(lbry_id_filename, "r") as lbry_id_file:
                self.lbryid = base58.b58decode(lbry_id_file.read())
        else:
            with open(lbry_id_filename, "w") as lbry_id_file:
                self.lbryid = utils.generate_id()
                lbry_id_file.write(base58.b58encode(self.lbryid))

    def _set_events(self):
        context = analytics.make_context(self._get_platform(), self.wallet_type)
        self._events = analytics.Events(context, base58.b58encode(self.lbryid), self._session_id)

    def _check_network_connection(self):
        self.connected_to_internet = utils.check_connection()

    def _check_lbrynet_connection(self):
        def _log_success():
            log.info("lbrynet connectivity test passed")
        def _log_failure():
            log.info("lbrynet connectivity test failed")

        wonderfullife_sh = ("6f3af0fa3924be98a54766aa2715d22c6c1509c3f7fa32566df4899"
                            "a41f3530a9f97b2ecb817fa1dcbf1b30553aefaa7")
        d = download_sd_blob(self.session, wonderfullife_sh, self.session.base_payment_rate_manager)
        d.addCallbacks(lambda _: _log_success, lambda _: _log_failure)

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

    # claim_out is dictionary containing 'txid' and 'nout'
    def _add_to_pending_claims(self, name, claim_out):
        txid = claim_out['txid']
        nout = claim_out['nout']
        log.info("Adding lbry://%s to pending claims, txid %s nout %d" % (name, txid, nout))
        self.pending_claims[name] = (txid, nout)
        return claim_out

    def _check_pending_claims(self):
        # TODO: this was blatantly copied from jsonrpc_start_lbry_file. Be DRY.
        def _start_file(f):
            d = self.lbry_file_manager.toggle_lbry_file_running(f)
            return defer.succeed("Started LBRY file")

        def _get_and_start_file(name):
            def start_stopped_file(l):
                if l.stopped:
                    return _start_file(l)
                else:
                    return "LBRY file was already running"
            d = defer.succeed(self.pending_claims.pop(name))
            d.addCallback(lambda _: self._get_lbry_file(FileID.NAME, name, return_json=False))
            d.addCallback(start_stopped_file)

        def re_add_to_pending_claims(name):
            log.warning("Re-add %s to pending claims", name)
            txid, nout = self.pending_claims.pop(name)
            claim_out = {'txid':txid, 'nout':nout}
            self._add_to_pending_claims(name, claim_out)

        def _process_lbry_file(name, lbry_file):
            # lbry_file is an instance of ManagedEncryptedFileDownloader or None
            # TODO: check for sd_hash in addition to txid
            ready_to_start = (
                lbry_file and
                self.pending_claims[name] == (lbry_file.txid, lbry_file.nout)
            )
            if ready_to_start:
                _get_and_start_file(name)
            else:
                re_add_to_pending_claims(name)

        for name in self.pending_claims:
            log.info("Checking if new claim for lbry://%s is confirmed" % name)
            d = self._resolve_name(name, force_refresh=True)
            d.addCallback(lambda _: self._get_lbry_file_by_uri(name))
            d.addCallbacks(
                lambda lbry_file: _process_lbry_file(name, lbry_file),
                lambda _: re_add_to_pending_claims(name)
            )

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

    def _start_reflector(self):
        if self.run_reflector_server:
            log.info("Starting reflector server")
            if self.reflector_port is not None:
                reflector_factory = reflector.ServerFactory(
                    self.session.peer_manager,
                    self.session.blob_manager
                )
                try:
                    self.reflector_server_port = reactor.listenTCP(
                        self.reflector_port, reflector_factory)
                    log.info('Started reflector on port %s', self.reflector_port)
                except error.CannotListenError as e:
                    log.exception("Couldn't bind reflector to port %d", self.reflector_port)
                    raise ValueError(
                        "{} lbrynet may already be running on your computer.".format(e))
        return defer.succeed(True)

    def _stop_reflector(self):
        if self.run_reflector_server:
            log.info("Stopping reflector server")
            try:
                if self.reflector_server_port is not None:
                    self.reflector_server_port, p = None, self.reflector_server_port
                    return defer.maybeDeferred(p.stopListening)
            except AttributeError:
                return defer.succeed(True)
        return defer.succeed(True)

    def _stop_file_manager(self):
        if self.lbry_file_manager:
            self.lbry_file_manager.stop()
        return defer.succeed(True)

    def _stop_server(self):
        try:
            if self.lbry_server_port is not None:
                self.lbry_server_port, p = None, self.lbry_server_port
                log.info('Stop listening to %s', p)
                return defer.maybeDeferred(p.stopListening)
            else:
                return defer.succeed(True)
        except AttributeError:
            return defer.succeed(True)

    def _setup_server(self):
        self.startup_status = STARTUP_STAGES[4]
        d = self._start_server()
        d.addCallback(lambda _: self._start_reflector())
        return d

    def _setup_query_handlers(self):
        handlers = [
            BlobRequestHandlerFactory(
                self.session.blob_manager,
                self.session.wallet,
                self.session.payment_rate_manager,
                self.analytics_manager.track
            ),
            self.session.wallet.get_wallet_info_query_handler_factory(),
        ]
        return self._add_query_handlers(handlers)

    def _add_query_handlers(self, query_handlers):
        for handler in query_handlers:
            query_id = handler.get_primary_query_identifier()
            self.query_handlers[query_id] = handler
        return defer.succeed(None)

    def _upload_log(self, log_type=None, exclude_previous=False, force=False):
        if self.upload_log or force:
            lbry_id = base58.b58encode(self.lbryid)[:SHORT_ID_LEN]
            try:
                self.log_uploader.upload(exclude_previous, lbry_id, log_type)
            except requests.RequestException:
                log.warning('Failed to upload log file')
        return defer.succeed(None)

    def _clean_up_temp_files(self):
        for path in self.uploaded_temp_files:
            try:
                log.debug('Removing tmp file: %s', path)
                os.remove(path)
            except OSError:
                pass

    def _shutdown(self):
        log.info("Closing lbrynet session")
        log.info("Status at time of shutdown: " + self.startup_status[0])
        self.looping_call_manager.shutdown()
        if self.analytics_manager:
            self.analytics_manager.shutdown()
        if self.lbry_ui_manager.update_checker.running:
            self.lbry_ui_manager.update_checker.stop()

        self._clean_up_temp_files()

        try:
            d = self._upload_log(
                log_type="close", exclude_previous=False if self.first_run else True)
        except Exception:
            log.warn('Failed to upload log', exc_info=True)
            d = defer.succeed(None)

        d.addCallback(lambda _: self._stop_server())
        d.addErrback(log.fail(), 'Failure while shutting down')
        d.addCallback(lambda _: self._stop_reflector())
        d.addErrback(log.fail(), 'Failure while shutting down')
        d.addCallback(lambda _: self._stop_file_manager())
        d.addErrback(log.fail(), 'Failure while shutting down')
        if self.session is not None:
            d.addCallback(lambda _: self.session.shut_down())
            d.addErrback(log.fail(), 'Failure while shutting down')
        return d

    def _update_settings(self, settings):
        setting_types = {
            'run_on_startup': bool,
            'data_rate': float,
            'max_key_fee': float,
            'download_directory': str,
            'max_upload': float,
            'max_download': float,
            'upload_log': bool,
            'download_timeout': int,
            'search_timeout': float,
            'cache_time': int
        }
        def can_update_key(settings, key, setting_type):
            return (
                isinstance(settings[key], setting_type) or
                (
                    key == "max_key_fee" and
                    isinstance(FeeValidator(settings[key]).amount, setting_type)
                )
            )

        for key, setting_type in setting_types.iteritems():
            if key in settings:
                if can_update_key(settings, key, setting_type):
                    conf.settings.update({key: settings[key]})
                else:
                    try:
                        converted = setting_type(settings[key])
                        conf.settings.update({key: converted})
                    except Exception as err:
                        log.warning(err.message)
                        log.warning("error converting setting '%s' to type %s", key, setting_type)
        conf.save_settings()

        self.run_on_startup = conf.settings.run_on_startup
        self.data_rate = conf.settings.data_rate
        self.max_key_fee = conf.settings.max_key_fee
        self.download_directory = conf.settings.download_directory
        self.max_upload = conf.settings.max_upload
        self.max_download = conf.settings.max_download
        self.upload_log = conf.settings.upload_log
        self.download_timeout = conf.settings.download_timeout
        self.search_timeout = conf.settings.search_timeout
        self.cache_time = conf.settings.cache_time

        return defer.succeed(True)

    def _write_db_revision_file(self, version_num):
        with open(self.db_revision_file, mode='w') as db_revision:
            db_revision.write(str(version_num))

    def _setup_data_directory(self):
        old_revision = 1
        self.startup_status = STARTUP_STAGES[1]
        log.info("Loading databases...")
        if self.created_data_dir:
            self._write_db_revision_file(self.current_db_revision)
            log.debug("Created the db revision file: %s", self.db_revision_file)
        if not os.path.exists(self.blobfile_dir):
            os.mkdir(self.blobfile_dir)
            log.debug("Created the blobfile directory: %s", str(self.blobfile_dir))
        if not os.path.exists(self.db_revision_file):
            log.warning("db_revision file not found. Creating it")
            self._write_db_revision_file(old_revision)

    def _check_db_migration(self):
        old_revision = 1
        if os.path.exists(self.db_revision_file):
            old_revision = int(open(self.db_revision_file).read().strip())

        if old_revision > self.current_db_revision:
            raise Exception('This version of lbrynet is not compatible with the database')

        def update_version_file_and_print_success():
            self._write_db_revision_file(self.current_db_revision)
            log.info("Finished upgrading the databases.")

        if old_revision < self.current_db_revision:
            from lbrynet.db_migrator import dbmigrator
            log.info("Upgrading your databases...")
            d = threads.deferToThread(
                dbmigrator.migrate_db, self.db_dir, old_revision, self.current_db_revision)
            d.addCallback(lambda _: update_version_file_and_print_success())
            return d
        return defer.succeed(True)

    def _modify_loggly_formatter(self):
        log_support.configure_loggly_handler(
            lbry_id=base58.b58encode(self.lbryid),
            session_id=self._session_id
        )

    def _setup_lbry_file_manager(self):
        self.startup_status = STARTUP_STAGES[3]
        self.lbry_file_metadata_manager = DBEncryptedFileMetadataManager(self.db_dir)
        d = self.lbry_file_metadata_manager.setup()

        def set_lbry_file_manager():
            self.lbry_file_manager = EncryptedFileManager(
                self.session, self.lbry_file_metadata_manager,
                self.sd_identifier, download_directory=self.download_directory)
            return self.lbry_file_manager.setup()
        d.addCallback(lambda _: set_lbry_file_manager())
        return d

    def _get_analytics(self):
        context = analytics.make_context(self._get_platform(), self.wallet_type)
        events_generator = analytics.Events(
            context, base58.b58encode(self.lbryid), self._session_id)
        if self.analytics_manager is None:
            self.analytics_manager = analytics.Manager.new_instance(
                events=events_generator
            )
        else:
            self.analytics_manager.update_events_generator(events_generator)

        if not self.analytics_manager.is_started:
            self.analytics_manager.start()
            self.analytics_manager.register_repeating_metric(
                analytics.BLOB_BYTES_AVAILABLE,
                AlwaysSend(calculate_available_blob_size, self.session.blob_manager),
                frequency=300
            )

    def _get_session(self):
        def get_wallet():
            if self.wallet_type == LBRYCRD_WALLET:
                raise ValueError('LBRYcrd Wallet is no longer supported')
            elif self.wallet_type == LBRYUM_WALLET:
                log.info("Using lbryum wallet")
                config = {'auto_connect': True}
                if conf.settings.lbryum_wallet_dir:
                    config['lbryum_path'] = conf.settings.lbryum_wallet_dir
                return defer.succeed(LBRYumWallet(self.db_dir, config))
            elif self.wallet_type == PTC_WALLET:
                log.info("Using PTC wallet")
                from lbrynet.core.PTCWallet import PTCWallet
                return defer.succeed(PTCWallet(self.db_dir))
            else:
                raise ValueError('Wallet Type {} is not valid'.format(self.wallet_type))

        d = get_wallet()

        def create_session(wallet):
            self.session = Session(
                conf.settings.data_rate,
                db_dir=self.db_dir,
                lbryid=self.lbryid,
                blob_dir=self.blobfile_dir,
                dht_node_port=self.dht_node_port,
                known_dht_nodes=conf.settings.known_dht_nodes,
                peer_port=self.peer_port,
                use_upnp=self.use_upnp,
                wallet=wallet,
                is_generous=conf.settings.is_generous_host
            )
            self.startup_status = STARTUP_STAGES[2]

        d.addCallback(create_session)
        d.addCallback(lambda _: self.session.setup())

        return d

    def _setup_stream_identifier(self):
        file_saver_factory = EncryptedFileSaverFactory(
            self.session.peer_finder,
            self.session.rate_limiter,
            self.session.blob_manager,
            self.stream_info_manager,
            self.session.wallet,
            self.download_directory
        )
        self.sd_identifier.add_stream_downloader_factory(
            EncryptedFileStreamType, file_saver_factory)
        file_opener_factory = EncryptedFileOpenerFactory(
            self.session.peer_finder,
            self.session.rate_limiter,
            self.session.blob_manager,
            self.stream_info_manager,
            self.session.wallet
        )
        self.sd_identifier.add_stream_downloader_factory(
            EncryptedFileStreamType, file_opener_factory)
        return defer.succeed(None)

    def _download_sd_blob(self, sd_hash, timeout=conf.settings.sd_download_timeout):
        def cb(result):
            if not r.called:
                r.callback(result)

        def eb():
            if not r.called:
                self.analytics_manager.send_error("sd blob download timed out", sd_hash)
                r.errback(Exception("sd timeout"))

        r = defer.Deferred(None)
        reactor.callLater(timeout, eb)
        d = download_sd_blob(self.session, sd_hash, self.session.payment_rate_manager)
        d.addErrback(lambda err: self.analytics_manager.send_error(
            "error downloading sd blob: " + err, sd_hash))
        d.addCallback(BlobStreamDescriptorReader)
        d.addCallback(lambda blob: blob.get_info())
        d.addCallback(cb)

        return r

    def _download_name(self, name, timeout=conf.settings.download_timeout, download_directory=None,
                       file_name=None, stream_info=None, wait_for_write=True):
        """
        Add a lbry file to the file manager, start the download, and return the new lbry file.
        If it already exists in the file manager, return the existing lbry file
        """
        self.analytics_manager.send_download_started(name, stream_info)
        helper = _DownloadNameHelper(
            self, name, timeout, download_directory, file_name, wait_for_write)

        if not stream_info:
            self.waiting_on[name] = True
            d = self._resolve_name(name)
        else:
            d = defer.succeed(stream_info)
        d.addCallback(helper._setup_stream)
        d.addCallback(helper.wait_or_get_stream)
        if not stream_info:
            d.addCallback(helper._remove_from_wait)
        return d

    def add_stream(self, name, timeout, download_directory, file_name, stream_info):
        """Makes, adds and starts a stream"""
        self.streams[name] = GetStream(self.sd_identifier,
                                       self.session,
                                       self.session.wallet,
                                       self.lbry_file_manager,
                                       self.exchange_rate_manager,
                                       max_key_fee=self.max_key_fee,
                                       data_rate=self.data_rate,
                                       timeout=timeout,
                                       download_directory=download_directory,
                                       file_name=file_name)
        d = self.streams[name].start(stream_info, name)
        return d

    def _get_long_count_timestamp(self):
        return int((datetime.utcnow() - (datetime(year=2012, month=12, day=21))).total_seconds())

    def _update_claim_cache(self):
        f = open(os.path.join(self.db_dir, "stream_info_cache.json"), "w")
        f.write(json.dumps(self.name_cache))
        f.close()
        return defer.succeed(True)

    def _resolve_name(self, name, force_refresh=False):
        """Resolves a name. Checks the cache first before going out to the blockchain.

        Args:
            name: the lbry://<name> to resolve
            force_refresh: if True, always go out to the blockchain to resolve.
        """
        if name.startswith('lbry://'):
            raise ValueError('name {} should not start with lbry://'.format(name))
        helper = _ResolveNameHelper(self, name, force_refresh)
        return helper.get_deferred()

    def _delete_lbry_file(self, lbry_file, delete_file=True):
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
            if delete_file:
                def remove_if_file():
                    filename = os.path.join(self.download_directory, lbry_file.file_name)
                    if os.path.isfile(filename):
                        os.remove(filename)
                    else:
                        return defer.succeed(None)
                d.addCallback(lambda _: remove_if_file)
            return d

        d.addCallback(lambda _: finish_deletion(lbry_file))
        d.addCallback(lambda _: log.info("Delete lbry file"))
        return d

    def _get_or_download_sd_blob(self, blob, sd_hash):
        if blob:
            return self.session.blob_manager.get_blob(blob[0], True)

        def _check_est(downloader):
            if downloader.result is not None:
                downloader.cancel()

        d = defer.succeed(None)
        reactor.callLater(self.search_timeout, _check_est, d)
        d.addCallback(
            lambda _: download_sd_blob(
                self.session, sd_hash, self.session.payment_rate_manager))
        return d

    def get_or_download_sd_blob(self, sd_hash):
        """Return previously downloaded sd blob if already in the blob
        manager, otherwise download and return it
        """
        d = self.session.blob_manager.completed_blobs([sd_hash])
        d.addCallback(self._get_or_download_sd_blob, sd_hash)
        return d

    def get_size_from_sd_blob(self, sd_blob):
        """
        Get total stream size in bytes from a sd blob
        """

        d = self.sd_identifier.get_metadata_for_sd_blob(sd_blob)
        d.addCallback(lambda metadata: metadata.validator.info_to_show())
        d.addCallback(lambda info: int(dict(info)['stream_size']))
        return d

    def _get_est_cost_from_stream_size(self, size):
        """
        Calculate estimated LBC cost for a stream given its size in bytes
        """

        if self.session.payment_rate_manager.generous:
            return 0.0
        return size / (10**6) * conf.settings.data_rate

    def get_est_cost_using_known_size(self, name, size):
        """
        Calculate estimated LBC cost for a stream given its size in bytes
        """

        cost = self._get_est_cost_from_stream_size(size)

        d = self._resolve_name(name)
        d.addCallback(lambda metadata: self._add_key_fee_to_est_data_cost(metadata, cost))
        return d

    def get_est_cost_from_sd_hash(self, sd_hash):
        """
        Get estimated cost from a sd hash
        """

        d = self.get_or_download_sd_blob(sd_hash)
        d.addCallback(self.get_size_from_sd_blob)
        d.addCallback(self._get_est_cost_from_stream_size)
        return d

    def _get_est_cost_from_metadata(self, metadata, name):
        d = self.get_est_cost_from_sd_hash(metadata['sources']['lbry_sd_hash'])

        def _handle_err(err):
            if isinstance(err, Failure):
                log.warning(
                    "Timeout getting blob for cost est for lbry://%s, using only key fee", name)
                return 0.0
            raise err

        d.addErrback(_handle_err)
        d.addCallback(lambda data_cost: self._add_key_fee_to_est_data_cost(metadata, data_cost))
        return d

    def _add_key_fee_to_est_data_cost(self, metadata, data_cost):
        fee = self.exchange_rate_manager.to_lbc(metadata.get('fee', None))
        fee_amount = 0.0 if fee is None else fee.amount
        return data_cost + fee_amount

    def get_est_cost_from_name(self, name):
        """
        Resolve a name and return the estimated stream cost
        """

        d = self._resolve_name(name)
        d.addCallback(self._get_est_cost_from_metadata, name)
        return d

    def get_est_cost(self, name, size=None):
        """Get a cost estimate for a lbry stream, if size is not provided the
        sd blob will be downloaded to determine the stream size

        """

        if size is not None:
            return self.get_est_cost_using_known_size(name, size)
        return self.get_est_cost_from_name(name)

    def _get_lbry_file_by_uri(self, name):
        def _get_file(stream_info):
            sd = stream_info['sources']['lbry_sd_hash']

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
        return _GetFileHelper(self, search_by, val, return_json).retrieve_file()

    def _get_lbry_files(self):
        d = defer.DeferredList([
            self._get_lbry_file(FileID.SD_HASH, l.sd_hash)
            for l in self.lbry_file_manager.lbry_files
        ])
        return d

    def _reflect(self, lbry_file):
        if not lbry_file:
            return defer.fail(Exception("no lbry file given to reflect"))
        stream_hash = lbry_file.stream_hash
        if stream_hash is None:
            return defer.fail(Exception("no stream hash"))
        log.info("Reflecting stream: %s" % stream_hash)
        factory = reflector.ClientFactory(
            self.session.blob_manager,
            self.lbry_file_manager.stream_info_manager,
            stream_hash
        )
        return run_reflector_factory(factory)

    def _reflect_blobs(self, blob_hashes):
        if not blob_hashes:
            return defer.fail(Exception("no lbry file given to reflect"))
        log.info("Reflecting %i blobs" % len(blob_hashes))
        factory = reflector.BlobClientFactory(
            self.session.blob_manager,
            blob_hashes
        )
        return run_reflector_factory(factory)

    def _run_scripts(self):
        if len([k for k in self.startup_scripts if 'run_once' in k.keys()]):
            log.info("Removing one time startup scripts")
            remaining_scripts = [s for s in self.startup_scripts if 'run_once' not in s.keys()]
            startup_scripts = self.startup_scripts
            self.startup_scripts = conf.settings.startup_scripts = remaining_scripts
            conf.save_settings()

        for script in startup_scripts:
            if script['script_name'] == 'migrateto025':
                log.info("Running migrator to 0.2.5")
                from lbrynet.lbrynet_daemon.daemon_scripts.migrateto025 import run as run_migrate
                run_migrate(self)

            if script['script_name'] == 'Autofetcher':
                log.info("Starting autofetcher script")
                from lbrynet.lbrynet_daemon.daemon_scripts.Autofetcher import run as run_autofetcher
                run_autofetcher(self)

        return defer.succeed(None)

    def jsonrpc_is_running(self):
        """
        Check if lbrynet daemon is running

        Args:
            None
        Returns: true if daemon completed startup, otherwise false
        """

        log.info("is_running: " + str(self.announced_startup))

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
        elif self.startup_status[0] == LOADING_wallet_CODE:
            if self.wallet_type == LBRYUM_WALLET:
                if self.session.wallet.blocks_behind_alert != 0:
                    r['message'] %= str(self.session.wallet.blocks_behind_alert) + " blocks behind"
                    r['progress'] = self.session.wallet.catchup_progress
                else:
                    r['message'] = "Catching up with the blockchain"
                    r['progress'] = 0
            else:
                r['message'] = "Catching up with the blockchain"
                r['progress'] = 0
        return self._render_response(r, OK_CODE)

    def jsonrpc_is_first_run(self):
        """
        Check if this is the first time lbrynet daemon has been run

        Args:
            None
        Returns:
            True if first run, otherwise False
        """

        log.info("Check if is first run")
        try:
            d = self.session.wallet.is_first_run()
        except:
            d = defer.fail(None)

        d.addCallbacks(
            lambda r: self._render_response(r, OK_CODE),
            lambda _: self._render_response(None, OK_CODE))

        return d

    def jsonrpc_get_start_notice(self):
        """
        Get special message to be displayed at startup

        Args:
            None
        Returns:
            Startup message, such as first run notification
        """

        log.info("Get startup notice")

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

        platform_info = self._get_platform()
        try:
            lbrynet_update_available = utils.version_is_greater_than(
                self.git_lbrynet_version, lbrynet_version)
        except AttributeError:
            lbrynet_update_available = False
        try:
            lbryum_update_available = utils.version_is_greater_than(
                self.git_lbryum_version, lbryum_version)
        except AttributeError:
            lbryum_update_available = False
        msg = {
            'platform': platform_info['platform'],
            'os_release': platform_info['os_release'],
            'os_system': platform_info['os_system'],
            'lbrynet_version': lbrynet_version,
            'lbryum_version': lbryum_version,
            'ui_version': self.ui_version,
            'remote_lbrynet': self.git_lbrynet_version,
            'remote_lbryum': self.git_lbryum_version,
            'lbrynet_update_available': lbrynet_update_available,
            'lbryum_update_available': lbryum_update_available
        }

        log.info("Get version info: " + json.dumps(msg))
        return self._render_response(msg, OK_CODE)

    def jsonrpc_get_lbry_session_info(self):
        """
        Get information about the current lbrynet session

        Args:
            None
        Returns:
            'lbry_id': string,
            'managed_blobs': int, number of completed blobs in the blob manager,
            'managed_streams': int, number of lbry files in the file manager
        """

        d = self.session.blob_manager.get_all_verified_blobs()

        def _prepare_message(blobs):
            msg = {
                'lbry_id': base58.b58encode(self.lbryid)[:SHORT_ID_LEN],
                'managed_blobs': len(blobs),
                'managed_streams': len(self.lbry_file_manager.lbry_files),
            }
            return msg

        d.addCallback(_prepare_message)
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

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
        """

        log.info("Get daemon settings")
        return self._render_response(conf.settings.get_dict(), OK_CODE)

    @AuthJSONRPCServer.auth_required
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
            log.info(
                "Set daemon settings to %s",
                json.dumps(conf.settings.get_adjustable_settings_dict()))

        d = self._update_settings(p)
        d.addErrback(lambda err: log.info(err.getTraceback()))
        d.addCallback(lambda _: _log_settings_change())
        d.addCallback(
            lambda _: self._regnder_response(conf.settings.get_adjustable_settings_dict(), OK_CODE))

        return d

    def jsonrpc_help(self, p=None):
        """Function to retrieve docstring for API function

        Args:
            optional 'function': function to retrieve documentation for
            optional 'callable_during_startup':
        Returns:
            if given a function, returns given documentation
            if given callable_during_startup flag, returns list of
            functions callable during the startup sequence
            if no params are given, returns the list of callable functions
        """

        if not p:
            return self._render_response(sorted(self.callable_methods.keys()), OK_CODE)
        elif 'callable_during_start' in p.keys():
            return self._render_response(self.allowed_during_startup, OK_CODE)
        elif 'function' in p.keys():
            func_path = p['function']
            function = self.callable_methods.get(func_path)
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

        log.info("Get balance")
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
        d.addCallback(lambda r: self._render_response([d[1] for d in r], OK_CODE))

        return d

    def jsonrpc_get_lbry_file(self, p):
        """Get lbry file

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
        d = self._get_deferred_for_lbry_file(p)
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def _get_deferred_for_lbry_file(self, p):
        try:
            searchtype, value = get_lbry_file_search_value(p)
        except NoValidSearch:
            return defer.fail()
        else:
            return self._get_lbry_file(searchtype, value)

    def jsonrpc_resolve_name(self, p):
        """
        Resolve stream info from a LBRY uri

        Args:
            'name': name to look up, string, do not include lbry:// prefix
        Returns:
            metadata from name claim
        """

        force = p.get('force', False)

        name = p.get(FileID.NAME)
        if not name:
            return self._render_response(None, BAD_REQUEST)

        d = self._resolve_name(name, force_refresh=force)
        # TODO: this is the rpc call that returns a server.failure.
        #       what is up with that?
        d.addCallbacks(
            lambda info: self._render_response(info, OK_CODE),
            # TODO: Is server.failure a module? It looks like it:
            #
            # In [1]: import twisted.web.server
            # In [2]: twisted.web.server.failure
            # Out[2]: <module 'twisted.python.failure' from
            #         '.../site-packages/twisted/python/failure.pyc'>
            #
            # If so, maybe we should return something else.
            errback=log.fail(lambda err: server.failure),
            errbackArgs=('Failed to resolve name',),
            errbackKeywords={'level':'INFO'},
        )
        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_get_my_claim(self, p):
        """
        Return existing claim for a given name

        Args:
            'name': name to look up
        Returns:
            claim info, False if no such claim exists
        """

        name = p[FileID.NAME]
        d = self.session.wallet.get_my_claim(name)
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def jsonrpc_get_claim_info(self, p):
        """
            Resolve claim info from a LBRY uri

            Args:
                'name': name to look up, string, do not include lbry:// prefix
                'txid': optional, if specified, look for claim with this txid
                'nout': optional, if specified, look for claim with this nout

            Returns:
                txid, amount, value, n, height
        """

        def _convert_amount_to_float(r):
            if not r:
                return False
            else:
                r['amount'] = float(r['amount']) / 10**8
                return r

        name = p[FileID.NAME]
        txid = p.get('txid', None)
        nout = p.get('nout', None)
        d = self.session.wallet.get_claim_info(name, txid, nout)
        d.addCallback(_convert_amount_to_float)
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def _process_get_parameters(self, p):
        """Extract info from input parameters and fill in default values for `get` call."""
        # TODO: this process can be abstracted s.t. each method
        #       can spec what parameters it expects and how to set default values
        timeout = p.get('timeout', self.download_timeout)
        download_directory = p.get('download_directory', self.download_directory)
        file_name = p.get(FileID.FILE_NAME)
        stream_info = p.get('stream_info')
        sd_hash = get_sd_hash(stream_info)
        wait_for_write = p.get('wait_for_write', True)
        name = p.get(FileID.NAME)
        return Parameters(
            timeout=timeout,
            download_directory=download_directory,
            file_name=file_name,
            stream_info=stream_info,
            sd_hash=sd_hash,
            wait_for_write=wait_for_write,
            name=name
        )

    @AuthJSONRPCServer.auth_required
    def jsonrpc_get(self, p):
        """Download stream from a LBRY uri.

        Args:
            'name': name to download, string
            'download_directory': optional, path to directory where file will be saved, string
            'file_name': optional, a user specified name for the downloaded file
            'stream_info': optional, specified stream info overrides name
            'timeout': optional
            'wait_for_write': optional, defaults to True
        Returns:
            'stream_hash': hex string
            'path': path of download
        """
        params = self._process_get_parameters(p)
        if not params.name:
            return server.failure
        if params.name in self.waiting_on:
            return server.failure
        d = self._download_name(name=params.name,
                                timeout=params.timeout,
                                download_directory=params.download_directory,
                                stream_info=params.stream_info,
                                file_name=params.file_name,
                                wait_for_write=params.wait_for_write)
        # TODO: downloading can timeout.  Not sure what to do when that happens
        d.addCallbacks(
            get_output_callback(params),
            lambda err: str(err))
        d.addCallback(lambda message: self._render_response(message, OK_CODE))
        return d

    @AuthJSONRPCServer.auth_required
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
            if f.stopped:
                return "LBRY file wasn't running"
            else:
                d = self.lbry_file_manager.toggle_lbry_file_running(f)
                d.addCallback(lambda _: "Stopped LBRY file")
                return d

        try:
            searchtype, value = get_lbry_file_search_value(p)
        except NoValidSearch:
            d = defer.fail()
        else:
            d = self._get_lbry_file(searchtype, value, return_json=False)
            d.addCallback(_stop_file)

        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    @AuthJSONRPCServer.auth_required
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
            if f.stopped:
                d = self.lbry_file_manager.toggle_lbry_file_running(f)
                return defer.succeed("Started LBRY file")
            else:
                return "LBRY file was already running"

        try:
            searchtype, value = get_lbry_file_search_value(p)
        except NoValidSearch:
            d = defer.fail()
        else:
            d = self._get_lbry_file(searchtype, value, return_json=False)
            d.addCallback(_start_file)

        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def jsonrpc_get_est_cost(self, p):
        """
        Get estimated cost for a lbry stream

        Args:
            'name': lbry uri
            'size': stream size, in bytes. if provided an sd blob won't be downloaded.
        Returns:
            estimated cost
        """

        size = p.get('size', None)
        name = p.get(FileID.NAME, None)

        d = self.get_est_cost(name, size)
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_delete_lbry_file(self, p):
        """
        Delete a lbry file

        Args:
            'file_name': downloaded file name, string
        Returns:
            confirmation message
        """

        delete_file = p.get('delete_target_file', True)

        def _delete_file(f):
            if not f:
                return False
            file_name = f.file_name
            d = self._delete_lbry_file(f, delete_file=delete_file)
            d.addCallback(lambda _: "Deleted LBRY file" + file_name)
            return d

        try:
            searchtype, value = get_lbry_file_search_value(p)
        except NoValidSearch:
            d = defer.fail()
        else:
            d = self._get_lbry_file(searchtype, value, return_json=False)
            d.addCallback(_delete_file)

        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_publish(self, p):
        """
        Make a new name claim and publish associated data to lbrynet

        Args:
            'name': name to be claimed, string
            'file_path': path to file to be associated with name, string
            'bid': amount of credits to commit in this claim, float
            'metadata': metadata dictionary
            optional 'fee'
        Returns:
            'txid' : txid of resulting transaction if succesful
            'nout' : nout of the resulting support claim if succesful
            'fee' : fee paid for the claim transaction if succesful
            'claimid' : claimid of the resulting transaction
        """

        def _set_address(address, currency, m):
            log.info("Generated new address for key fee: " + str(address))
            m['fee'][currency]['address'] = address
            return m

        def _reflect_if_possible(sd_hash, claim_out):
            d = self._get_lbry_file(FileID.SD_HASH, sd_hash, return_json=False)
            d.addCallback(self._reflect)
            d.addCallback(lambda _: claim_out)
            return d

        name = p[FileID.NAME]
        log.info("Publish: %s", p)
        verify_name_characters(name)
        bid = p['bid']
        if bid <= 0.0:
            return defer.fail(Exception("Invalid bid"))

        try:
            metadata = Metadata(p['metadata'])
            make_lbry_file = False
            sd_hash = metadata['sources']['lbry_sd_hash']
            log.info("Update publish for %s using existing stream", name)
        except ValidationError:
            make_lbry_file = True
            sd_hash = None
            metadata = p['metadata']
            file_path = p['file_path']
            if not file_path:
                raise Exception("No file given to publish")
            if not os.path.isfile(file_path):
                raise Exception("Specified file for publish doesnt exist: %s" % file_path)

        self.looping_call_manager.start(Checker.PENDING_CLAIM, 30)

        d = self._resolve_name(name, force_refresh=True)
        d.addErrback(lambda _: None)

        if 'fee' in p:
            metadata['fee'] = p['fee']
            assert len(metadata['fee']) == 1, "Too many fees"
            for c in metadata['fee']:
                if 'address' not in metadata['fee'][c]:
                    d.addCallback(lambda _: self.session.wallet.get_new_address())
                    d.addCallback(lambda addr: _set_address(addr, c, metadata))
        else:
            d.addCallback(lambda _: metadata)
        if make_lbry_file:
            pub = Publisher(self.session, self.lbry_file_manager, self.session.wallet)
            d.addCallback(lambda meta: pub.start(name, file_path, bid, meta))
        else:
            d.addCallback(lambda meta: self.session.wallet.claim_name(name, bid, meta))
            if sd_hash:
                d.addCallback(lambda claim_out: _reflect_if_possible(sd_hash, claim_out))

        d.addCallback(lambda claim_out: self._add_to_pending_claims(name, claim_out))
        d.addCallback(lambda r: self._render_response(r, OK_CODE))

        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_abandon_claim(self, p):
        """
        Abandon a name and reclaim credits from the claim
        Args:
            'txid': txid of claim, string
            'nout': nout of claim, integer
        Return:
            txid : txid of resulting transaction if succesful
            fee : fee paid for the transaction if succesful
        """
        if 'txid' in p.keys() and 'nout' in p.keys():
            txid = p['txid']
            nout = p['nout']
        else:
            return server.failure

        def _disp(x):
            log.info("Abandoned name claim tx " + str(x))
            return self._render_response(x, OK_CODE)

        d = defer.Deferred()
        d.addCallback(lambda _: self.session.wallet.abandon_claim(txid, nout))
        d.addCallback(_disp)
        d.callback(None)

        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_abandon_name(self, p):
        """
        DEPRECIATED, use abandon_claim

        Args:
            'txid': txid of claim, string
        Return:
            txid
        """

        return self.jsonrpc_abandon_claim(p)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_support_claim(self, p):
        """
        Support a name claim

        Args:
            'name': name
            'claim_id': claim id of claim to support
            'amount': amount to support by
        Return:
            txid : txid of resulting transaction if succesful
            nout : nout of the resulting support claim if succesful
            fee : fee paid for the transaction if succesful
        """

        name = p[FileID.NAME]
        claim_id = p['claim_id']
        amount = p['amount']
        d = self.session.wallet.support_claim(name, claim_id, amount)
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    @AuthJSONRPCServer.auth_required
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

    def jsonrpc_get_claims_for_name(self, p):
        """
        Get claims for a name

        Args:
            'name': name
        Returns
            list of name claims
        """

        name = p[FileID.NAME]
        d = self.session.wallet.get_claims_for_name(name)
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    @AuthJSONRPCServer.auth_required
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

    @AuthJSONRPCServer.auth_required
    def jsonrpc_address_is_mine(self, p):
        """
        Checks if an address is associated with the current wallet.

        Args:
            address: string
        Returns:
            is_mine: bool
        """

        address = p['address']

        d = self.session.wallet.address_is_mine(address)
        d.addCallback(lambda is_mine: self._render_response(is_mine, OK_CODE))

        return d

    @AuthJSONRPCServer.auth_required
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

    @AuthJSONRPCServer.auth_required
    def jsonrpc_get_new_address(self):
        """
        Generate a new wallet address

        Args:
            None
        Returns:
            new wallet address, base 58 string
        """

        def _disp(address):
            log.info("Got new wallet address: " + address)
            return defer.succeed(address)

        d = self.session.wallet.get_new_address()
        d.addCallback(_disp)
        d.addCallback(lambda address: self._render_response(address, OK_CODE))
        return d

    @AuthJSONRPCServer.auth_required
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
            d = self.session.wallet.get_block(blockhash)
        elif 'height' in p.keys():
            height = p['height']
            d = self.session.wallet.get_block_info(height)
            d.addCallback(lambda blockhash: self.session.wallet.get_block(blockhash))
        else:
            return server.failure
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

    @AuthJSONRPCServer.auth_required
    def jsonrpc_download_descriptor(self, p):
        """
        Download and return a sd blob

        Args:
            sd_hash
        Returns
            sd blob, dict
        """
        sd_hash = p[FileID.SD_HASH]
        timeout = p.get('timeout', conf.settings.sd_download_timeout)
        d = self._download_sd_blob(sd_hash, timeout)
        d.addCallbacks(
            lambda r: self._render_response(r, OK_CODE),
            lambda _: self._render_response(False, OK_CODE))
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

    @AuthJSONRPCServer.auth_required
    def jsonrpc_set_miner(self, p):
        """
            Start of stop the miner, function only available when lbrycrd is set as the wallet

            Args:
                run: True/False
            Returns:
                miner status, True/False
        """

        stat = p['run']
        if stat:
            d = self.session.wallet.start_miner()
        else:
            d = self.session.wallet.stop_miner()
        d.addCallback(lambda _: self.session.wallet.get_miner_status())
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def jsonrpc_get_miner_status(self):
        """
            Get status of miner

            Args:
                None
            Returns:
                True/False
        """

        d = self.session.wallet.get_miner_status()
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def jsonrpc_log(self, p):
        """
        Log message

        Args:
            'message': message to be logged
        Returns:
             True
        """

        message = p['message']
        log.info("API client log request: %s" % message)
        return self._render_response(True, OK_CODE)

    def jsonrpc_upload_log(self, p=None):
        """Upload log

        Args, optional:
            'name_prefix': prefix to indicate what is requesting the log upload
            'exclude_previous': true/false, whether or not to exclude
                previous sessions from upload, defaults on true

        Returns:
            True

        """

        if p:
            if 'name_prefix' in p.keys():
                log_type = p['name_prefix'] + '_api'
            elif 'log_type' in p.keys():
                log_type = p['log_type'] + '_api'
            else:
                log_type = None

            if 'exclude_previous' in p.keys():
                exclude_previous = p['exclude_previous']
            else:
                exclude_previous = True

            if 'message' in p.keys():
                log.info("Upload log message: " + str(p['message']))

            if 'force' in p.keys():
                force = p['force']
            else:
                force = False
        else:
            log_type = "api"
            exclude_previous = True

        d = self._upload_log(log_type=log_type, exclude_previous=exclude_previous, force=force)
        d.addCallback(lambda _: self._render_response(True, OK_CODE))
        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_configure_ui(self, p):
        """
        Configure the UI being hosted

        Args, optional:
            'branch': a branch name on lbryio/lbry-web-ui
            'path': path to a ui folder
        """

        if 'check_requirements' in p:
            check_require = p['check_requirements']
        else:
            check_require = True

        if 'path' in p:
            d = self.lbry_ui_manager.setup(
                user_specified=p['path'], check_requirements=check_require)
        elif 'branch' in p:
            d = self.lbry_ui_manager.setup(branch=p['branch'], check_requirements=check_require)
        else:
            d = self.lbry_ui_manager.setup(check_requirements=check_require)
        d.addCallback(lambda r: self._render_response(r, OK_CODE))

        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_reveal(self, p):
        """
        Reveal a file or directory in file browser

        Args:
            'path': path to be selected in file browser
        Returns:
            True, opens file browser
        """
        path = p['path']
        if sys.platform == "darwin":
            d = threads.deferToThread(subprocess.Popen, ['open', '-R', path])
        else:
            # No easy way to reveal specific files on Linux, so just open the containing directory
            d = threads.deferToThread(subprocess.Popen, ['xdg-open', os.path.dirname(path)])

        d.addCallback(lambda _: self._render_response(True, OK_CODE))
        return d

    def jsonrpc_get_peers_for_hash(self, p):
        """
        Get peers for blob hash

        Args:
            'blob_hash': blob hash
        Returns:
            List of contacts
        """

        blob_hash = p['blob_hash']

        d = self.session.peer_finder.find_peers_for_blob(blob_hash)
        d.addCallback(lambda r: [[c.host, c.port, c.is_available()] for c in r])
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def jsonrpc_announce_all_blobs_to_dht(self):
        """
        Announce all blobs to the dht

        Args:
            None
        Returns:

        """

        d = self.session.blob_manager.immediate_announce_all_blobs()
        d.addCallback(lambda _: self._render_response("Announced", OK_CODE))
        return d

    def jsonrpc_reflect(self, p):
        """
        Reflect a stream

        Args:
            sd_hash: sd_hash of lbry file
        Returns:
            True or traceback
        """

        sd_hash = p[FileID.SD_HASH]
        d = self._get_lbry_file(FileID.SD_HASH, sd_hash, return_json=False)
        d.addCallback(self._reflect)
        d.addCallbacks(
            lambda _: self._render_response(True, OK_CODE),
            lambda err: self._render_response(err.getTraceback(), OK_CODE))
        return d

    def jsonrpc_get_blob_hashes(self):
        """
        Returns all blob hashes

        Args:
            None
        Returns:
            list of blob hashes
        """

        d = self.session.blob_manager.get_all_verified_blobs()
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def jsonrpc_reflect_all_blobs(self):
        """
        Reflects all saved blobs

        Args:
            None
        Returns:
            True
        """

        d = self.session.blob_manager.get_all_verified_blobs()
        d.addCallback(self._reflect_blobs)
        d.addCallback(lambda r: self._render_response(r, OK_CODE))
        return d

    def jsonrpc_get_mean_availability(self):
        """
        Get mean blob availability

        Args:
            None
        Returns:
            Mean peers for a blob
        """

        d = self._render_response(self.session.blob_tracker.last_mean_availability, OK_CODE)
        return d

    def jsonrpc_get_availability(self, p):
        """
        Get stream availability for a winning claim

        Arg:
            name (str): lbry uri

        Returns:
             peers per blob / total blobs
        """

        def _get_mean(blob_availabilities):
            peer_counts = []
            for blob_availability in blob_availabilities:
                for blob, peers in blob_availability.iteritems():
                    peer_counts.append(peers)
            if peer_counts:
                return round(1.0 * sum(peer_counts) / len(peer_counts), 2)
            else:
                return 0.0

        name = p[FileID.NAME]

        d = self._resolve_name(name, force_refresh=True)
        d.addCallback(get_sd_hash)
        d.addCallback(self._download_sd_blob)
        d.addCallbacks(
            lambda descriptor: [blob.get('blob_hash') for blob in descriptor['blobs']],
            lambda _: [])
        d.addCallback(self.session.blob_tracker.get_availability_for_blobs)
        d.addCallback(_get_mean)
        d.addCallback(lambda result: self._render_response(result, OK_CODE))

        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_test_api_authentication(self):
        if self._use_authentication:
            return self._render_response(True, OK_CODE)
        return self._render_response("Not using authentication", OK_CODE)


def get_lbryum_version_from_github():
    r = urlopen(
        "https://raw.githubusercontent.com/lbryio/lbryum/master/lib/version.py").read().split('\n')
    version = next(line.split("=")[1].split("#")[0].replace(" ", "")
                   for line in r if "LBRYUM_VERSION" in line)
    version = version.replace("'", "")
    return version


def get_lbrynet_version_from_github():
    """Return the latest released version from github."""
    response = requests.get('https://api.github.com/repos/lbryio/lbry/releases/latest')
    release = response.json()
    tag = release['tag_name']
    # githubs documentation claims this should never happen, but we'll check just in case
    if release['prerelease']:
        raise Exception('Release {} is a pre-release'.format(tag))
    return get_version_from_tag(tag)


def get_version_from_tag(tag):
    match = re.match('v([\d.]+)', tag)
    if match:
        return match.group(1)
    else:
        raise Exception('Failed to parse version from tag {}'.format(tag))


def get_sd_hash(stream_info):
    if not stream_info:
        return None
    try:
        return stream_info['sources']['lbry_sd_hash']
    except KeyError:
        return stream_info.get('stream_hash')


def get_output_callback(params):
    def callback(l):
        return {
            'stream_hash': params.sd_hash if params.stream_info else l.sd_hash,
            'path': os.path.join(params.download_directory, l.file_name)
        }
    return callback


class _DownloadNameHelper(object):
    def __init__(self, daemon, name,
                 timeout=conf.settings.download_timeout,
                 download_directory=None, file_name=None,
                 wait_for_write=True):
        self.daemon = daemon
        self.name = name
        self.timeout = timeout
        if not download_directory or not os.path.isdir(download_directory):
            self.download_directory = daemon.download_directory
        else:
            self.download_directory = download_directory
        self.file_name = file_name
        self.wait_for_write = wait_for_write

    def _setup_stream(self, stream_info):
        stream_hash = get_sd_hash(stream_info)
        d = self.daemon._get_lbry_file_by_sd_hash(stream_hash)
        d.addCallback(self._prepend_stream_info, stream_info)
        return d

    def _prepend_stream_info(self, lbry_file, stream_info):
        if lbry_file:
            if os.path.isfile(os.path.join(self.download_directory, lbry_file.file_name)):
                return defer.succeed((stream_info, lbry_file))
        return defer.succeed((stream_info, None))

    def wait_or_get_stream(self, args):
        stream_info, lbry_file = args
        if lbry_file:
            log.debug('Wait on lbry_file')
            return self._wait_on_lbry_file(lbry_file)
        else:
            log.debug('No lbry_file, need to get stream')
            return self._get_stream(stream_info)

    def _get_stream(self, stream_info):
        d = self.daemon.add_stream(
            self.name, self.timeout, self.download_directory, self.file_name, stream_info)

        def _handle_timeout(args):
            was_successful, _, _ = args
            if not was_successful:
                log.warning("lbry://%s timed out, removing from streams", self.name)
                del self.daemon.streams[self.name]

        d.addCallback(_handle_timeout)

        if self.wait_for_write:
            d.addCallback(lambda _: self._wait_for_write())

        def _get_stream_for_return():
            stream = self.daemon.streams.get(self.name, None)
            if stream:
                return stream.downloader
            else:
                self._remove_from_wait("Timed out")
                return defer.fail(Exception("Timed out"))

        d.addCallback(lambda _: _get_stream_for_return())
        return d

    def _wait_for_write(self):
        d = defer.succeed(None)
        if not self.has_downloader_wrote():
            d.addCallback(lambda _: reactor.callLater(1, self._wait_for_write))
        return d

    def has_downloader_wrote(self):
        stream = self.daemon.streams.get(self.name, False)
        if stream:
            downloader = stream.downloader
        else:
            downloader = False
        if not downloader:
            return False
        return self.get_written_bytes(downloader.file_name)

    def _wait_on_lbry_file(self, f):
        written_bytes = self.get_written_bytes(f.file_name)
        if written_bytes:
            return defer.succeed(self._disp_file(f))
        return task.deferLater(reactor, 1, self._wait_on_lbry_file, f)

    def get_written_bytes(self, file_name):
        """Returns the number of bytes written to `file_name`.

        Returns False if there were issues reading `file_name`.
        """
        try:
            file_path = os.path.join(self.download_directory, file_name)
            if os.path.isfile(file_path):
                written_file = file(file_path)
                written_file.seek(0, os.SEEK_END)
                written_bytes = written_file.tell()
                written_file.close()
            else:
                written_bytes = False
        except Exception:
            writen_bytes = False
        return written_bytes

    def _disp_file(self, f):
        file_path = os.path.join(self.download_directory, f.file_name)
        log.info("Already downloaded: %s --> %s", f.sd_hash, file_path)
        return f

    def _remove_from_wait(self, r):
        if self.name in self.daemon.waiting_on:
            del self.daemon.waiting_on[self.name]
        return r


class _ResolveNameHelper(object):
    def __init__(self, daemon, name, force_refresh):
        self.daemon = daemon
        self.name = name
        self.force_refresh = force_refresh

    def get_deferred(self):
        if self.need_fresh_stream():
            log.info("Resolving stream info for lbry://%s", self.name)
            d = self.wallet.get_stream_info_for_name(self.name)
            d.addCallback(self._cache_stream_info)
        else:
            log.debug("Returning cached stream info for lbry://%s", self.name)
            d = defer.succeed(self.name_data['claim_metadata'])
        return d

    @property
    def name_data(self):
        return self.daemon.name_cache[self.name]

    @property
    def wallet(self):
        return self.daemon.session.wallet

    def now(self):
        return self.daemon._get_long_count_timestamp()

    def _add_txid(self, txid):
        self.name_data['txid'] = txid
        return defer.succeed(None)

    def _cache_stream_info(self, stream_info):
        self.daemon.name_cache[self.name] = {
            'claim_metadata': stream_info,
            'timestamp': self.now()
        }
        d = self.wallet.get_txid_for_name(self.name)
        d.addCallback(self._add_txid)
        d.addCallback(lambda _: self.daemon._update_claim_cache())
        d.addCallback(lambda _: self.name_data['claim_metadata'])
        return d

    def need_fresh_stream(self):
        return self.force_refresh or not self.is_in_cache() or self.is_cached_name_expired()

    def is_in_cache(self):
        return self.name in self.daemon.name_cache

    def is_cached_name_expired(self):
        time_in_cache = self.now() - self.name_data['timestamp']
        return time_in_cache >= self.daemon.cache_time


class _GetFileHelper(object):
    def __init__(self, daemon, search_by, val, return_json=True):
        self.daemon = daemon
        self.search_by = search_by
        self.val = val
        self.return_json = return_json

    def retrieve_file(self):
        d = self.search_for_file()
        if self.return_json:
            d.addCallback(self._get_json)
        return d

    def search_for_file(self):
        if self.search_by == FileID.NAME:
            return self.daemon._get_lbry_file_by_uri(self.val)
        elif self.search_by == FileID.SD_HASH:
            return self.daemon._get_lbry_file_by_sd_hash(self.val)
        elif self.search_by == FileID.FILE_NAME:
            return self.daemon._get_lbry_file_by_file_name(self.val)
        raise Exception('{} is not a valid search operation'.format(self.search_by))

    def _get_json(self, lbry_file):
        if lbry_file:
            d = lbry_file.get_total_bytes()
            d.addCallback(self._generate_reply, lbry_file)
            d.addCallback(self._add_metadata, lbry_file)
            return d
        else:
            return False

    def _generate_reply(self, size, lbry_file):
        written_bytes = self._get_written_bytes(lbry_file)
        code, message = self._get_status(lbry_file)

        if code == DOWNLOAD_RUNNING_CODE:
            d = lbry_file.status()
            d.addCallback(self._get_msg_for_file_status)
            d.addCallback(
                lambda msg: self._get_properties_dict(lbry_file, code, msg, written_bytes, size))
        else:
            d = defer.succeed(
                self._get_properties_dict(lbry_file, code, message, written_bytes, size))
        return d

    def _get_msg_for_file_status(self, file_status):
        message = STREAM_STAGES[2][1] % (
            file_status.name, file_status.num_completed, file_status.num_known,
            file_status.running_status)
        return defer.succeed(message)

    def _get_key(self, lbry_file):
        return binascii.b2a_hex(lbry_file.key) if lbry_file.key else None

    def _full_path(self, lbry_file):
        return os.path.join(lbry_file.download_directory, lbry_file.file_name)

    def _get_status(self, lbry_file):
        if self.search_by == FileID.NAME:
            if self.val in self.daemon.streams.keys():
                status = self.daemon.streams[self.val].code
            elif lbry_file in self.daemon.lbry_file_manager.lbry_files:
                status = STREAM_STAGES[2]
            else:
                status = [False, False]
        else:
            status = [False, False]
        return status

    def _get_written_bytes(self, lbry_file):
        full_path = self._full_path(lbry_file)
        if os.path.isfile(full_path):
            with open(full_path) as written_file:
                written_file.seek(0, os.SEEK_END)
                written_bytes = written_file.tell()
        else:
            written_bytes = False
        return written_bytes

    def _get_properties_dict(self, lbry_file, code, message, written_bytes, size):
        key = self._get_key(lbry_file)
        full_path = self._full_path(lbry_file)
        mime_type = mimetypes.guess_type(full_path)[0]
        return {
            'completed': lbry_file.completed,
            'file_name': lbry_file.file_name,
            'download_directory': lbry_file.download_directory,
            'points_paid': lbry_file.points_paid,
            'stopped': lbry_file.stopped,
            'stream_hash': lbry_file.stream_hash,
            'stream_name': lbry_file.stream_name,
            'suggested_file_name': lbry_file.suggested_file_name,
            'upload_allowed': lbry_file.upload_allowed,
            'sd_hash': lbry_file.sd_hash,
            'lbry_uri': lbry_file.uri,
            'txid': lbry_file.txid,
            'claim_id': lbry_file.claim_id,
            'download_path': full_path,
            'mime_type': mime_type,
            'key': key,
            'total_bytes': size,
            'written_bytes': written_bytes,
            'code': code,
            'message': message
        }

    def _add_metadata(self, message, lbry_file):
        def _add_to_dict(metadata):
            message['metadata'] = metadata
            return defer.succeed(message)

        if lbry_file.txid:
            d = self.daemon._resolve_name(lbry_file.uri)
            d.addCallbacks(_add_to_dict, lambda _: _add_to_dict("Pending confirmation"))
        else:
            d = defer.succeed(message)
        return d


def get_lbry_file_search_value(p):
    for searchtype in (FileID.SD_HASH, FileID.NAME, FileID.FILE_NAME):
        value = p.get(searchtype)
        if value:
            return searchtype, value
    raise NoValidSearch()


def run_reflector_factory(factory):
    reflector_server = random.choice(conf.settings.reflector_servers)
    reflector_address, reflector_port = reflector_server
    log.info("Start reflector client")
    d = reactor.resolve(reflector_address)
    d.addCallback(lambda ip: reactor.connectTCP(ip, reflector_port, factory))
    d.addCallback(lambda _: factory.finished_deferred)
    return d
