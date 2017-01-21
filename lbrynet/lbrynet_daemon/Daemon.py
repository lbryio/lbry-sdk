import binascii
import logging.handlers
import mimetypes
import os
import random
import re
import base58
import requests
import urllib
import simplejson as json
import textwrap
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
from lbrynet.core import log_support, utils, file_utils
from lbrynet.core import system_info
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier, download_sd_blob
from lbrynet.core.StreamDescriptor import BlobStreamDescriptorReader
from lbrynet.core.Session import Session
from lbrynet.core.Wallet import LBRYumWallet, SqliteStorage
from lbrynet.core.looping_call_manager import LoopingCallManager
from lbrynet.core.server.BlobRequestHandler import BlobRequestHandlerFactory
from lbrynet.core.server.ServerProtocol import ServerProtocolFactory
from lbrynet.core.Error import InsufficientFundsError

log = logging.getLogger(__name__)

INITIALIZING_CODE = 'initializing'
LOADING_DB_CODE = 'loading_db'
LOADING_WALLET_CODE = 'loading_wallet'
LOADING_FILE_MANAGER_CODE = 'loading_file_manager'
LOADING_SERVER_CODE = 'loading_server'
STARTED_CODE = 'started'
WAITING_FOR_FIRST_RUN_CREDITS = 'waiting_for_credits'
STARTUP_STAGES = [
    (INITIALIZING_CODE, 'Initializing'),
    (LOADING_DB_CODE, 'Loading databases'),
    (LOADING_WALLET_CODE, 'Catching up with the blockchain'),
    (LOADING_FILE_MANAGER_CODE, 'Setting up file manager'),
    (LOADING_SERVER_CODE, 'Starting lbrynet'),
    (STARTED_CODE, 'Started lbrynet'),
    (WAITING_FOR_FIRST_RUN_CREDITS, 'Waiting for first run credits'),
]

# TODO: make this consistent with the stages in Downloader.py
DOWNLOAD_METADATA_CODE = 'downloading_metadata'
DOWNLOAD_TIMEOUT_CODE = 'timeout'
DOWNLOAD_RUNNING_CODE = 'running'
DOWNLOAD_STOPPED_CODE = 'stopped'
STREAM_STAGES = [
    (INITIALIZING_CODE, 'Initializing'),
    (DOWNLOAD_METADATA_CODE, 'Downloading metadata'),
    (DOWNLOAD_RUNNING_CODE, 'Started %s, got %s/%s blobs, stream status: %s'),
    (DOWNLOAD_STOPPED_CODE, 'Paused stream'),
    (DOWNLOAD_TIMEOUT_CODE, 'Stream timed out')
]

CONNECTION_STATUS_CONNECTED = 'connected'
CONNECTION_STATUS_VERSION_CHECK = 'version_check'
CONNECTION_STATUS_NETWORK = 'network_connection'
CONNECTION_STATUS_WALLET = 'wallet_catchup_lag'
CONNECTION_MESSAGES = {
    CONNECTION_STATUS_CONNECTED: 'No connection problems detected',
    CONNECTION_STATUS_VERSION_CHECK: "There was a problem checking for updates on github",
    CONNECTION_STATUS_NETWORK: "Your internet connection appears to have been interrupted",
    CONNECTION_STATUS_WALLET: "Catching up with the blockchain is slow. " +
                              "If this continues try restarting LBRY",
}

PENDING_ID = "not set"
SHORT_ID_LEN = 20


class Checker:
    """The looping calls the daemon runs"""
    INTERNET_CONNECTION = 'internet_connection_checker'
    VERSION = 'version_checker'
    CONNECTION_STATUS = 'connection_status_checker'
    PENDING_CLAIM = 'pending_claim_checker'


class FileID:
    """The different ways a file can be identified"""
    NAME = 'name'
    SD_HASH = 'sd_hash'
    FILE_NAME = 'file_name'


# TODO add login credentials in a conf file
# TODO alert if your copy of a lbry file is out of date with the name record


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


# If an instance has a lot of blobs, this call might get very expensive.
# For reflector, with 50k blobs, it definitely has an impact on the first run
# But doesn't seem to impact performance after that.
@defer.inlineCallbacks
def calculate_available_blob_size(blob_manager):
    blob_hashes = yield blob_manager.get_all_verified_blobs()
    blobs = yield defer.DeferredList([blob_manager.get_blob(b, True) for b in blob_hashes])
    defer.returnValue(sum(b.length for success, b in blobs if success and b.length))


