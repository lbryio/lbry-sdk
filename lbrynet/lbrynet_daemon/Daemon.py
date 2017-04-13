import binascii
import logging.handlers
import mimetypes
import os
import re
import base58
import requests
import urllib
import json
import textwrap
from requests import exceptions as requests_exceptions
import random

from twisted.web import server
from twisted.internet import defer, threads, error, reactor
from twisted.internet.task import LoopingCall
from twisted.python.failure import Failure

from lbryschema.claim import ClaimDict
from lbryschema.uri import parse_lbry_uri
from lbryschema.error import URIParseError

# TODO: importing this when internet is disabled raises a socket.gaierror
from lbryum.version import LBRYUM_VERSION
from lbrynet import __version__ as LBRYNET_VERSION
from lbrynet import conf, analytics
from lbrynet.conf import LBRYCRD_WALLET, LBRYUM_WALLET, PTC_WALLET
from lbrynet.reflector import reupload
from lbrynet.reflector import ServerFactory as reflector_server_factory
from lbrynet.metadata.Fee import FeeValidator
from lbrynet.metadata.Metadata import verify_name_characters

from lbrynet.lbryfile.client.EncryptedFileDownloader import EncryptedFileSaverFactory
from lbrynet.lbryfile.client.EncryptedFileDownloader import EncryptedFileOpenerFactory
from lbrynet.lbryfile.client.EncryptedFileOptions import add_lbry_file_to_sd_identifier
from lbrynet.lbryfile.EncryptedFileMetadataManager import DBEncryptedFileMetadataManager
from lbrynet.lbryfile.StreamDescriptor import EncryptedFileStreamType
from lbrynet.lbryfilemanager.EncryptedFileManager import EncryptedFileManager
from lbrynet.lbrynet_daemon.Downloader import GetStream
from lbrynet.lbrynet_daemon.Publisher import Publisher
from lbrynet.lbrynet_daemon.ExchangeRateManager import ExchangeRateManager
from lbrynet.lbrynet_daemon.auth.server import AuthJSONRPCServer
from lbrynet.core.PaymentRateManager import OnlyFreePaymentsManager
from lbrynet.core import log_support, utils, system_info
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier, download_sd_blob
from lbrynet.core.Session import Session
from lbrynet.core.Wallet import LBRYumWallet, SqliteStorage, ClaimOutpoint
from lbrynet.core.looping_call_manager import LoopingCallManager
from lbrynet.core.server.BlobRequestHandler import BlobRequestHandlerFactory
from lbrynet.core.server.ServerProtocol import ServerProtocolFactory
from lbrynet.core.Error import InsufficientFundsError, UnknownNameError, NoSuchSDHash
from lbrynet.core.Error import NoSuchStreamHash

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
CONNECTION_STATUS_NETWORK = 'network_connection'
CONNECTION_MESSAGES = {
    CONNECTION_STATUS_CONNECTED: 'No connection problems detected',
    CONNECTION_STATUS_NETWORK: "Your internet connection appears to have been interrupted",
}

SHORT_ID_LEN = 20


class IterableContainer(object):
    def __iter__(self):
        for attr in dir(self):
            if not attr.startswith("_"):
                yield getattr(self, attr)

    def __contains__(self, item):
        for attr in self:
            if item == attr:
                return True
        return False


class Checker:
    """The looping calls the daemon runs"""
    INTERNET_CONNECTION = 'internet_connection_checker'
    VERSION = 'version_checker'
    CONNECTION_STATUS = 'connection_status_checker'


class _FileID(IterableContainer):
    """The different ways a file can be identified"""
    NAME = 'name'
    SD_HASH = 'sd_hash'
    FILE_NAME = 'file_name'
    STREAM_HASH = 'stream_hash'
    CLAIM_ID = "claim_id"
    OUTPOINT = "outpoint"
    ROWID = "rowid"


FileID = _FileID()


# TODO add login credentials in a conf file
# TODO alert if your copy of a lbry file is out of date with the name record


class NoValidSearch(Exception):
    pass


class CheckInternetConnection(object):
    def __init__(self, daemon):
        self.daemon = daemon

    def __call__(self):
        self.daemon.connected_to_internet = utils.check_connection()


class CheckRemoteVersion(object):
    URL = 'https://api.github.com/repos/lbryio/lbry-app/releases/latest'

    def __init__(self):
        self.version = None

    def __call__(self):
        d = threads.deferToThread(self._get_lbry_electron_client_version)
        d.addErrback(self._trap_and_log_error, 'lbry-app')
        d.addErrback(log.fail(), 'Failure checking versions on github')

    def _trap_and_log_error(self, err, module_checked):
        # KeyError is thrown by get_version_from_github
        # It'd be better to catch the error before trying to parse the response
        err.trap(requests_exceptions.RequestException, KeyError)
        log.warning("Failed to check latest %s version from github", module_checked)

    def _get_lbry_electron_client_version(self):
        # We'll need to ensure the lbry-app version is in sync with the lbrynet-daemon version
        self._set_data_from_github()
        log.info(
            "remote lbrynet %s > local lbrynet %s = %s",
            self.version, LBRYNET_VERSION,
            utils.version_is_greater_than(self.version, LBRYNET_VERSION)
        )

    def _set_data_from_github(self):
        release = self._get_release_data()
        # githubs documentation claims this should never happen, but we'll check just in case
        if release['prerelease']:
            raise Exception('Release {} is a pre-release'.format(release['tag_name']))
        self.version = self._get_version_from_release(release)

    def _get_release_data(self):
        response = requests.get(self.URL, timeout=20)
        release = response.json()
        return release

    @staticmethod
    def _get_version_from_release(release):
        """Return the latest released version from github."""
        tag = release['tag_name']
        return get_version_from_tag(tag)

    def is_update_available(self):
        try:
            return utils.version_is_greater_than(self.version, LBRYNET_VERSION)
        except TypeError:
            return False


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
    blobs = yield defer.DeferredList([blob_manager.get_blob(b) for b in blob_hashes])
    defer.returnValue(sum(b.length for success, b in blobs if success and b.length))


class Daemon(AuthJSONRPCServer):
    """
    LBRYnet daemon, a jsonrpc interface to lbry functions
    """

    def __init__(self, root, analytics_manager):
        AuthJSONRPCServer.__init__(self, conf.settings['use_auth_http'])
        reactor.addSystemEventTrigger('before', 'shutdown', self._shutdown)

        self.allowed_during_startup = [
            'stop', 'status', 'version',
            # delete these once they are fully removed:
            'is_running', 'is_first_run', 'get_time_behind_blockchain', 'daemon_status',
            'get_start_notice',
        ]
        last_version = {'last_version': {'lbrynet': LBRYNET_VERSION, 'lbryum': LBRYUM_VERSION}}
        conf.settings.update(last_version)
        self.db_dir = conf.settings['data_dir']
        self.download_directory = conf.settings['download_directory']
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

        self.analytics_manager = analytics_manager
        self.lbryid = utils.generate_id()

        self.wallet_user = None
        self.wallet_password = None
        self.query_handlers = {}
        self.waiting_on = {}
        self.streams = {}
        self.name_cache = {}
        self.exchange_rate_manager = ExchangeRateManager()
        self._remote_version = CheckRemoteVersion()
        calls = {
            Checker.INTERNET_CONNECTION: LoopingCall(CheckInternetConnection(self)),
            Checker.VERSION: LoopingCall(self._remote_version),
            Checker.CONNECTION_STATUS: LoopingCall(self._update_connection_status),
        }
        self.looping_call_manager = LoopingCallManager(calls)
        self.sd_identifier = StreamDescriptorIdentifier()
        self.stream_info_manager = None
        self.lbry_file_manager = None

    @defer.inlineCallbacks
    def setup(self, launch_ui):
        self._modify_loggly_formatter()

        @defer.inlineCallbacks
        def _announce_startup():
            def _announce():
                self.announced_startup = True
                self.startup_status = STARTUP_STAGES[5]
                log.info("Started lbrynet-daemon")
                log.info("%i blobs in manager", len(self.session.blob_manager.blobs))

            yield self.session.blob_manager.get_all_verified_blobs()
            yield _announce()

        log.info("Starting lbrynet-daemon")

        self.looping_call_manager.start(Checker.INTERNET_CONNECTION, 3600)
        self.looping_call_manager.start(Checker.VERSION, 1800)
        self.looping_call_manager.start(Checker.CONNECTION_STATUS, 30)
        self.exchange_rate_manager.start()

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
        log.info("Starting balance: " + str(self.session.wallet.get_balance()))
        yield _announce_startup()

    def _get_platform(self):
        if self.platform is None:
            self.platform = system_info.get_platform()
        return self.platform

    def _initial_setup(self):
        def _log_platform():
            log.info("Platform: %s", json.dumps(self._get_platform()))
            return defer.succeed(None)

        d = _log_platform()
        return d

    def _load_caches(self):
        name_cache_filename = os.path.join(self.db_dir, "stream_info_cache.json")

        if os.path.isfile(name_cache_filename):
            with open(name_cache_filename, "r") as name_cache_file:
                name_cache = name_cache_file.read()
            try:
                self.name_cache = json.loads(name_cache)
                log.info("Loaded claim info cache")
            except ValueError:
                log.warning("Unable to load claim info cache")

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

        if not self.connected_to_internet:
            self.connection_status_code = CONNECTION_STATUS_NETWORK

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
                reflector_factory = reflector_server_factory(
                    self.session.peer_manager,
                    self.session.blob_manager
                )
                try:
                    self.reflector_server_port = reactor.listenTCP(self.reflector_port,
                                                                   reflector_factory)
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
                self.lbry_server_port, old_port = None, self.lbry_server_port
                log.info('Stop listening to %s', old_port)
                return defer.maybeDeferred(old_port.stopListening)
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

        self._clean_up_temp_files()

        d = self._stop_server()
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
            'download_timeout': int,
            'search_timeout': float,
            'cache_time': int,
            'share_debug_info': bool,
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
        if not os.path.exists(self.download_directory):
            os.mkdir(self.download_directory)
        if not os.path.exists(self.db_dir):
            os.mkdir(self.db_dir)
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
            installation_id=conf.settings.installation_id,
            session_id=self._session_id
        )

    @defer.inlineCallbacks
    def _setup_lbry_file_manager(self):
        log.info('Starting to setup up file manager')
        self.startup_status = STARTUP_STAGES[3]
        self.stream_info_manager = DBEncryptedFileMetadataManager(self.db_dir)
        yield self.stream_info_manager.setup()
        self.lbry_file_manager = EncryptedFileManager(
            self.session,
            self.stream_info_manager,
            self.sd_identifier,
            download_directory=self.download_directory
        )
        yield self.lbry_file_manager.setup()
        log.info('Done setting up file manager')

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

    def _download_blob(self, blob_hash, rate_manager=None, timeout=None):
        """
        Download a blob

        :param blob_hash (str): blob hash
        :param rate_manager (PaymentRateManager), optional: the payment rate manager to use,
                                                         defaults to session.payment_rate_manager
        :param timeout (int): blob timeout
        :return: BlobFile
        """

        def cb(blob):
            if not finished_d.called:
                finished_d.callback(blob)

        def eb():
            if not finished_d.called:
                finished_d.errback(Exception("Blob (%s) download timed out" %
                                              blob_hash[:SHORT_ID_LEN]))

        if not blob_hash:
            raise Exception("Nothing to download")

        rate_manager = rate_manager or self.session.payment_rate_manager
        timeout = timeout or 30
        finished_d = defer.Deferred(None)
        reactor.callLater(timeout, eb)
        d = download_sd_blob(self.session, blob_hash, rate_manager)
        d.addCallback(cb)
        return finished_d

    @defer.inlineCallbacks
    def _download_name(self, name, stream_info, claim_id, timeout=None, download_directory=None,
                       file_name=None):
        """
        Add a lbry file to the file manager, start the download, and return the new lbry file.
        If it already exists in the file manager, return the existing lbry file
        """

        if claim_id in self.streams:
            downloader = self.streams[claim_id]
            result = yield downloader.finished_deferred
            defer.returnValue(result)
        else:
            download_id = utils.random_string()
            self.analytics_manager.send_download_started(download_id, name, stream_info)

            self.streams[claim_id] = GetStream(self.sd_identifier, self.session,
                                               self.session.wallet, self.lbry_file_manager,
                                               self.exchange_rate_manager, self.max_key_fee,
                                               conf.settings['data_rate'], timeout,
                                               download_directory, file_name)
            try:
                download = self.streams[claim_id].start(stream_info, name)
                self.streams[claim_id].finished_deferred.addCallback(
                    lambda _: self.analytics_manager.send_download_finished(download_id,
                                                                            name,
                                                                            stream_info))
                lbry_file = yield download
                result = yield self._get_lbry_file_dict(lbry_file, full_status=True)
                del self.streams[claim_id]
            except Exception as err:
                log.warning('Failed to get %s: %s', name, err)
                self.analytics_manager.send_download_errored(download_id, name, stream_info)
                del self.streams[claim_id]
                result = {'error': err.message}
            defer.returnValue(result)

    @defer.inlineCallbacks
    def _publish_stream(self, name, bid, claim_dict, file_path=None, certificate_id=None):

        publisher = Publisher(self.session, self.lbry_file_manager, self.session.wallet,
                              certificate_id)
        verify_name_characters(name)
        if bid <= 0.0:
            raise Exception("Invalid bid")
        if not file_path:
            claim_out = yield publisher.publish_stream(name, bid, claim_dict)
        else:
            claim_out = yield publisher.create_and_publish_stream(name, bid, claim_dict, file_path)
            if conf.settings['reflect_uploads']:
                d = reupload.reflect_stream(publisher.lbry_file)
                d.addCallbacks(lambda _: log.info("Reflected new publication to lbry://%s", name),
                               log.exception)
        log.info("Success! Published to lbry://%s txid: %s nout: %d", name, claim_out['txid'],
                 claim_out['nout'])
        defer.returnValue(claim_out)

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
        return self.streams[name].start(stream_info, name)

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

    def _get_or_download_sd_blob(self, blob, sd_hash):
        if blob:
            return self.session.blob_manager.get_blob(blob[0])

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

    @defer.inlineCallbacks
    def get_est_cost_using_known_size(self, uri, size):
        """
        Calculate estimated LBC cost for a stream given its size in bytes
        """

        cost = self._get_est_cost_from_stream_size(size)

        resolved = yield self.session.wallet.resolve_uri(uri)
        if 'claim' in resolved:
            claim = ClaimDict.load_dict(resolved['claim']['value'])
            final_fee = self._add_key_fee_to_est_data_cost(claim.source_fee, cost)
            result = yield self._render_response(final_fee)
            defer.returnValue(result)
        else:
            defer.returnValue(None)

    def get_est_cost_from_sd_hash(self, sd_hash):
        """
        Get estimated cost from a sd hash
        """

        d = self.get_or_download_sd_blob(sd_hash)
        d.addCallback(self.get_size_from_sd_blob)
        d.addCallback(self._get_est_cost_from_stream_size)
        return d

    def _get_est_cost_from_metadata(self, metadata, name):
        d = self.get_est_cost_from_sd_hash(metadata.source_hash)

        def _handle_err(err):
            if isinstance(err, Failure):
                log.warning(
                    "Timeout getting blob for cost est for lbry://%s, using only key fee", name)
                return 0.0
            raise err

        d.addErrback(_handle_err)
        d.addCallback(lambda data_cost: self._add_key_fee_to_est_data_cost(metadata.source_fee,
                                                                           data_cost))
        return d

    def _add_key_fee_to_est_data_cost(self, fee, data_cost):
        fee_amount = 0.0 if not fee else self.exchange_rate_manager.to_lbc(fee).amount
        return data_cost + fee_amount

    @defer.inlineCallbacks
    def get_est_cost_from_uri(self, uri):
        """
        Resolve a name and return the estimated stream cost
        """
        try:
            claim_response = yield self.session.wallet.resolve_uri(uri)
        except Exception:
            claim_response = None

        result = None
        if claim_response and 'claim' in claim_response:
            if 'value' in claim_response['claim']:
                claim_value = ClaimDict.load_dict(claim_response['claim']['value'])
                cost = yield self._get_est_cost_from_metadata(claim_value, uri)
                result = round(cost, 5)
            else:
                log.warning("Failed to estimate cost for %s", uri)
        defer.returnValue(result)

    def get_est_cost(self, uri, size=None):
        """Get a cost estimate for a lbry stream, if size is not provided the
        sd blob will be downloaded to determine the stream size

        """

        if size is not None:
            return self.get_est_cost_using_known_size(uri, size)
        return self.get_est_cost_from_uri(uri)

    @defer.inlineCallbacks
    def _get_lbry_file_dict(self, lbry_file, full_status=False):
        key = binascii.b2a_hex(lbry_file.key) if lbry_file.key else None
        full_path = os.path.join(lbry_file.download_directory, lbry_file.file_name)
        mime_type = mimetypes.guess_type(full_path)[0]
        if os.path.isfile(full_path):
            with open(full_path) as written_file:
                written_file.seek(0, os.SEEK_END)
                written_bytes = written_file.tell()
        else:
            written_bytes = False

        if full_status:
            size = yield lbry_file.get_total_bytes()
            file_status = yield lbry_file.status()
            message = STREAM_STAGES[2][1] % (file_status.name, file_status.num_completed,
                                             file_status.num_known, file_status.running_status)
        else:
            size = None
            message = None

        claim = yield self.session.wallet.get_claim(lbry_file.claim_id)

        if claim and 'value' in claim:
            metadata = claim['value']
        else:
            metadata = None

        if claim and 'channel_name' in claim:
            channel_name = claim['channel_name']
        else:
            channel_name = None

        if lbry_file.txid and lbry_file.nout is not None:
            outpoint = repr(ClaimOutpoint(lbry_file.txid, lbry_file.nout))
        else:
            outpoint = None

        if claim and 'has_signature' in claim:
            has_signature = claim['has_signature']
        else:
            has_signature = None
        if claim and 'signature_is_valid' in claim:
            signature_is_valid = claim['signature_is_valid']
        else:
            signature_is_valid = None

        result = {
            'completed': lbry_file.completed,
            'file_name': lbry_file.file_name,
            'download_directory': lbry_file.download_directory,
            'points_paid': lbry_file.points_paid,
            'stopped': lbry_file.stopped,
            'stream_hash': lbry_file.stream_hash,
            'stream_name': lbry_file.stream_name,
            'suggested_file_name': lbry_file.suggested_file_name,
            'sd_hash': lbry_file.sd_hash,
            'name': lbry_file.name,
            'channel_name': channel_name,
            'outpoint': outpoint,
            'claim_id': lbry_file.claim_id,
            'download_path': full_path,
            'mime_type': mime_type,
            'key': key,
            'total_bytes': size,
            'written_bytes': written_bytes,
            'message': message,
            'metadata': metadata
        }
        if has_signature is not None:
            result['has_signature'] = has_signature
        if signature_is_valid is not None:
            result['signature_is_valid'] = signature_is_valid
        defer.returnValue(result)

    @defer.inlineCallbacks
    def _get_lbry_file(self, search_by, val, return_json=False, full_status=False):
        lbry_file = None
        if search_by in FileID:
            for l_f in self.lbry_file_manager.lbry_files:
                if l_f.__dict__.get(search_by) == val:
                    lbry_file = l_f
                    break
        else:
            raise NoValidSearch('{} is not a valid search operation'.format(search_by))
        if return_json and lbry_file:
            lbry_file = yield self._get_lbry_file_dict(lbry_file, full_status=full_status)
        defer.returnValue(lbry_file)

    @defer.inlineCallbacks
    def _get_lbry_files(self, return_json=False, full_status=False, **kwargs):
        lbry_files = list(self.lbry_file_manager.lbry_files)
        if kwargs:
            for search_type, value in iter_lbry_file_search_values(kwargs):
                lbry_files = [l_f for l_f in lbry_files if l_f.__dict__[search_type] == value]
        if return_json:
            file_dicts = []
            for lbry_file in lbry_files:
                lbry_file_dict = yield self._get_lbry_file_dict(lbry_file, full_status=full_status)
                file_dicts.append(lbry_file_dict)
            lbry_files = file_dicts
        log.info("Collected %i lbry files", len(lbry_files))
        defer.returnValue(lbry_files)

    # TODO: do this and get_blobs_for_sd_hash in the stream info manager
    def get_blobs_for_stream_hash(self, stream_hash):
        def _iter_blobs(blob_hashes):
            for blob_hash, blob_num, blob_iv, blob_length in blob_hashes:
                if blob_hash:
                    yield self.session.blob_manager.get_blob(blob_hash, length=blob_length)

        def _get_blobs(blob_hashes):
            dl = defer.DeferredList(list(_iter_blobs(blob_hashes)), consumeErrors=True)
            dl.addCallback(lambda blobs: [blob[1] for blob in blobs if blob[0]])
            return dl

        d = self.stream_info_manager.get_blobs_for_stream(stream_hash)
        d.addCallback(_get_blobs)
        return d

    def get_blobs_for_sd_hash(self, sd_hash):
        d = self.stream_info_manager.get_stream_hash_for_sd_hash(sd_hash)
        d.addCallback(self.get_blobs_for_stream_hash)
        return d

    ############################################################################
    #                                                                          #
    #                JSON-RPC API methods start here                           #
    #                                                                          #
    ############################################################################

    @defer.inlineCallbacks
    def jsonrpc_status(self, session_status=False):
        """
        Return daemon status

        Args:
            'session_status' (optional): (bool) true to return session status,
                default is false
        Returns:
            (dict) Daemon status dictionary
        """
        # on startup, the wallet or network won't be available but we still need this call to work
        has_wallet = self.session and self.session.wallet and self.session.wallet.network
        local_height = self.session.wallet.network.get_local_height() if has_wallet else 0
        remote_height = self.session.wallet.network.get_server_height() if has_wallet else 0
        best_hash = (yield self.session.wallet.get_best_blockhash()) if has_wallet else None

        response = {
            'lbry_id': base58.b58encode(self.lbryid)[:SHORT_ID_LEN],
            'installation_id': conf.settings.get_installation_id()[:SHORT_ID_LEN],
            'is_running': self.announced_startup,
            'is_first_run': self.session.wallet.is_first_run if has_wallet else None,
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
            'blocks_behind': remote_height - local_height,  # deprecated. remove from UI, then here
            'blockchain_status': {
                'blocks': local_height,
                'blocks_behind': remote_height - local_height,
                'best_blockhash': best_hash,
            }
        }
        if session_status:
            blobs = yield self.session.blob_manager.get_all_verified_blobs()
            response['session_status'] = {
                'managed_blobs': len(blobs),
                'managed_streams': len(self.lbry_file_manager.lbry_files),
            }
        defer.returnValue(response)

    def jsonrpc_get_best_blockhash(self):
        """
        DEPRECATED. Use `status blockchain_status=True` instead
        """
        d = self.jsonrpc_status()
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
                if status['blockchain_status']['blocks_behind'] > 0:
                    message += (
                        ' ' + str(status['blockchain_status']['blocks_behind']) + " blocks behind."
                    )
                    progress = status['blockchain_status']['blocks_behind']

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
        d = self.jsonrpc_status()
        d.addCallback(lambda x: self._render_response(x['is_first_run']))
        return d

    def jsonrpc_get_lbry_session_info(self):
        """
        DEPRECATED. Use `status` instead
        """

        d = self.jsonrpc_status(session_status=True)
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
        d = self.jsonrpc_status()
        d.addCallback(lambda x: self._render_response(x['blockchain_status']['blocks_behind']))
        return d

    def jsonrpc_version(self):
        """
        Get lbry version information

        Args:
            None
        Returns:
            (dict) Dictionary of lbry version information
            {
                'build': (str) build type (e.g. "dev", "rc", "release"),
                'ip': (str) remote ip, if available,
                'lbrynet_update_available': (bool) whether there's an update available,
                'lbrynet_version': (str) lbrynet_version,
                'lbryum_version': (str) lbryum_version,
                'os_release': (str) os release string
                'os_system': (str) os name
                'platform': (str) platform string
                'processor': (str) processor type,
                'python_version': (str) python version,
                'remote_lbrynet': (str) most recent lbrynet version available from github
            }
        """

        platform_info = self._get_platform()
        platform_info['remote_lbrynet'] = self._remote_version.version
        platform_info['lbrynet_update_available'] = self._remote_version.is_update_available()
        log.info("Get version info: " + json.dumps(platform_info))
        return self._render_response(platform_info)

    def jsonrpc_report_bug(self, message=None):
        """
        Report a bug to slack

        Args:
            'message': (str) message to send
        Returns:
            (bool) true if successful
        """

        platform_name = self._get_platform()['platform']
        report_bug_to_slack(
            message,
            conf.settings.installation_id,
            platform_name,
            LBRYNET_VERSION
        )
        return self._render_response(True)

    def jsonrpc_get_settings(self):
        """
        DEPRECATED. Use `settings_get` instead.
        """
        return self.jsonrpc_settings_get()

    def jsonrpc_settings_get(self):
        """
        Get daemon settings

        Returns:
            (dict) Dictionary of daemon settings
            See ADJUSTABLE_SETTINGS in lbrynet/conf.py for full list of settings
        """
        return self._render_response(conf.settings.get_adjustable_settings_dict())

    @AuthJSONRPCServer.auth_required
    def jsonrpc_set_settings(self, **kwargs):
        """
        DEPRECATED. Use `settings_set` instead.
        """
        return self.jsonrpc_settings_set(**kwargs)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_settings_set(self, **kwargs):
        """
        Set daemon settings

        Args:
            'run_on_startup': (bool) currently not supported
            'data_rate': (float) data rate,
            'max_key_fee': (float) maximum key fee,
            'download_directory': (str) path of where files are downloaded,
            'max_upload': (float), currently not supported
            'max_download': (float), currently not supported
            'download_timeout': (int) download timeout in seconds
            'search_timeout': (float) search timeout in seconds
            'cache_time': (int) cache timeout in seconds
        Returns:
            (dict) Updated dictionary of daemon settings
        """

        yield self._update_settings(kwargs)
        defer.returnValue(conf.settings.get_adjustable_settings_dict())

    def jsonrpc_help(self, command=None):
        """
        Return a useful message for an API command

        Args:
            'command'(optional): (str) command to retrieve documentation for
        Returns:
            (str) if given a command, returns documentation about that command
            otherwise returns general help message
        """

        if command is None:
            return self._render_response({
                'about': 'This is the LBRY JSON-RPC API',
                'command_help': 'Pass a `command` parameter to this method to see ' +
                                'help for that command (e.g. `help command=resolve_name`)',
                'command_list': 'Get a full list of commands using the `commands` method',
                'more_info': 'Visit https://lbry.io/api for more info',
            })

        fn = self.callable_methods.get(command)
        if fn is None:
            raise Exception(
                "No help available for '{}'. It is not a valid command.".format(command)
            )

        return self._render_response({
            'help': textwrap.dedent(fn.__doc__)
        })

    def jsonrpc_commands(self):
        """
        Return a list of available commands

        Returns:
            (list) list of available commands
        """
        return self._render_response(sorted(
            [command for command in self.callable_methods.keys()
             if 'DEPRECATED' not in getattr(self, "jsonrpc_" + command).__doc__]
        ))

    def jsonrpc_get_balance(self):
        """
        DEPRECATED. Use `wallet_balance` instead.
        """
        return self.jsonrpc_wallet_balance()

    def jsonrpc_wallet_balance(self):
        """
        Return the balance of the wallet

        Returns:
            (float) amount of lbry credits in wallet
        """
        return self._render_response(float(self.session.wallet.get_balance()))

    def jsonrpc_stop(self):
        """
        DEPRECATED. Use `daemon_stop` instead.
        """
        return self.jsonrpc_daemon_stop()

    def jsonrpc_daemon_stop(self):
        """
        Stop lbrynet-daemon

        Returns:
            (string) Shutdown message
        """

        def _display_shutdown_message():
            log.info("Shutting down lbrynet daemon")

        d = self._shutdown()
        d.addCallback(lambda _: _display_shutdown_message())
        d.addCallback(lambda _: reactor.callLater(0.0, reactor.stop))
        return self._render_response("Shutting down")

    @defer.inlineCallbacks
    def jsonrpc_file_list(self, **kwargs):
        """
        List files limited by optional filters

        Args:
            'name' (optional): (str) filter files by lbry name,
            'sd_hash' (optional): (str) filter files by sd hash,
            'file_name' (optional): (str) filter files by the name in the downloads folder,
            'stream_hash' (optional): (str) filter files by stream hash,
            'claim_id' (optional): (str) filter files by claim id,
            'outpoint' (optional): (str) filter files by claim outpoint,
            'rowid' (optional): (int) filter files by internal row id,
            'full_status': (optional): (bool) if true populate the 'message' and 'size' fields

        Returns:
            (list) List of files

            [
                {
                    'completed': (bool) true if download is completed,
                    'file_name': (str) name of file,
                    'download_directory': (str) download directory,
                    'points_paid': (float) credit paid to download file,
                    'stopped': (bool) true if download is stopped,
                    'stream_hash': (str) stream hash of file,
                    'stream_name': (str) stream name ,
                    'suggested_file_name': (str) suggested file name,
                    'sd_hash': (str) sd hash of file,
                    'name': (str) name claim attached to file
                    'outpoint': (str) claim outpoint attached to file
                    'claim_id': (str) claim ID attached to file,
                    'download_path': (str) download path of file,
                    'mime_type': (str) mime type of file,
                    'key': (str) key attached to file,
                    'total_bytes': (int) file size in bytes, None if full_status is false
                    'written_bytes': (int) written size in bytes
                    'message': (str), None if full_status is false
                    'metadata': (dict) Metadata dictionary
                },
            ]
        """

        result = yield self._get_lbry_files(return_json=True, **kwargs)
        response = yield self._render_response(result)
        defer.returnValue(response)

    @defer.inlineCallbacks
    def jsonrpc_resolve_name(self, name, force=False):
        """
        Resolve stream info from a LBRY name

        Args:
            'name': (str) name to look up, do not include lbry:// prefix
        Returns:
            (dict) Metadata dictionary from name claim, None if the name is not
                    resolvable
        """

        try:
            metadata = yield self._resolve_name(name, force_refresh=force)
        except UnknownNameError:
            log.info('Name %s is not known', name)
            defer.returnValue(None)
        else:
            defer.returnValue(metadata)

    def jsonrpc_get_claim_info(self, **kwargs):
        """
        DEPRECATED. Use `claim_show` instead.
        """
        return self.jsonrpc_claim_show(**kwargs)

    @defer.inlineCallbacks
    def jsonrpc_claim_show(self, name, txid=None, nout=None, claim_id=None):

        """
        Resolve claim info from a LBRY name

        Args:
            'name': (str) name to look up, do not include lbry:// prefix
            'txid'(optional): (str) if specified, look for claim with this txid
            'nout'(optional): (int) if specified, look for claim with this nout
            'claim_id'(optional): (str) if specified, look for claim with this claim_id
        Returns:
            (dict) Dictionary contaning claim info, (bool) false if claim is not
                resolvable

            {
                'txid': (str) txid of claim
                'nout': (int) nout of claim
                'amount': (float) amount of claim
                'value': (str) value of claim
                'height' : (int) height of claim takeover
                'claim_id': (str) claim ID of claim
                'supports': (list) list of supports associated with claim
            }
        """
        try:
            claim_results = yield self.session.wallet.get_claim_info(name, txid, nout, claim_id)
            result = format_json_out_amount_as_float(claim_results)
        except (TypeError, UnknownNameError):
            result = False
        response = yield self._render_response(result)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_resolve(self, uri):
        """
        Resolve a LBRY URI

        Args:
            'uri': (str) uri to download
        Returns:
            None if nothing can be resolved, otherwise:
            If uri resolves to a channel or a claim in a channel:
                'certificate': {
                    'address': (str) claim address,
                    'amount': (float) claim amount,
                    'effective_amount': (float) claim amount including supports,
                    'claim_id': (str) claim id,
                    'claim_sequence': (int) claim sequence number,
                    'decoded_claim': (bool) whether or not the claim value was decoded,
                    'height': (int) claim height,
                    'depth': (int) claim depth,
                    'has_signature': (bool) included if decoded_claim
                    'name': (str) claim name,
                    'supports: (list) list of supports [{'txid': txid,
                                                         'nout': nout,
                                                         'amount': amount}],
                    'txid': (str) claim txid,
                    'nout': (str) claim nout,
                    'signature_is_valid': (bool), included if has_signature,
                    'value': ClaimDict if decoded, otherwise hex string
                }
            If uri resolves to a channel:
                'claims_in_channel': [
                    {
                        'address': (str) claim address,
                        'amount': (float) claim amount,
                        'effective_amount': (float) claim amount including supports,
                        'claim_id': (str) claim id,
                        'claim_sequence': (int) claim sequence number,
                        'decoded_claim': (bool) whether or not the claim value was decoded,
                        'height': (int) claim height,
                        'depth': (int) claim depth,
                        'has_signature': (bool) included if decoded_claim
                        'name': (str) claim name,
                        'supports: (list) list of supports [{'txid': txid,
                                                             'nout': nout,
                                                             'amount': amount}],
                        'txid': (str) claim txid,
                        'nout': (str) claim nout,
                        'signature_is_valid': (bool), included if has_signature,
                        'value': ClaimDict if decoded, otherwise hex string
                    }
                ]
            If uri resolves to a claim:
                'claim': {
                    'address': (str) claim address,
                    'amount': (float) claim amount,
                    'effective_amount': (float) claim amount including supports,
                    'claim_id': (str) claim id,
                    'claim_sequence': (int) claim sequence number,
                    'decoded_claim': (bool) whether or not the claim value was decoded,
                    'height': (int) claim height,
                    'depth': (int) claim depth,
                    'has_signature': (bool) included if decoded_claim
                    'name': (str) claim name,
                    'channel_name': (str) channel name if claim is in a channel
                    'supports: (list) list of supports [{'txid': txid,
                                                         'nout': nout,
                                                         'amount': amount}]
                    'txid': (str) claim txid,
                    'nout': (str) claim nout,
                    'signature_is_valid': (bool), included if has_signature,
                    'value': ClaimDict if decoded, otherwise hex string
                }
            }
        """

        try:
            resolved = yield self.session.wallet.resolve_uri(uri)
        except Exception:
            resolved = None
        results = yield self._render_response(resolved)
        defer.returnValue(results)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_get(self, uri, file_name=None, timeout=None, download_directory=None):
        """
        Download stream from a LBRY name.

        Args:
            'uri': (str) lbry uri to download
            'file_name'(optional): (str) a user specified name for the downloaded file
            'timeout'(optional): (int) download timeout in number of seconds
            'download_directory'(optional): (str) path to directory where file will be saved
        Returns:
            (dict) Dictionary contaning information about the stream
            {
                'completed': (bool) true if download is completed,
                'file_name': (str) name of file,
                'download_directory': (str) download directory,
                'points_paid': (float) credit paid to download file,
                'stopped': (bool) true if download is stopped,
                'stream_hash': (str) stream hash of file,
                'stream_name': (str) stream name,
                'suggested_file_name': (str) suggested file name,
                'sd_hash': (str) sd hash of file,
                'name': (str) name claim attached to file
                'outpoint': (str) claim outpoint attached to file
                'claim_id': (str) claim ID attached to file,
                'download_path': (str) download path of file,
                'mime_type': (str) mime type of file,
                'key': (str) key attached to file,
                'total_bytes': (int) file size in bytes, None if full_status is false
                'written_bytes': (int) written size in bytes
                'message': (str), None if full_status is false
                'metadata': (dict) Metadata dictionary
            }
        """

        timeout = timeout if timeout is not None else self.download_timeout
        download_directory = download_directory or self.download_directory

        resolved = yield self.session.wallet.resolve_uri(uri)

        if 'value' not in resolved:
            if 'claim' not in resolved:
                raise Exception("Nothing to download")
            else:
                resolved = resolved['claim']

        name = resolved['name']
        claim_id = resolved['claim_id']
        stream_info = resolved['value']

        if claim_id in self.streams:
            log.info("Already waiting on lbry://%s to start downloading", name)
            yield self.streams[claim_id].data_downloading_deferred

        lbry_file = yield self._get_lbry_file(FileID.CLAIM_ID, claim_id, return_json=False)

        if lbry_file:
            if not os.path.isfile(os.path.join(lbry_file.download_directory, lbry_file.file_name)):
                log.info("Already have lbry file but missing file in %s, rebuilding it",
                         lbry_file.download_directory)
                yield lbry_file.start()
            else:
                log.info('Already have a file for %s', name)
            result = yield self._get_lbry_file_dict(lbry_file, full_status=True)
        else:
            result = yield self._download_name(name, stream_info, claim_id, timeout=timeout,
                                               download_directory=download_directory,
                                               file_name=file_name)
        response = yield self._render_response(result)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_stop_lbry_file(self, **kwargs):
        """
        DEPRECATED. Use `file_set_status status=stop` instead.
        """
        return self.jsonrpc_file_set_status(status='stop', **kwargs)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_start_lbry_file(self, **kwargs):
        """
        DEPRECATED. Use `file_set_status status=start` instead.
        """
        return self.jsonrpc_file_set_status(status='start', **kwargs)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_file_set_status(self, status, **kwargs):
        """
        Start or stop downloading a file

        Args:
            'status': (str) "start" or "stop"
            'name' (optional): (str) start file by lbry name,
            'sd_hash' (optional): (str) start file by the hash in the name claim,
            'file_name' (optional): (str) start file by its name in the downloads folder,
        Returns:
            (str) Confirmation message
        """

        if status not in ['start', 'stop']:
            raise Exception('Status must be "start" or "stop".')

        search_type, value = get_lbry_file_search_value(kwargs)
        lbry_file = yield self._get_lbry_file(search_type, value, return_json=False)
        if not lbry_file:
            raise Exception('Unable to find a file for {}:{}'.format(search_type, value))

        if status == 'start' and lbry_file.stopped or status == 'stop' and not lbry_file.stopped:
            yield self.lbry_file_manager.toggle_lbry_file_running(lbry_file)
            msg = "Started downloading file" if status == 'start' else "Stopped downloading file"
        else:
            msg = (
                "File was already being downloaded" if status == 'start'
                    else "File was already stopped"
            )
        response = yield self._render_response(msg)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_file_delete(self, delete_target_file=True, delete_all=False, **kwargs):
        """
        Delete a lbry file

        Args:
            'name' (optional): (str) delete file by lbry name,
            'sd_hash' (optional): (str) delete file by sd hash,
            'file_name' (optional): (str) delete file by the name in the downloads folder,
            'stream_hash' (optional): (str) delete file by stream hash,
            'claim_id' (optional): (str) delete file by claim ID,
            'outpoint' (optional): (str) delete file by claim outpoint,
            'rowid': (optional): (int) delete file by rowid in the file manager
            'delete_target_file' (optional): (bool) delete file from downloads folder,
                                            defaults to true if false only the blobs and
                                            db entries will be deleted
        Returns:
            (bool) true if deletion was successful
        """

        lbry_files = yield self._get_lbry_files(return_json=False, **kwargs)

        if len(lbry_files) > 1:
            if not delete_all:
                log.warning("There are %i files to delete, use narrower filters to select one",
                            len(lbry_files))
                result = False
            else:
                log.warning("Deleting %i files",
                            len(lbry_files))

        if not lbry_files:
            log.warning("There is no file to delete")
            result = False
        else:
            for lbry_file in lbry_files:
                file_name, stream_hash = lbry_file.file_name, lbry_file.stream_hash
                if lbry_file.claim_id in self.streams:
                    del self.streams[lbry_file.claim_id]
                yield self.lbry_file_manager.delete_lbry_file(lbry_file,
                                                              delete_file=delete_target_file)
                log.info("Deleted %s (%s)", file_name, utils.short_hash(stream_hash))
            result = True
        response = yield self._render_response(result)
        defer.returnValue(response)

    def jsonrpc_get_est_cost(self, **kwargs):
        """
        DEPRECATED. Use `stream_cost_estimate` instead
        """
        return self.jsonrpc_stream_cost_estimate(**kwargs)

    @defer.inlineCallbacks
    def jsonrpc_stream_cost_estimate(self, uri, size=None):
        """
        Get estimated cost for a lbry stream

        Args:
            'name': (str) lbry name
            'size' (optional): (int) stream size, in bytes. if provided an sd blob
                                won't be downloaded.
        Returns:
            (float) Estimated cost in lbry credits
        """
        cost = yield self.get_est_cost(uri, size)
        defer.returnValue(cost)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_channel_new(self, channel_name, amount):
        """
        Generate a publisher key and create a new certificate claim

        Args:
            'channel_name': (str) '@' prefixed name
            'amount': (float) amount to claim name

        Returns:
            (dict) Dictionary containing result of the claim
            {
                'tx' : (str) hex encoded transaction
                'txid' : (str) txid of resulting claim
                'nout' : (int) nout of the resulting claim
                'fee' : (float) fee paid for the claim transaction
                'claim_id' : (str) claim ID of the resulting claim
            }
        """

        try:
            parsed = parse_lbry_uri(channel_name)
            if not parsed.is_channel:
                raise Exception("Cannot make a new channel for a non channel name")
            if parsed.path:
                raise Exception("Invalid channel uri")
        except (TypeError, URIParseError):
            raise Exception("Invalid channel name")
        if amount <= 0:
            raise Exception("Invalid amount")
        if amount > self.session.wallet.get_balance():
            raise InsufficientFundsError()

        result = yield self.session.wallet.claim_new_channel(channel_name, amount)
        log.info("Claimed a new channel! Result: %s", result)
        response = yield self._render_response(result)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_channel_list_mine(self):
        """
        Get my channels

        Returns:
            (list) ClaimDict
        """

        result = yield self.session.wallet.channel_list()
        response = yield self._render_response(result)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_publish(self, name, bid, metadata=None, file_path=None, fee=None, title=None,
                        description=None, author=None, language=None, license=None,
                        license_url=None, thumbnail=None, preview=None, nsfw=None, sources=None,
                        channel_name=None):
        """
        Make a new name claim and publish associated data to lbrynet,
        update over existing claim if user already has a claim for name.

        Fields required in the final Metadata are:
            'title'
            'description'
            'author'
            'language'
            'license',
            'nsfw'

        Metadata can be set by either using the metadata argument or by setting individual arguments
        fee, title, description, author, language, license, license_url, thumbnail, preview, nsfw,
        or sources. Individual arguments will overwrite the fields specified in metadata argument.

        Args:
            'name': (str) name to be claimed
            'bid': (float) amount of credits to commit in this claim,
            'metadata'(optional): (dict) Metadata to associate with the claim.
            'file_path'(optional): (str) path to file to be associated with name. If provided,
                                    a lbry stream of this file will be used in 'sources'.
                                    If no path is given but a metadata dict is provided, the source
                                    from the given metadata will be used.
            'fee'(optional): (dict) Dictionary representing key fee to download content:
                              {currency_symbol: {'amount': float, 'address': str, optional}}
                              supported currencies: LBC, USD, BTC
                              If an address is not provided a new one will be automatically
                              generated. Default fee is zero.
            'title'(optional): (str) title of the file
            'description'(optional): (str) description of the file
            'author'(optional): (str) author of the file
            'language'(optional): (str), language code
            'license'(optional): (str) license for the file
            'license_url'(optional): (str) URL to license
            'thumbnail'(optional): (str) thumbnail URL for the file
            'preview'(optional): (str) preview URL for the file
            'nsfw'(optional): (bool) True if not safe for work
            'sources'(optional): (dict){'lbry_sd_hash':sd_hash} specifies sd hash of file
            'channel_name' (optional): (str) name of the publisher channel

        Returns:
            (dict) Dictionary containing result of the claim
            {
                'tx' : (str) hex encoded transaction
                'txid' : (str) txid of resulting claim
                'nout' : (int) nout of the resulting claim
                'fee' : (float) fee paid for the claim transaction
                'claim_id' : (str) claim ID of the resulting claim
            }
        """

        try:
            parse_lbry_uri(name)
        except (TypeError, URIParseError):
            raise Exception("Invalid name given to publish")

        if bid <= 0.0:
            raise Exception("Invalid bid")

        if bid > self.session.wallet.get_balance():
            raise InsufficientFundsError()

        metadata = metadata or {}
        if fee is not None:
            metadata['fee'] = fee
        if title is not None:
            metadata['title'] = title
        if description is not None:
            metadata['description'] = description
        if author is not None:
            metadata['author'] = author
        if language is not None:
            metadata['language'] = language
        if license is not None:
            metadata['license'] = license
        if license_url is not None:
            metadata['license_url'] = license_url
        if thumbnail is not None:
            metadata['thumbnail'] = thumbnail
        if preview is not None:
            metadata['preview'] = preview
        if nsfw is not None:
            metadata['nsfw'] = bool(nsfw)

        metadata['version'] = '_0_1_0'

        # original format {'currency':{'address','amount'}}
        # add address to fee if unspecified {'version': ,'currency', 'address' , 'amount'}
        if 'fee' in metadata:
            new_fee_dict = {}
            assert len(metadata['fee']) == 1, "Too many fees"
            currency, fee_dict = metadata['fee'].items()[0]
            if 'address' not in fee_dict:
                address = yield self.session.wallet.get_new_address()
            else:
                address = fee_dict['address']
            new_fee_dict = {
                'version': '_0_0_1',
                'currency': currency,
                'address': address,
                'amount': fee_dict['amount']
            }
            metadata['fee'] = new_fee_dict

        log.info("Publish: %s", {
            'name': name,
            'file_path': file_path,
            'bid': bid,
            'metadata': metadata,
            'fee': fee,
        })

        claim_dict = {
            'version': '_0_0_1',
            'claimType': 'streamType',
            'stream': {
                'metadata': metadata,
                'version': '_0_0_1'
            }
        }

        if sources is not None:
            claim_dict['stream']['source'] = sources

        if channel_name:
            certificate_id = None
            my_certificates = yield self.session.wallet.channel_list()
            for certificate in my_certificates:
                if channel_name == certificate['name']:
                    certificate_id = certificate['claim_id']
                    break
            if not certificate_id:
                raise Exception("Cannot publish using channel %s" % channel_name)
        else:
            certificate_id = None

        result = yield self._publish_stream(name, bid, claim_dict, file_path, certificate_id)
        response = yield self._render_response(result)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_abandon_claim(self, **kwargs):
        """
        DEPRECATED. Use `claim_abandon` instead
        """
        return self.jsonrpc_claim_abandon(**kwargs)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_claim_abandon(self, claim_id):
        """
        Abandon a name and reclaim credits from the claim

        Args:
            'claim_id': (str) claim_id of claim
        Return:
            (dict) Dictionary containing result of the claim
            {
                txid : (str) txid of resulting transaction
                fee : (float) fee paid for the transaction
            }
        """

        try:
            abandon_claim_tx = yield self.session.wallet.abandon_claim(claim_id)
            response = yield self._render_response(abandon_claim_tx)
        except BaseException as err:
            log.warning(err)
            # pylint: disable=unsubscriptable-object
            if len(err.args) and err.args[0] == "txid was not found in wallet":
                raise Exception("This transaction was not found in your wallet")
            else:
                response = yield self._render_response(err)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_abandon_name(self, **kwargs):
        """
        DEPRECATED, use abandon_claim
        """

        return self.jsonrpc_abandon_claim(**kwargs)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_support_claim(self, **kwargs):
        """
        DEPRECATED. Use `claim_abandon` instead
        """
        return self.jsonrpc_claim_new_support(**kwargs)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_claim_new_support(self, name, claim_id, amount):
        """
        Support a name claim

        Args:
            'name': (str) name
            'claim_id': (str) claim ID of claim to support
            'amount': (float) amount to support by
        Return:
            (dict) Dictionary containing result of the claim
            {
                txid : (str) txid of resulting support claim
                nout : (int) nout of the resulting support claim
                fee : (float) fee paid for the transaction
            }
        """

        d = self.session.wallet.support_claim(name, claim_id, amount)
        d.addCallback(lambda r: self._render_response(r))
        return d

    # TODO: merge this into claim_list
    @AuthJSONRPCServer.auth_required
    def jsonrpc_get_my_claim(self, name):
        """
        DEPRECATED. This method will be removed in a future release.

        Return existing claim for a given name

        Args:
            'name': name to look up
        Returns:
            claim info, false if no such claim exists
        """

        d = self.session.wallet.get_my_claim(name)
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
            (list) List of name claims owned by user
            [
                {
                    'address': (str) address that owns the claim
                    'amount': (float) amount assigned to the claim
                    'blocks_to_expiration': (int) number of blocks until it expires
                    'category': (str) "claim", "update" , or "support"
                    'claim_id': (str) claim ID of the claim
                    'confirmations': (int) number of blocks of confirmations for the claim
                    'expiration_height': (int) the block height which the claim will expire
                    'expired': (bool) true if expired, false otherwise
                    'height': (int) height of the block containing the claim
                    'is_spent': (bool) true if claim is abandoned, false otherwise
                    'name': (str) name of the claim
                    'txid': (str) txid of the cliam
                    'nout': (int) nout of the claim
                    'value': (str) value of the claim
                },
           ]
        """

        d = self.session.wallet.get_name_claims()
        d.addCallback(format_json_out_amount_as_float)
        d.addCallback(lambda claims: self._render_response(claims))
        return d

    def jsonrpc_get_claims_for_name(self, **kwargs):
        """
        DEPRECATED. Use `claim_list` instead.
        """
        return self.jsonrpc_claim_list(**kwargs)

    def jsonrpc_get_claims_for_tx(self, **kwargs):
        """
        DEPRECATED. Use `claim_list` instead.
        """
        return self.jsonrpc_claim_list(**kwargs)

    @defer.inlineCallbacks
    def jsonrpc_claim_list(self, name):
        """
        Get claims for a name

        Args:
            'name': (str) search for claims on this name
        Returns
            (dict) State of claims assigned for the name
            {
                'claims': (list) list of claims for the name
                [
                    {
                    'amount': (float) amount assigned to the claim
                    'effective_amount': (float) total amount assigned to the claim,
                                        including supports
                    'claim_id': (str) claim ID of the claim
                    'height': (int) height of block containing the claim
                    'txid': (str) txid of the claim
                    'nout': (int) nout of the claim
                    'supports': (list) a list of supports attached to the claim
                    'value': (str) the value of the claim
                    },
                ]
                'supports_without_claims': (list) supports without any claims attached to them
                'last_takeover_height': (int) the height of last takeover for the name
            }
        """

        claims = yield self.session.wallet.get_claims_for_name(name)
        defer.returnValue(claims)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_get_transaction_history(self):
        """
        DEPRECATED. Use `transaction_list` instead
        """
        return self.jsonrpc_transaction_list()

    @AuthJSONRPCServer.auth_required
    def jsonrpc_transaction_list(self):
        """
        List transactions belonging to wallet

        Args:
            None
        Returns:
            (list) List of transactions
        """

        d = self.session.wallet.get_history()
        d.addCallback(lambda r: self._render_response(r))
        return d

    def jsonrpc_get_transaction(self, txid):
        """
        DEPRECATED. Use `transaction_show` instead
        """
        return self.jsonrpc_transaction_show(txid)

    def jsonrpc_transaction_show(self, txid):
        """
        Get a decoded transaction from a txid

        Args:
            'txid': (str) txid of transaction
        Returns:
            (dict) JSON formatted transaction
        """

        d = self.session.wallet.get_transaction(txid)
        d.addCallback(lambda r: self._render_response(r))
        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_address_is_mine(self, address):
        """
        DEPRECATED. Use `wallet_is_address_mine` instead
        """
        return self.jsonrpc_wallet_is_address_mine(address)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_wallet_is_address_mine(self, address):
        """
        Checks if an address is associated with the current wallet.

        Args:
            'address': (str) address to check in base58
        Returns:
            (bool) true, if address is associated with current wallet
        """

        d = self.session.wallet.address_is_mine(address)
        d.addCallback(lambda is_mine: self._render_response(is_mine))
        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_get_public_key_from_wallet(self, wallet):
        """
        DEPRECATED. Use `wallet_is_address_mine` instead
        """
        return self.jsonrpc_wallet_public_key(wallet)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_wallet_public_key(self, address):
        """
        Get public key from wallet address

        Args:
            'address': (str) wallet address in base58
        Returns:
            (list) list of public keys associated with address.
                Could contain more than one public key if multisig.
        """

        d = self.session.wallet.get_pub_keys(address)
        d.addCallback(lambda r: self._render_response(r))
        return d

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_wallet_list(self):
        """
        List wallet addresses

        Args:
            None
        Returns:
            List of wallet addresses
        """

        addresses = yield self.session.wallet.list_addresses()
        response = yield self._render_response(addresses)
        defer.returnValue(response)

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
            (str) New wallet address in base58
        """

        def _disp(address):
            log.info("Got new wallet address: " + address)
            return defer.succeed(address)

        d = self.session.wallet.get_new_address()
        d.addCallback(_disp)
        d.addCallback(lambda address: self._render_response(address))
        return d


    @AuthJSONRPCServer.auth_required
    def jsonrpc_wallet_unused_address(self):
        """
        Return an address containing no balance, will create
        a new address if there is none.

        Args:
            None
        Returns:
            (str) Unused wallet address in base58
        """

        def _disp(address):
            log.info("Got unused wallet address: " + address)
            return defer.succeed(address)

        d = self.session.wallet.get_unused_address()
        d.addCallback(_disp)
        d.addCallback(lambda address: self._render_response(address))
        return d


    @AuthJSONRPCServer.auth_required
    def jsonrpc_send_amount_to_address(self, amount, address):
        """
        Send credits to an address

        Args:
            'amount': (float) the amount to send
            'address': (str) the address of the recipient in base58
        Returns:
            (bool) true if payment successfully scheduled
        """

        reserved_points = self.session.wallet.reserve_points(address, amount)
        if reserved_points is None:
            return defer.fail(InsufficientFundsError())
        d = self.session.wallet.send_points_to_address(reserved_points, amount)
        d.addCallback(lambda _: self._render_response(True))
        return d

    def jsonrpc_get_block(self, **kwargs):
        """
        DEPRECATED. Use `block_show` instead
        """
        return self.jsonrpc_block_show(**kwargs)

    def jsonrpc_block_show(self, blockhash=None, height=None):
        """
        Get contents of a block

        Args:
            'blockhash': (str) hash of the block to look up
        Returns:
            (dict) Requested block
        """

        if blockhash is not None:
            d = self.session.wallet.get_block(blockhash)
        elif height is not None:
            d = self.session.wallet.get_block_info(height)
            d.addCallback(lambda b: self.session.wallet.get_block(b))
        else:
            # TODO: return a useful error message
            return server.failure

        d.addCallback(lambda r: self._render_response(r))
        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_download_descriptor(self, **kwargs):
        """
        DEPRECATED. Use `descriptor_get` instead
        """
        return self.jsonrpc_descriptor_get(**kwargs)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_descriptor_get(self, sd_hash, timeout=None, payment_rate_manager=None):
        """
        Download and return a sd blob

        Args:
            'sd_hash': (str) hash of sd blob
            'timeout'(optional): (int) timeout in number of seconds
            'payment_rate_manager'(optional): (str) if not given the default payment rate manager
                                             will be used. supported alternative rate managers:
                                             only-free

        Returns
            (str) Success/Fail message or (dict) decoded data
        """
        return self.jsonrpc_blob_get(sd_hash, timeout, 'json', payment_rate_manager)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_blob_get(self, blob_hash, timeout=None, encoding=None, payment_rate_manager=None):
        """
        Download and return a blob

        Args:
            'blob_hash': (str) blob hash of blob to get
            'timeout'(optional): (int) timeout in number of seconds
            'encoding'(optional): (str) by default no attempt at decoding is made,
                                 can be set to one of the following decoders:
                                 'json'
            'payment_rate_manager'(optional): if not given the default payment rate manager
                                             will be used. supported alternative rate managers:
                                             'only-free'

        Returns
            (str) Success/Fail message or (dict) decoded data
        """

        decoders = {
            'json': json.loads
        }

        timeout = timeout or 30
        payment_rate_manager = get_blob_payment_rate_manager(self.session, payment_rate_manager)
        blob = yield self._download_blob(blob_hash, rate_manager=payment_rate_manager,
                                         timeout=timeout)
        if encoding and encoding in decoders:
            blob_file = blob.open_for_reading()
            result = decoders[encoding](blob_file.read())
            blob.close_read_handle(blob_file)
        else:
            result = "Downloaded blob %s" % blob_hash

        response = yield self._render_response(result)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_blob_delete(self, blob_hash):
        """
        Delete a blob

        Args:
            'blob_hash': (str) hash of blob to get
        Returns:
            (str) Success/fail message
        """

        if blob_hash not in self.session.blob_manager.blobs:
            response = yield self._render_response("Don't have that blob")
            defer.returnValue(response)
        try:
            stream_hash = yield self.stream_info_manager.get_stream_hash_for_sd_hash(blob_hash)
            yield self.stream_info_manager.delete_stream(stream_hash)
        except Exception as err:
            pass
        yield self.session.blob_manager.delete_blobs([blob_hash])
        response = yield self._render_response("Deleted %s" % blob_hash)
        defer.returnValue(response)

    def jsonrpc_get_peers_for_hash(self, blob_hash):
        """
        DEPRECATED. Use `peer_list` instead
        """
        return self.jsonrpc_peer_list(blob_hash)

    def jsonrpc_peer_list(self, blob_hash, timeout=None):
        """
        Get peers for blob hash

        Args:
            'blob_hash': (str) blob hash
            'timeout'(optional): (int) peer search timeout in seconds
        Returns:
            (list) List of contacts
        """

        timeout = timeout or conf.settings['peer_search_timeout']

        d = self.session.peer_finder.find_peers_for_blob(blob_hash, timeout=timeout)
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
            (str) Success/fail message
        """

        d = self.session.blob_manager.immediate_announce_all_blobs()
        d.addCallback(lambda _: self._render_response("Announced"))
        return d

    @defer.inlineCallbacks
    def jsonrpc_reflect(self, sd_hash):
        """
        Reflect a stream

        Args:
            'sd_hash': (str) sd_hash of lbry file
        Returns:
            (bool) true if successful
        """

        lbry_file = yield self._get_lbry_file(FileID.SD_HASH, sd_hash, return_json=False)
        if lbry_file is None:
            raise Exception('No file found for give sd hash')
        yield reupload.reflect_stream(lbry_file)
        defer.returnValue("Reflect success")

    def jsonrpc_get_blob_hashes(self):
        """
        DEPRECATED. Use `blob_list` instead
        """
        return self.jsonrpc_blob_list()

    @defer.inlineCallbacks
    def jsonrpc_blob_list(self, uri=None, stream_hash=None, sd_hash=None, needed=None,
                          finished=None, page_size=None, page=None):
        """
        Returns blob hashes. If not given filters, returns all blobs known by the blob manager

        Args:
            'uri' (optional): (str) filter by blobs in stream for winning claim
            'stream_hash' (optional): (str) filter by blobs in given stream hash
            'sd_hash' (optional): (str) filter by blobs in given sd hash
            'needed' (optional): (bool) only return needed blobs
            'finished' (optional): (bool) only return finished blobs
            'page_size' (optional): (int) limit number of results returned
            'page' (optional): (int) filter to page x of [page_size] results
        Returns:
            (list) List of blob hashes
        """

        if uri:
            metadata = yield self._resolve_name(uri)
            sd_hash = utils.get_sd_hash(metadata)
            blobs = yield self.get_blobs_for_sd_hash(sd_hash)
        elif stream_hash:
            try:
                blobs = yield self.get_blobs_for_stream_hash(stream_hash)
            except NoSuchStreamHash:
                blobs = []
        elif sd_hash:
            try:
                blobs = yield self.get_blobs_for_sd_hash(sd_hash)
            except NoSuchSDHash:
                blobs = []
        else:
            blobs = self.session.blob_manager.blobs.itervalues()

        if needed:
            blobs = [blob for blob in blobs if not blob.is_validated()]
        if finished:
            blobs = [blob for blob in blobs if blob.is_validated()]

        blob_hashes = [blob.blob_hash for blob in blobs]
        page_size = page_size or len(blob_hashes)
        page = page or 0
        start_index = page * page_size
        stop_index = start_index + page_size
        blob_hashes_for_return = blob_hashes[start_index:stop_index]
        response = yield self._render_response(blob_hashes_for_return)
        defer.returnValue(response)

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
            (bool) true if successful
        """

        d = self.session.blob_manager.get_all_verified_blobs()
        d.addCallback(reupload.reflect_blob_hashes, self.session.blob_manager)
        d.addCallback(lambda r: self._render_response(r))
        return d

    @defer.inlineCallbacks
    def jsonrpc_get_availability(self, uri, sd_timeout=None, peer_timeout=None):
        """
        Get stream availability for lbry uri

        Args:
            'uri' : (str) lbry uri
            'sd_timeout' (optional): (int) sd blob download timeout
            'peer_timeout' (optional): (int) how long to look for peers

        Returns:
            (float) Peers per blob / total blobs
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

        def read_sd_blob(sd_blob):
            sd_blob_file = sd_blob.open_for_reading()
            decoded_sd_blob = json.loads(sd_blob_file.read())
            sd_blob.close_read_handle(sd_blob_file)
            return decoded_sd_blob

        try:
            resolved = yield self.session.wallet.resolve_uri(uri)
        except Exception:
            defer.returnValue(None)

        if resolved and 'claim' in resolved:
            metadata = resolved['claim']['value']
        else:
            defer.returnValue(None)

        sd_hash = utils.get_sd_hash(metadata)
        sd_timeout = sd_timeout or conf.settings['sd_download_timeout']
        peer_timeout = peer_timeout or conf.settings['peer_search_timeout']
        blobs = []
        try:
            blobs = yield self.get_blobs_for_sd_hash(sd_hash)
            need_sd_blob = False
            log.info("Already have sd blob")
        except NoSuchSDHash:
            need_sd_blob = True
            log.info("Need sd blob")

        blob_hashes = [blob.blob_hash for blob in blobs]
        if need_sd_blob:
            # we don't want to use self._download_descriptor here because it would create a stream
            try:
                sd_blob = yield self._download_blob(sd_hash, timeout=sd_timeout)
            except Exception as err:
                response = yield self._render_response(0.0)
                log.warning(err)
                defer.returnValue(response)
            decoded = read_sd_blob(sd_blob)
            blob_hashes = [blob.get("blob_hash") for blob in decoded['blobs']
                           if blob.get("blob_hash")]
        sample = random.sample(blob_hashes, min(len(blob_hashes), 5))
        log.info("check peers for %i of %i blobs in stream", len(sample), len(blob_hashes))
        availabilities = yield self.session.blob_tracker.get_availability_for_blobs(sample,
                                                                                    peer_timeout)
        mean_availability = _get_mean(availabilities)
        response = yield self._render_response(mean_availability)
        defer.returnValue(response)

    def jsonrpc_get_start_notice(self):
        """
        DEPRECATED.

        Get special message to be displayed at startup
        Args:
            None
        Returns:
            (str) Startup message, such as first run notification
        """

        def _get_startup_message(status):
            if status['is_first_run'] and self.session.wallet.wallet_balance:
                return self._render_response(None)
            else:
                return self._render_response(status['startup_status']['message'])

        d = self.jsonrpc_status()
        d.addCallback(_get_startup_message)
        return d


class _ResolveNameHelper(object):
    def __init__(self, daemon, name, force_refresh):
        self.daemon = daemon
        self.name = name
        self.force_refresh = force_refresh

    def get_deferred(self):
        if self.need_fresh_stream():
            log.info("Resolving stream info for lbry://%s", self.name)
            d = self.wallet.get_claim_by_name(self.name)
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
            'claim_metadata': stream_info['value'],
            'timestamp': self.now()
        }
        d = self._add_txid(stream_info['txid'])
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


def loggly_time_string(dt):
    formatted_dt = dt.strftime("%Y-%m-%dT%H:%M:%S")
    milliseconds = str(round(dt.microsecond * (10.0 ** -5), 3))
    return urllib.quote_plus(formatted_dt + milliseconds + "Z")


def get_loggly_query_string(installation_id):
    base_loggly_search_url = "https://lbry.loggly.com/search#"
    now = utils.now()
    yesterday = now - utils.timedelta(days=1)
    params = {
        'terms': 'json.installation_id:{}*'.format(installation_id[:SHORT_ID_LEN]),
        'from': loggly_time_string(yesterday),
        'to': loggly_time_string(now)
    }
    data = urllib.urlencode(params)
    return base_loggly_search_url + data


def report_bug_to_slack(message, installation_id, platform_name, app_version):
    webhook = utils.deobfuscate(conf.settings['SLACK_WEBHOOK'])
    payload_template = "os: %s\n version: %s\n<%s|loggly>\n%s"
    payload_params = (
        platform_name,
        app_version,
        get_loggly_query_string(installation_id),
        message
    )
    payload = {
        "text": payload_template % payload_params
    }
    requests.post(webhook, json.dumps(payload))


def get_lbry_file_search_value(search_fields):
    for searchtype in FileID:
        value = search_fields.get(searchtype, None)
        if value is not None:
            return searchtype, value
    raise NoValidSearch('{} is missing a valid search type'.format(search_fields))


def iter_lbry_file_search_values(search_fields):
    for searchtype in FileID:
        value = search_fields.get(searchtype, None)
        if value is not None:
            yield searchtype, value


def get_blob_payment_rate_manager(session, payment_rate_manager=None):
    if payment_rate_manager:
        rate_managers = {
            'only-free': OnlyFreePaymentsManager()
        }
        if payment_rate_manager in rate_managers:
            payment_rate_manager = rate_managers[payment_rate_manager]
            log.info("Downloading blob with rate manager: %s", payment_rate_manager)
    return payment_rate_manager or session.payment_rate_manager


def get_version_from_tag(tag):
    match = re.match('v([\d.]+)', tag)
    if match:
        return match.group(1)
    else:
        raise Exception('Failed to parse version from tag {}'.format(tag))


# lbryum returns json loadeable object with amounts as decimal encoded string,
# convert them into floats for the daemon
# TODO: daemon should also use decimal encoded string
def format_json_out_amount_as_float(obj):
    if isinstance(obj, dict):
        for k, v in obj.iteritems():
            if k == 'amount' or k == 'effective_amount':
                obj[k] = float(obj[k])
            if isinstance(v, dict) or isinstance(v, list):
                obj[k] = format_json_out_amount_as_float(v)

    elif isinstance(obj, list):
        obj = [format_json_out_amount_as_float(o) for o in obj]
    return obj