class Daemon(AuthJSONRPCServer):
    """
    LBRYnet daemon, a jsonrpc interface to lbry functions
    """

    def __init__(self, root, analytics_manager, upload_logs_on_shutdown=True):
        AuthJSONRPCServer.__init__(self, conf.settings['use_auth_http'])
        reactor.addSystemEventTrigger('before', 'shutdown', self._shutdown)

        self.upload_logs_on_shutdown = upload_logs_on_shutdown
        self.allowed_during_startup = [
            'stop', 'status', 'version',
            # delete these once they are fully removed:
            'is_running', 'is_first_run', 'get_time_behind_blockchain', 'daemon_status',
            'get_start_notice',
        ]
        last_version = {'last_version': {'lbrynet': lbrynet_version, 'lbryum': lbryum_version}}
        conf.settings.update(last_version)
        self.db_dir = conf.settings['data_dir']
        self.download_directory = conf.settings['download_directory']
        self.created_data_dir = False
        if not os.path.exists(self.db_dir):
            os.mkdir(self.db_dir)
            self.created_data_dir = True
        if conf.settings['BLOBFILES_DIR'] == "blobfiles":
            self.blobfile_dir = os.path.join(self.db_dir, "blobfiles")
        else:
            log.info("Using non-default blobfiles directory: %s", conf.settings['BLOBFILES_DIR'])
            self.blobfile_dir = conf.settings['BLOBFILES_DIR']

        self.run_on_startup = conf.settings['run_on_startup']
        self.data_rate = conf.settings['data_rate']
        self.max_key_fee = conf.settings['max_key_fee']
        self.max_upload = conf.settings['max_upload']
        self.max_download = conf.settings['max_download']
        self.upload_log = conf.settings['upload_log']
        self.search_timeout = conf.settings['search_timeout']
        self.download_timeout = conf.settings['download_timeout']
        self.max_search_results = conf.settings['max_search_results']
        self.run_reflector_server = conf.settings['run_reflector_server']
        self.wallet_type = conf.settings['wallet']
        self.delete_blobs_on_remove = conf.settings['delete_blobs_on_remove']
        self.peer_port = conf.settings['peer_port']
        self.reflector_port = conf.settings['reflector_port']
        self.dht_node_port = conf.settings['dht_node_port']
        self.use_upnp = conf.settings['use_upnp']
        self.cache_time = conf.settings['cache_time']

        self.startup_status = STARTUP_STAGES[0]
        self.connected_to_internet = True
        self.connection_status_code = None
        self.git_lbrynet_version = None
        self.git_lbryum_version = None
        self.platform = None
        self.first_run = None
        self.log_file = conf.settings.get_log_filename()
        self.current_db_revision = 2
        self.db_revision_file = conf.settings.get_db_revision_filename()
        self.session = None
        self.uploaded_temp_files = []
        self._session_id = conf.settings.get_session_id()
        # TODO: this should probably be passed into the daemon, or
        # possibly have the entire log upload functionality taken out
        # of the daemon, but I don't want to deal with that now
        self.log_uploader = log_support.LogUploader.load('lbrynet', self.log_file)

        self.analytics_manager = analytics_manager
        self.lbryid = conf.settings.get_lbry_id()

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
            Checker.CONNECTION_STATUS: LoopingCall(self._update_connection_status),
            Checker.PENDING_CLAIM: LoopingCall(self._check_pending_claims),
        }
        self.looping_call_manager = LoopingCallManager(calls)
        self.sd_identifier = StreamDescriptorIdentifier()
        self.stream_info_manager = TempEncryptedFileMetadataManager()
        self.lbry_ui_manager = UIManager(root)
        self.lbry_file_metadata_manager = None
        self.lbry_file_manager = None

    @defer.inlineCallbacks
    def setup(self, launch_ui):
        self._modify_loggly_formatter()

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
        self.looping_call_manager.start(Checker.CONNECTION_STATUS, 1)
        self.exchange_rate_manager.start()

        if conf.settings['host_ui']:
            self.lbry_ui_manager.update_checker.start(1800, now=False)
            yield self.lbry_ui_manager.setup()
        if launch_ui:
            self.lbry_ui_manager.launch()
        yield self._initial_setup()
        yield threads.deferToThread(self._setup_data_directory)
        yield self._check_db_migration()
        yield self._load_caches()
        yield self._get_session()
        yield self._get_analytics()
        yield add_lbry_file_to_sd_identifier(self.sd_identifier)
        yield self._setup_stream_identifier()
        yield self._setup_lbry_file_manager()
        yield self._setup_query_handlers()
        yield self._setup_server()
        log.info("Starting balance: " + str(self.session.wallet.wallet_balance))
        yield _announce_startup()

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
        lbryid_filename = os.path.join(self.db_dir, "lbryid")

        if os.path.isfile(name_cache_filename):
            with open(name_cache_filename, "r") as name_cache:
                self.name_cache = json.loads(name_cache.read())
            log.info("Loaded claim info cache")

        if os.path.isfile(lbryid_filename):
            with open(lbryid_filename, "r") as lbryid_file:
                self.lbryid = base58.b58decode(lbryid_file.read())
        else:
            with open(lbryid_filename, "w") as lbryid_file:
                self.lbryid = utils.generate_id()
                lbryid_file.write(base58.b58encode(self.lbryid))

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

    def _update_connection_status(self):
        self.connection_status_code = CONNECTION_STATUS_CONNECTED

        if not self.git_lbrynet_version or not self.git_lbryum_version:
            self.connection_status_code = CONNECTION_STATUS_VERSION_CHECK

        elif self.startup_status[0] == 'loading_wallet' and self.session.wallet.is_lagging:
            self.connection_status_code = CONNECTION_STATUS_WALLET

        if not self.connected_to_internet:
            self.connection_status_code = CONNECTION_STATUS_NETWORK

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
            claim_out = {'txid': txid, 'nout': nout}
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
            lbryid = base58.b58encode(self.lbryid)[:SHORT_ID_LEN]
            try:
                self.log_uploader.upload(exclude_previous, lbryid, log_type)
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

        if self.upload_logs_on_shutdown:
            try:
                d = self._upload_log(
                    log_type="close", exclude_previous=False if self.first_run else True)
            except Exception:
                log.warn('Failed to upload log', exc_info=True)
                d = defer.succeed(None)
        else:
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
                    conf.settings.update({key: settings[key]},
                                         data_types=(conf.TYPE_RUNTIME, conf.TYPE_PERSISTED))
                else:
                    try:
                        converted = setting_type(settings[key])
                        conf.settings.update({key: converted},
                                             data_types=(conf.TYPE_RUNTIME, conf.TYPE_PERSISTED))
                    except Exception as err:
                        log.warning(err.message)
                        log.warning("error converting setting '%s' to type %s", key, setting_type)
        conf.settings.save_conf_file_settings()

        self.run_on_startup = conf.settings['run_on_startup']
        self.data_rate = conf.settings['data_rate']
        self.max_key_fee = conf.settings['max_key_fee']
        self.download_directory = conf.settings['download_directory']
        self.max_upload = conf.settings['max_upload']
        self.max_download = conf.settings['max_download']
        self.upload_log = conf.settings['upload_log']
        self.download_timeout = conf.settings['download_timeout']
        self.search_timeout = conf.settings['search_timeout']
        self.cache_time = conf.settings['cache_time']

        return defer.succeed(True)

    def _write_db_revision_file(self, version_num):
        with open(self.db_revision_file, mode='w') as db_revision:
            db_revision.write(str(version_num))

    def _setup_data_directory(self):
        old_revision = 1
        self.startup_status = STARTUP_STAGES[1]
        log.info("Loading databases")
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
            log.info("Upgrading your databases")
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
                if conf.settings['lbryum_wallet_dir']:
                    config['lbryum_path'] = conf.settings['lbryum_wallet_dir']
                storage = SqliteStorage(self.db_dir)
                wallet = LBRYumWallet(storage, config)
                return defer.succeed(wallet)
            elif self.wallet_type == PTC_WALLET:
                log.info("Using PTC wallet")
                from lbrynet.core.PTCWallet import PTCWallet
                return defer.succeed(PTCWallet(self.db_dir))
            else:
                raise ValueError('Wallet Type {} is not valid'.format(self.wallet_type))

        d = get_wallet()

        def create_session(wallet):
            self.session = Session(
                conf.settings['data_rate'],
                db_dir=self.db_dir,
                lbryid=self.lbryid,
                blob_dir=self.blobfile_dir,
                dht_node_port=self.dht_node_port,
                known_dht_nodes=conf.settings['known_dht_nodes'],
                peer_port=self.peer_port,
                use_upnp=self.use_upnp,
                wallet=wallet,
                is_generous=conf.settings['is_generous_host']
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

    def _download_sd_blob(self, sd_hash, timeout=None):
        timeout = timeout if timeout is not None else conf.settings['sd_download_timeout']

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

    @defer.inlineCallbacks
    def _download_name(self, name, timeout=None, download_directory=None,
                       file_name=None, stream_info=None, wait_for_write=True):
        """
        Add a lbry file to the file manager, start the download, and return the new lbry file.
        If it already exists in the file manager, return the existing lbry file
        """
        timeout = timeout if timeout is not None else conf.settings['download_timeout']

        helper = _DownloadNameHelper(
            self, name, timeout, download_directory, file_name, wait_for_write)

        if not stream_info:
            self.waiting_on[name] = True
            stream_info = yield self._resolve_name(name)
            del self.waiting_on[name]
        lbry_file = yield helper.setup_stream(stream_info)
        sd_hash, file_path = yield helper.wait_or_get_stream(stream_info, lbry_file)
        defer.returnValue((sd_hash, file_path))

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
        dt = utils.utcnow() - utils.datetime_obj(year=2012, month=12, day=21)
        return int(dt.total_seconds())

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
        return size / (10 ** 6) * conf.settings['data_rate']

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
        def safe_get(sd_hash):
            d = self._get_lbry_file(FileID.SD_HASH, sd_hash)
            d.addErrback(log.fail(), 'Failed to get file for hash: %s', sd_hash)
            return d

        d = defer.DeferredList([
                                   safe_get(l.sd_hash)
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


    ############################################################################
    #                                                                          #
    #                JSON-RPC API methods start here                           #
    #                                                                          #
    ############################################################################

    @defer.inlineCallbacks
    def jsonrpc_status(self, p={}):
        """
        Return daemon status

        Args:
            session_status: bool
            blockchain_status: bool
        Returns:
            daemon status
        """
        has_wallet = self.session and self.session.wallet
        response = {
            'lbry_id': base58.b58encode(self.lbryid)[:SHORT_ID_LEN],
            'is_running': self.announced_startup,
            'is_first_run': self.session.wallet.is_first_run if has_wallet  else None,
            'startup_status': {
                'code': self.startup_status[0],
                'message': self.startup_status[1],
            },
            'connection_status': {
                'code': self.connection_status_code,
                'message': (
                    CONNECTION_MESSAGES[self.connection_status_code]
                    if self.connection_status_code is not None
                    else ''
                ),
            },
            'blocks_behind': (
                self.session.wallet.blocks_behind
                if has_wallet  and self.wallet_type == LBRYUM_WALLET
                else 'unknown'
            ),
        }
        if p.get('session_status', False):
            blobs = yield self.session.blob_manager.get_all_verified_blobs()
            response['session_status'] = {
                'managed_blobs': len(blobs),
                'managed_streams': len(self.lbry_file_manager.lbry_files),
            }
        if p.get('blockchain_status', False) and has_wallet:
            # calculate blocks_behind more accurately
            local_height = self.session.wallet.network.get_local_height()
            remote_height = self.session.wallet.network.get_server_height()
            response['blocks_behind'] = remote_height - local_height
            best_hash = yield self.session.wallet.get_best_blockhash()
            response['blockchain_status'] = {'best_blockhash': best_hash}
        defer.returnValue(response)

    def jsonrpc_get_best_blockhash(self):
        """
        DEPRECATED. Use `status blockchain_status=True` instead
        """
        d = self.jsonrpc_status({'blockchain_status': True})
        d.addCallback(lambda x: self._render_response(
            x['blockchain_status']['best_blockhash']))
        return d

    def jsonrpc_is_running(self):
        """
        DEPRECATED. Use `status` instead
        """
        d = self.jsonrpc_status()
        d.addCallback(lambda x: self._render_response(x['is_running']))
        return d

    def jsonrpc_daemon_status(self):
        """
        DEPRECATED. Use `status` instead
        """

        def _simulate_old_daemon_status(status):
            message = status['startup_status']['message']
            problem_code = None
            progress = None

            if self.connection_status_code != CONNECTION_STATUS_CONNECTED:
                problem_code = self.connection_status_code
                message = CONNECTION_MESSAGES[self.connection_status_code]
            elif status['startup_status']['code'] == LOADING_WALLET_CODE:
                message = "Catching up with the blockchain."
                progress = 0
                if status['blocks_behind'] > 0:
                    message += ' ' + str(status['blocks_behind']) + " blocks behind."
                    progress = self.session.wallet.catchup_progress

            return {
                'message': message,
                'code': status['startup_status']['code'],
                'progress': progress,
                'is_lagging': self.connection_status_code != CONNECTION_STATUS_CONNECTED,
                'problem_code': problem_code,
            }

        d = self.jsonrpc_status()
        d.addCallback(_simulate_old_daemon_status)
        d.addCallback(lambda x: self._render_response(x))  # is this necessary?
        return d

    def jsonrpc_is_first_run(self):
        """
        DEPRECATED. Use `status` instead
        """
        d = self.jsonrpc_status({'blockchain_status': True})
        d.addCallback(lambda x: self._render_response(x['is_first_run']))
        return d

    def jsonrpc_get_lbry_session_info(self):
        """
        DEPRECATED. Use `status` instead
        """

        d = self.jsonrpc_status({'session_status': True})
        d.addCallback(lambda x: self._render_response({
            'lbry_id': x['lbry_id'],
            'managed_blobs': x['session_status']['managed_blobs'],
            'managed_streams': x['session_status']['managed_streams'],
        }))
        return d

    def jsonrpc_get_time_behind_blockchain(self):
        """
        DEPRECATED. Use `status` instead
        """
        d = self.jsonrpc_status({'blockchain_status': True})  # blockchain_status=True is needed
        d.addCallback(lambda x: self._render_response(x['blocks_behind']))
        return d

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
            'ui_version': platform_info['ui_version'],
            'remote_lbrynet': self.git_lbrynet_version,
            'remote_lbryum': self.git_lbryum_version,
            'lbrynet_update_available': lbrynet_update_available,
            'lbryum_update_available': lbryum_update_available
        }

        log.info("Get version info: " + json.dumps(msg))
        return self._render_response(msg)

    def jsonrpc_report_bug(self, p):
        """
        Report a bug to slack

        Args:
            'message': string, message to send
        Returns:
            True if successful
        """

        bug_message = p['message']
        platform_name = self._get_platform()['platform']
        report_bug_to_slack(bug_message, self.lbryid, platform_name, lbrynet_version)
        return self._render_response(True)

    def jsonrpc_get_settings(self):
        """
        DEPRECATED. Use `settings_get` instead.
        """
        return self.jsonrpc_settings_get()

    def jsonrpc_settings_get(self):
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
        return self._render_response(conf.settings.get_current_settings_dict())

    @AuthJSONRPCServer.auth_required
    def jsonrpc_set_settings(self, p):
        """
        DEPRECATED. Use `settings_set` instead.
        """
        return self.jsonrpc_settings_set(p)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_settings_set(self, p):
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
            lambda _: self._render_response(conf.settings.get_adjustable_settings_dict()))

        return d

    def jsonrpc_help(self, p=None):
        """
        Return a useful message for an API command

        Args:
            'command': optional, command to retrieve documentation for
        Returns:
            if given a command, returns documentation about that command
            otherwise returns general help message
        """

        if p and 'command' in p:
            fn = self.callable_methods.get(p['command'])
            if fn is None:
                return self._render_response(
                    "No help available for '" + p['command'] + "'. It is not a valid command."
                )
            return self._render_response(textwrap.dedent(fn.__doc__))
        else:
            return self._render_response(textwrap.dedent(self.jsonrpc_help.__doc__))

    def jsonrpc_commands(self):
        """
        Return a list of available commands

        Returns:
            list
        """
        return self._render_response(sorted(self.callable_methods.keys()))

    def jsonrpc_get_balance(self):
        """
        DEPRECATED. Use `wallet_balance` instead.
        """
        return self.jsonrpc_wallet_balance()

    def jsonrpc_wallet_balance(self):
        """
        Return the balance of the wallet

        Returns:
            balance, float
        """
        return self._render_response(float(self.session.wallet.wallet_balance))

    def jsonrpc_stop(self):
        """
        DEPRECATED. Use `daemon_stop` instead.
        """
        return self.jsonrpc_daemon_stop()

    def jsonrpc_daemon_stop(self):
        """
        Stop lbrynet-daemon

        Returns:
            shutdown message
        """

        def _display_shutdown_message():
            log.info("Shutting down lbrynet daemon")

        d = self._shutdown()
        d.addCallback(lambda _: _display_shutdown_message())
        d.addCallback(lambda _: reactor.callLater(0.0, reactor.stop))
        return self._render_response("Shutting down")

    def jsonrpc_get_lbry_files(self):
        """
        DEPRECATED. Use `file_list` instead.
        """
        return self.jsonrpc_file_list()

    def jsonrpc_file_list(self):
        """
        List files

        Args:
            None
        Returns:
            List of files, with the following keys:
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
        d.addCallback(lambda r: self._render_response([d[1] for d in r if d[0]]))

        return d

    def jsonrpc_get_lbry_file(self, p):
        """
        DEPRECATED. Use `file_get` instead.
        """
        return self.jsonrpc_file_get(p)

    def jsonrpc_file_get(self, p):
        """
        Get a file

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
        d.addCallback(lambda r: self._render_response(r))
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
            return self._render_response(None)

        d = self._resolve_name(name, force_refresh=force)
        d.addCallback(self._render_response)
        return d

    def jsonrpc_get_claim_info(self, p):
        """
        DEPRECATED. Use `claim_show` instead.
        """
        return self.jsonrpc_claim_show(p)

    def jsonrpc_claim_show(self, p):

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
                r['amount'] = float(r['amount']) / 10 ** 8
                return r

        name = p[FileID.NAME]
        txid = p.get('txid', None)
        nout = p.get('nout', None)
        d = self.session.wallet.get_claim_info(name, txid, nout)
        d.addCallback(_convert_amount_to_float)
        d.addCallback(lambda r: self._render_response(r))
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
    @defer.inlineCallbacks
    def jsonrpc_get(self, p):
        """
        Download stream from a LBRY uri.

        Args:
            'name': name to download, string
            'download_directory': optional, path to directory where file will be saved, string
            'file_name': optional, a user specified name for the downloaded file
            'stream_info': optional, specified stream info overrides name
            'timeout': optional
            'wait_for_write': optional, defaults to True. When set, waits for the file to
                only start to be written before returning any results.
        Returns:
            'stream_hash': hex string
            'path': path of download
        """
        params = self._process_get_parameters(p)
        if not params.name:
            # TODO: return a useful error message here, like "name argument is required"
            defer.returnValue(server.failure)
        if params.name in self.waiting_on:
            # TODO: return a useful error message here, like "already
            # waiting for name to be resolved"
            defer.returnValue(server.failure)
        name = params.name
        stream_info = params.stream_info

        # first check if we already have this
        lbry_file = yield self._get_lbry_file(FileID.NAME, name, return_json=False)
        if lbry_file:
            log.info('Already have a file for %s', name)
            message = {
                'stream_hash': params.sd_hash if params.stream_info else lbry_file.sd_hash,
                'path': os.path.join(lbry_file.download_directory, lbry_file.file_name)
            }
            response = yield self._render_response(message)
            defer.returnValue(response)

        download_id = utils.random_string()
        self.analytics_manager.send_download_started(download_id, name, stream_info)
        try:
            sd_hash, file_path = yield self._download_name(
                name=params.name,
                timeout=params.timeout,
                download_directory=params.download_directory,
                stream_info=params.stream_info,
                file_name=params.file_name,
                wait_for_write=params.wait_for_write
            )
        except Exception as e:
            self.analytics_manager.send_download_errored(download_id, name, stream_info)
            log.exception('Failed to get %s', params.name)
            response = yield self._render_response(str(e))
        else:
            # TODO: should stream_hash key be changed to sd_hash?
            message = {
                'stream_hash': params.sd_hash if params.stream_info else sd_hash,
                'path': file_path
            }
            stream = self.streams.get(name)
            if stream:
                stream.downloader.finished_deferred.addCallback(
                    lambda _: self.analytics_manager.send_download_finished(
                        download_id, name, stream_info)
                )
            response = yield self._render_response(message)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_stop_lbry_file(self, p):
        """
        DEPRECATED. Use `file_seed status=stop` instead.
        """
        p['status'] = 'stop'
        return self.jsonrpc_file_seed(p)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_start_lbry_file(self, p):
        """
        DEPRECATED. Use `file_seed status=start` instead.
        """
        p['status'] = 'start'
        return self.jsonrpc_file_seed(p)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_file_seed(self, p):
        """
        Start or stop seeding a file

        Args:
            'status': "start" or "stop"
            'name': start file by lbry uri,
            'sd_hash': start file by the hash in the name claim,
            'file_name': start file by its name in the downloads folder,
        Returns:
            confirmation message
        """

        status = p.get('status', None)
        if status is None:
            raise Exception('"status" option required')
        if status not in ['start', 'stop']:
            raise Exception('Status must be "start" or "stop".')

        search_type, value = get_lbry_file_search_value(p)
        lbry_file = yield self._get_lbry_file(search_type, value, return_json=False)
        if not lbry_file:
            raise Exception('Unable to find a file for {}:{}'.format(search_type, value))

        if status == 'start' and lbry_file.stopped or status == 'stop' and not lbry_file.stopped:
            yield self.lbry_file_manager.toggle_lbry_file_running(lbry_file)
            msg = "Started seeding file" if status == 'start' else "Stopped seeding file"
        else:
            msg = (
                "File was already being seeded" if status == 'start' else "File was already stopped"
            )
        response = yield self._render_response(msg)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_delete_lbry_file(self, p):
        """
        DEPRECATED. Use `file_delete` instead
        """
        return self.jsonrpc_file_delete(p)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_file_delete(self, p):
        """
        Delete a lbry file

        Args:
            'file_name': downloaded file name, string
        Returns:
            confirmation message
        """

        # TODO: is this option used? if yes, document it. if no, remove it
        delete_file = p.get('delete_target_file', True)

        def _delete_file(f):
            if not f:
                return False
            file_name = f.file_name
            d = self._delete_lbry_file(f, delete_file=delete_file)
            d.addCallback(lambda _: "Deleted file: " + file_name)
            return d

        try:
            searchtype, value = get_lbry_file_search_value(p)
        except NoValidSearch:
            d = defer.fail()
        else:
            d = self._get_lbry_file(searchtype, value, return_json=False)
            d.addCallback(_delete_file)

        d.addCallback(lambda r: self._render_response(r))
        return d

    def jsonrpc_get_est_cost(self, p):
        """
        DEPRECATED. Use `stream_cost_estimate` instead
        """
        return self.jsonrpc_stream_cost_estimate(p)

    def jsonrpc_stream_cost_estimate(self, p):
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
        d.addCallback(lambda r: self._render_response(r))
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
            'success' : True if claim was succesful , False otherwise
            'reason' : if not succesful, give reason
            'txid' : txid of resulting transaction if succesful
            'nout' : nout of the resulting support claim if succesful
            'fee' : fee paid for the claim transaction if succesful
            'claim_id' : claim id of the resulting transaction
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
        d.addCallback(lambda r: self._render_response(r))

        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_abandon_claim(self, p):
        """
        DEPRECATED. Use `claim_abandon` instead
        """
        return self.jsonrpc_claim_abandon(p)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_claim_abandon(self, p):
        """
        Abandon a name and reclaim credits from the claim

        Args:
            'txid': txid of claim, string
            'nout': nout of claim, integer
        Return:
            txid : txid of resulting transaction if succesful
            fee : fee paid for the transaction if succesful
        """
        if 'txid' not in p or 'nout' not in p:
            return server.failure

        def _disp(x):
            log.info("Abandoned name claim tx " + str(x))
            return self._render_response(x)

        d = defer.Deferred()
        d.addCallback(lambda _: self.session.wallet.abandon_claim(p['txid'], p['nout']))
        d.addCallback(_disp)
        d.callback(None)  # TODO: is this line necessary???
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
        DEPRECATED. Use `claim_abandon` instead
        """
        return self.jsonrpc_claim_new_support(p)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_claim_new_support(self, p):
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
        d.addCallback(lambda r: self._render_response(r))
        return d

    # TODO: merge this into claim_list
    @AuthJSONRPCServer.auth_required
    def jsonrpc_get_my_claim(self, p):
        """
        DEPRECATED. This method will be removed in a future release.

        Return existing claim for a given name

        Args:
            'name': name to look up
        Returns:
            claim info, False if no such claim exists
        """

        d = self.session.wallet.get_my_claim(p[FileID.NAME])
        d.addCallback(lambda r: self._render_response(r))
        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_get_name_claims(self):
        """
        DEPRECATED. Use `claim_list_mine` instead
        """
        return self.jsonrpc_claim_list_mine()

    # TODO: claim_list_mine should be merged into claim_list, but idk how to authenticate it -Grin
    @AuthJSONRPCServer.auth_required
    def jsonrpc_claim_list_mine(self):
        """
        List my name claims

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
        d.addCallback(lambda claims: self._render_response(claims))
        return d

    def jsonrpc_get_claims_for_name(self, p):
        """
        DEPRECATED. Use `claim_list` instead.
        """
        return self.jsonrpc_claim_list(p)

    def jsonrpc_get_claims_for_tx(self, p):
        """
        DEPRECATED. Use `claim_list` instead.
        """
        return self.jsonrpc_claim_list(p)

    def jsonrpc_claim_list(self, p):
        """
        Get claims for a name

        Args:
            name: file name
            txid: transaction id of a name claim transaction
        Returns
            list of name claims
        """

        if FileID.NAME in p:
            d = self.session.wallet.get_claims_for_name(p[FileID.NAME])
        elif 'txid' in p:
            d = self.session.wallet.get_claims_from_tx(p['txid'])
        else:
            return server.failure

        d.addCallback(lambda r: self._render_response(r))
        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_get_transaction_history(self):
        """
        DEPRECATED. Use `transaction_list` instead
        """
        return self.jsonrpc_transaction_list()

    @AuthJSONRPCServer.auth_required
    def jsonrpc_transaction_list(self):
        """
        List transactions

        Args:
            None
        Returns:
            list of transactions
        """

        d = self.session.wallet.get_history()
        d.addCallback(lambda r: self._render_response(r))
        return d

    def jsonrpc_get_transaction(self, p):
        """
        DEPRECATED. Use `transaction_show` instead
        """
        return self.jsonrpc_transaction_show(p)

    def jsonrpc_transaction_show(self, p):
        """
        Get a decoded transaction from a txid

        Args:
            txid: txid hex string
        Returns:
            JSON formatted transaction
        """

        d = self.session.wallet.get_transaction(p['txid'])
        d.addCallback(lambda r: self._render_response(r))
        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_address_is_mine(self, p):
        """
        DEPRECATED. Use `wallet_is_address_mine` instead
        """
        return self.jsonrpc_wallet_is_address_mine(p)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_wallet_is_address_mine(self, p):
        """
        Checks if an address is associated with the current wallet.

        Args:
            address: string
        Returns:
            is_mine: bool
        """

        d = self.session.wallet.address_is_mine(p['address'])
        d.addCallback(lambda is_mine: self._render_response(is_mine))
        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_get_public_key_from_wallet(self, p):
        """
        DEPRECATED. Use `wallet_is_address_mine` instead
        """
        return self.jsonrpc_wallet_public_key(p)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_wallet_public_key(self, p):
        """
        Get public key from wallet address

        Args:
            wallet: wallet address, base58
        Returns:
            public key
        """

        d = self.session.wallet.get_pub_keys(p['wallet'])
        d.addCallback(lambda r: self._render_response(r))

    @AuthJSONRPCServer.auth_required
    def jsonrpc_get_new_address(self):
        """
        DEPRECATED. Use `wallet_new_address` instead
        """
        return self.jsonrpc_wallet_new_address()

    @AuthJSONRPCServer.auth_required
    def jsonrpc_wallet_new_address(self):
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
        d.addCallback(lambda address: self._render_response(address))
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

        if 'amount' in p and 'address' in p:
            amount = p['amount']
            address = p['address']
        else:
            # TODO: return a useful error message
            return server.failure

        reserved_points = self.session.wallet.reserve_points(address, amount)
        if reserved_points is None:
            return defer.fail(InsufficientFundsError())
        d = self.session.wallet.send_points_to_address(reserved_points, amount)
        d.addCallback(lambda _: self._render_response(True))
        return d

    def jsonrpc_get_block(self, p):
        """
        DEPRECATED. Use `block_show` instead
        """
        return self.jsonrpc_block_show(p)

    def jsonrpc_block_show(self, p):
        """
            Get contents of a block

            Args:
                blockhash: hash of the block to look up
            Returns:
                requested block
        """

        if 'blockhash' in p:
            d = self.session.wallet.get_block(p['blockhash'])
        elif 'height' in p:
            d = self.session.wallet.get_block_info(p['height'])
            d.addCallback(lambda blockhash: self.session.wallet.get_block(blockhash))
        else:
            # TODO: return a useful error message
            return server.failure
        d.addCallback(lambda r: self._render_response(r))
        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_download_descriptor(self, p):
        """
        DEPRECATED. Use `blob_get` instead
        """
        return self.jsonrpc_blob_get(p)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_blob_get(self, p):
        """
        Download and return a sd blob

        Args:
            sd_hash
        Returns
            sd blob, dict
        """
        sd_hash = p[FileID.SD_HASH]
        timeout = p.get('timeout', conf.settings['sd_download_timeout'])
        d = self._download_sd_blob(sd_hash, timeout)
        d.addCallbacks(
            lambda r: self._render_response(r),
            lambda _: self._render_response(False))
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
        d.addCallback(lambda r: self._render_response(r))
        return d

    def jsonrpc_log(self, p):
        """
        DEPRECATED. This method will be removed in a future release.

        Log message

        Args:
            'message': message to be logged
        Returns:
             True
        """

        log.info("API client log request: %s" % p['message'])
        return self._render_response(True)

    def jsonrpc_upload_log(self, p=None):
        """
        DEPRECATED. This method will be removed in a future release.

        Upload log

        Args, optional:
            'name_prefix': prefix to indicate what is requesting the log upload
            'exclude_previous': true/false, whether or not to exclude
                previous sessions from upload, defaults on true

        Returns:
            True

        """

        exclude_previous = True
        force = False
        log_type = None

        if p:
            if 'name_prefix' in p:
                log_type = p['name_prefix'] + '_api'
            elif 'log_type' in p:
                log_type = p['log_type'] + '_api'

            if 'exclude_previous' in p:
                exclude_previous = p['exclude_previous']

            if 'message' in p:
                log.info("Upload log message: " + str(p['message']))

            if 'force' in p:
                force = p['force']
        else:
            log_type = "api"

        d = self._upload_log(log_type=log_type, exclude_previous=exclude_previous, force=force)
        d.addCallback(lambda _: self._render_response(True))
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
        d.addCallback(lambda r: self._render_response(r))

        return d

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_open(self, p):
        """
        Instruct the OS to open a file with its default program.

        Args:
            'sd_hash': SD hash of file to be opened
        Returns:
            True, opens file
        """

        if 'sd_hash' not in p:
            raise ValueError('sd_hash is required')

        lbry_file = yield self._get_lbry_file(FileID.SD_HASH, p['sd_hash'])
        if not lbry_file:
            raise Exception('Unable to find file for {}'.format(p['sd_hash']))

        try:
            file_utils.start(lbry_file['download_path'])
        except IOError:
            pass
        defer.returnValue(True)

    @defer.inlineCallbacks
    @AuthJSONRPCServer.auth_required
    def jsonrpc_reveal(self, p):
        """
        Reveal a file or directory in file browser

        Args:
            'path': path to be revealed in file browser
        Returns:
            True, opens file browser
        """

        if 'sd_hash' not in p:
            raise ValueError('sd_hash is required')

        lbry_file = yield self._get_lbry_file(FileID.SD_HASH, p['sd_hash'])
        if not lbry_file:
            raise Exception('Unable to find file for {}'.format(p['sd_hash']))

        try:
            file_utils.reveal(lbry_file['download_path'])
        except IOError:
            pass
        defer.returnValue(True)

    def jsonrpc_get_peers_for_hash(self, p):
        """
        DEPRECATED. Use `peer_list` instead
        """
        return self.jsonrpc_peer_list(p)

    def jsonrpc_peer_list(self, p):
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
        d.addCallback(lambda r: self._render_response(r))
        return d

    def jsonrpc_announce_all_blobs_to_dht(self):
        """
        DEPRECATED. Use `blob_announce_all` instead.
        """
        return self.jsonrpc_blob_announce_all()

    def jsonrpc_blob_announce_all(self):
        """
        Announce all blobs to the DHT

        Args:
            None
        Returns:

        """

        d = self.session.blob_manager.immediate_announce_all_blobs()
        d.addCallback(lambda _: self._render_response("Announced"))
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
            lambda _: self._render_response(True),
            lambda err: self._render_response(err.getTraceback()))
        return d

    def jsonrpc_get_blob_hashes(self):
        """
        DEPRECATED. Use `blob_list` instead
        """
        return self.jsonrpc_blob_list()

    def jsonrpc_blob_list(self):
        """
        Returns all blob hashes

        Args:
            None
        Returns:
            list of blob hashes
        """

        d = self.session.blob_manager.get_all_verified_blobs()
        d.addCallback(lambda r: self._render_response(r))
        return d

    def jsonrpc_reflect_all_blobs(self):
        """
        DEPRECATED. Use `blob_reflect_all` instead
        """
        return self.jsonrpc_blob_reflect_all()

    def jsonrpc_blob_reflect_all(self):
        """
        Reflects all saved blobs

        Args:
            None
        Returns:
            True
        """

        d = self.session.blob_manager.get_all_verified_blobs()
        d.addCallback(self._reflect_blobs)
        d.addCallback(lambda r: self._render_response(r))
        return d

    def jsonrpc_get_mean_availability(self):
        """
        Get mean blob availability

        Args:
            None
        Returns:
            Mean peers for a blob
        """

        d = self._render_response(self.session.blob_tracker.last_mean_availability)
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

        d = self._resolve_name(p[FileID.NAME], force_refresh=True)
        d.addCallback(get_sd_hash)
        d.addCallback(self._download_sd_blob)
        d.addCallbacks(
            lambda descriptor: [blob.get('blob_hash') for blob in descriptor['blobs']],
            lambda _: [])
        d.addCallback(self.session.blob_tracker.get_availability_for_blobs)
        d.addCallback(_get_mean)
        d.addCallback(lambda result: self._render_response(result))

        return d

    def jsonrpc_get_start_notice(self):
        """
        DEPRECATED.

        Get special message to be displayed at startup
        Args:
            None
        Returns:
            Startup message, such as first run notification
        """

        def _get_startup_message(status):
            if status['is_first_run'] and self.session.wallet.wallet_balance:
                return self._render_response(None)
            else:
                return self._render_response(status['startup_status']['message'])

        d = self.jsonrpc_status()
        d.addCallback(_get_startup_message)
        return d



def get_lbryum_version_from_github():
    return get_version_from_github('https://api.github.com/repos/lbryio/lbryum/releases/latest')


def get_lbrynet_version_from_github():
    return get_version_from_github('https://api.github.com/repos/lbryio/lbry/releases/latest')


def get_version_from_github(url):
    """Return the latest released version from github."""
    response = requests.get(url, timeout=20)
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


class _DownloadNameHelper(object):
    def __init__(self, daemon, name,
                 timeout=None,
                 download_directory=None, file_name=None,
                 wait_for_write=True):
        self.daemon = daemon
        self.name = name
        self.timeout = timeout if timeout is not None else conf.settings['download_timeout']
        if not download_directory or not os.path.isdir(download_directory):
            self.download_directory = daemon.download_directory
        else:
            self.download_directory = download_directory
        self.file_name = file_name
        self.wait_for_write = wait_for_write

    @defer.inlineCallbacks
    def setup_stream(self, stream_info):
        sd_hash = get_sd_hash(stream_info)
        lbry_file = yield self.daemon._get_lbry_file_by_sd_hash(sd_hash)
        if self._does_lbry_file_exists(lbry_file):
            defer.returnValue(lbry_file)
        else:
            defer.returnValue(None)

    def _does_lbry_file_exists(self, lbry_file):
        return lbry_file and os.path.isfile(self._full_path(lbry_file))

    def _full_path(self, lbry_file):
        return os.path.join(self.download_directory, lbry_file.file_name)

    @defer.inlineCallbacks
    def wait_or_get_stream(self, stream_info, lbry_file):
        if lbry_file:
            log.debug('Wait on lbry_file')
            # returns the lbry_file
            yield self._wait_on_lbry_file(lbry_file)
            defer.returnValue((lbry_file.sd_hash, self._full_path(lbry_file)))
        else:
            log.debug('No lbry_file, need to get stream')
            # returns an instance of ManagedEncryptedFileDownloaderFactory
            sd_hash, file_path = yield self._get_stream(stream_info)
            defer.returnValue((sd_hash, file_path))

    def _wait_on_lbry_file(self, f):
        file_path = self._full_path(f)
        written_bytes = self._get_written_bytes(file_path)
        if written_bytes:
            log.info("File has bytes: %s --> %s", f.sd_hash, file_path)
            return defer.succeed(True)
        return task.deferLater(reactor, 1, self._wait_on_lbry_file, f)

    @defer.inlineCallbacks
    def _get_stream(self, stream_info):
        was_successful, sd_hash, download_path = yield self.daemon.add_stream(
            self.name, self.timeout, self.download_directory, self.file_name, stream_info)
        if not was_successful:
            log.warning("lbry://%s timed out, removing from streams", self.name)
            del self.daemon.streams[self.name]
            self.remove_from_wait("Timed out")
            raise Exception("Timed out")
        if self.wait_for_write:
            yield self._wait_for_write()
        defer.returnValue((sd_hash, download_path))

    def _wait_for_write(self):
        d = defer.succeed(None)
        if not self._has_downloader_wrote():
            d.addCallback(lambda _: reactor.callLater(1, self._wait_for_write))
        return d

    def _has_downloader_wrote(self):
        stream = self.daemon.streams.get(self.name, False)
        if stream:
            file_path = self._full_path(stream.downloader)
            return self._get_written_bytes(file_path)
        else:
            return False

    def _get_written_bytes(self, file_path):
        """Returns the number of bytes written to `file_path`.

        Returns False if there were issues reading `file_path`.
        """
        try:
            if os.path.isfile(file_path):
                with open(file_path) as written_file:
                    written_file.seek(0, os.SEEK_END)
                    written_bytes = written_file.tell()
            else:
                written_bytes = False
        except Exception:
            writen_bytes = False
        return written_bytes

    def remove_from_wait(self, reason):
        if self.name in self.daemon.waiting_on:
            del self.daemon.waiting_on[self.name]
        return reason


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


def loggly_time_string(dt):
    formatted_dt = dt.strftime("%Y-%m-%dT%H:%M:%S")
    milliseconds = str(round(dt.microsecond * (10.0 ** -5), 3))
    return urllib.quote_plus(formatted_dt + milliseconds + "Z")


def get_loggly_query_string(lbry_id):
    decoded_id = base58.b58encode(lbry_id)
    base_loggly_search_url = "https://lbry.loggly.com/search#"
    now = utils.now()
    yesterday = now - utils.timedelta(days=1)
    params = {
        'terms': 'json.lbry_id:{}*'.format(decoded_id[:SHORT_ID_LEN]),
        'from': loggly_time_string(yesterday),
        'to': loggly_time_string(now)
    }
    data = urllib.urlencode(params)
    return base_loggly_search_url + data


def report_bug_to_slack(message, lbry_id, platform_name, app_version):
    webhook = utils.deobfuscate(conf.settings['SLACK_WEBHOOK'])
    payload_template = "os: %s\n version: %s\n<%s|loggly>\n%s"
    payload_params = (
        platform_name,
        app_version,
        get_loggly_query_string(lbry_id),
        message
    )
    payload = {
        "text": payload_template % payload_params
    }
    requests.post(webhook, json.dumps(payload))


def get_lbry_file_search_value(p):
    for searchtype in (FileID.SD_HASH, FileID.NAME, FileID.FILE_NAME):
        value = p.get(searchtype)
        if value:
            return searchtype, value
    raise NoValidSearch('{} is missing a valid search type'.format(p))


def run_reflector_factory(factory):
    reflector_server = random.choice(conf.settings['reflector_servers'])
    reflector_address, reflector_port = reflector_server
    log.info("Start reflector client")
    d = reactor.resolve(reflector_address)
    d.addCallback(lambda ip: reactor.connectTCP(ip, reflector_port, factory))
    d.addCallback(lambda _: factory.finished_deferred)
    return d
