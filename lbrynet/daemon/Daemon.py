import binascii
import logging.handlers
import mimetypes
import os
import base58
import requests
import urllib
import json
import textwrap
import random
import signal

from twisted.web import server
from twisted.internet import defer, threads, error, reactor
from twisted.internet.task import LoopingCall
from twisted.python.failure import Failure

from lbryschema.claim import ClaimDict
from lbryschema.uri import parse_lbry_uri
from lbryschema.error import URIParseError
from lbryschema.validator import validate_claim_id
from lbryschema.base import base_decode

# TODO: importing this when internet is disabled raises a socket.gaierror
from lbrynet.core.system_info import get_lbrynet_version
from lbrynet import conf, analytics
from lbrynet.conf import LBRYCRD_WALLET, LBRYUM_WALLET, PTC_WALLET
from lbrynet.reflector import reupload
from lbrynet.reflector import ServerFactory as reflector_server_factory
from lbrynet.core.log_support import configure_loggly_handler
from lbrynet.lbry_file.client.EncryptedFileDownloader import EncryptedFileSaverFactory
from lbrynet.lbry_file.client.EncryptedFileDownloader import EncryptedFileOpenerFactory
from lbrynet.lbry_file.client.EncryptedFileOptions import add_lbry_file_to_sd_identifier
from lbrynet.lbry_file.EncryptedFileMetadataManager import DBEncryptedFileMetadataManager
from lbrynet.lbry_file.StreamDescriptor import EncryptedFileStreamType
from lbrynet.file_manager.EncryptedFileManager import EncryptedFileManager
from lbrynet.daemon.Downloader import GetStream
from lbrynet.daemon.Publisher import Publisher
from lbrynet.daemon.ExchangeRateManager import ExchangeRateManager
from lbrynet.daemon.auth.server import AuthJSONRPCServer
from lbrynet.core.PaymentRateManager import OnlyFreePaymentsManager
from lbrynet.core import utils, system_info
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier, download_sd_blob
from lbrynet.core.Session import Session
from lbrynet.core.Wallet import LBRYumWallet, SqliteStorage, ClaimOutpoint
from lbrynet.core.looping_call_manager import LoopingCallManager
from lbrynet.core.server.BlobRequestHandler import BlobRequestHandlerFactory
from lbrynet.core.server.ServerProtocol import ServerProtocolFactory
from lbrynet.core.Error import InsufficientFundsError, UnknownNameError, NoSuchSDHash
from lbrynet.core.Error import NoSuchStreamHash
from lbrynet.core.Error import NullFundsError, NegativeFundsError

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


class Checker(object):
    """The looping calls the daemon runs"""
    INTERNET_CONNECTION = 'internet_connection_checker'
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

    allowed_during_startup = [
        'daemon_stop', 'status', 'version',
    ]

    def __init__(self, analytics_manager):
        AuthJSONRPCServer.__init__(self, conf.settings['use_auth_http'])
        self.db_dir = conf.settings['data_dir']
        self.download_directory = conf.settings['download_directory']
        if conf.settings['BLOBFILES_DIR'] == "blobfiles":
            self.blobfile_dir = os.path.join(self.db_dir, "blobfiles")
        else:
            log.info("Using non-default blobfiles directory: %s", conf.settings['BLOBFILES_DIR'])
            self.blobfile_dir = conf.settings['BLOBFILES_DIR']
        self.data_rate = conf.settings['data_rate']
        self.max_key_fee = conf.settings['max_key_fee']
        self.disable_max_key_fee = conf.settings['disable_max_key_fee']
        self.download_timeout = conf.settings['download_timeout']
        self.run_reflector_server = conf.settings['run_reflector_server']
        self.wallet_type = conf.settings['wallet']
        self.delete_blobs_on_remove = conf.settings['delete_blobs_on_remove']
        self.peer_port = conf.settings['peer_port']
        self.reflector_port = conf.settings['reflector_port']
        self.dht_node_port = conf.settings['dht_node_port']
        self.use_upnp = conf.settings['use_upnp']

        self.startup_status = STARTUP_STAGES[0]
        self.connected_to_internet = True
        self.connection_status_code = None
        self.platform = None
        self.current_db_revision = 4
        self.db_revision_file = conf.settings.get_db_revision_filename()
        self.session = None
        self.uploaded_temp_files = []
        self._session_id = conf.settings.get_session_id()
        # TODO: this should probably be passed into the daemon, or
        # possibly have the entire log upload functionality taken out
        # of the daemon, but I don't want to deal with that now

        self.analytics_manager = analytics_manager
        self.lbryid = conf.settings.node_id

        self.wallet_user = None
        self.wallet_password = None
        self.query_handlers = {}
        self.waiting_on = {}
        self.streams = {}
        self.exchange_rate_manager = ExchangeRateManager()
        calls = {
            Checker.INTERNET_CONNECTION: LoopingCall(CheckInternetConnection(self)),
            Checker.CONNECTION_STATUS: LoopingCall(self._update_connection_status),
        }
        self.looping_call_manager = LoopingCallManager(calls)
        self.sd_identifier = StreamDescriptorIdentifier()
        self.stream_info_manager = None
        self.lbry_file_manager = None

    @defer.inlineCallbacks
    def setup(self):
        reactor.addSystemEventTrigger('before', 'shutdown', self._shutdown)

        configure_loggly_handler()

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
        self.looping_call_manager.start(Checker.CONNECTION_STATUS, 30)
        self.exchange_rate_manager.start()

        yield self._initial_setup()
        yield threads.deferToThread(self._setup_data_directory)
        yield self._check_db_migration()
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
                log.info("Daemon bound to port: %d", self.peer_port)
                self.lbry_server_port = reactor.listenTCP(self.peer_port, server_factory)
            except error.CannotListenError as e:
                import traceback
                log.error("Couldn't bind to port %d. Visit lbry.io/faq/how-to-change-port for"
                          " more details.", self.peer_port)
                log.error("%s", traceback.format_exc())
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
                log.info('Stop listening on port %s', old_port.port)
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
                self.analytics_manager
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

    @staticmethod
    def _already_shutting_down(sig_num, frame):
        log.info("Already shutting down")

    def _shutdown(self):
        # ignore INT/TERM signals once shutdown has started
        signal.signal(signal.SIGINT, self._already_shutting_down)
        signal.signal(signal.SIGTERM, self._already_shutting_down)

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
            'download_directory': str,
            'data_rate': float,
            'download_timeout': int,
            'peer_port': int,
            'max_key_fee': dict,
            'use_upnp': bool,
            'run_reflector_server': bool,
            'cache_time': int,
            'reflect_uploads': bool,
            'share_usage_data': bool,
            'disable_max_key_fee': bool,
            'peer_search_timeout': int,
            'sd_download_timeout': int,
        }

        for key, setting_type in setting_types.iteritems():
            if key in settings:
                if isinstance(settings[key], setting_type):
                    conf.settings.update({key: settings[key]},
                                         data_types=(conf.TYPE_RUNTIME, conf.TYPE_PERSISTED))
                elif setting_type is dict and isinstance(settings[key], (unicode, str)):
                    decoded = json.loads(str(settings[key]))
                    conf.settings.update({key: decoded},
                                         data_types=(conf.TYPE_RUNTIME, conf.TYPE_PERSISTED))
                else:
                    try:
                        converted = setting_type(settings[key])
                        conf.settings.update({key: converted},
                                             data_types=(conf.TYPE_RUNTIME, conf.TYPE_PERSISTED))
                    except Exception as err:
                        log.warning(err.message)
                        log.warning("error converting setting '%s' to type %s from type %s", key,
                                    setting_type, str(type(settings[key])))
        conf.settings.save_conf_file_settings()

        self.data_rate = conf.settings['data_rate']
        self.max_key_fee = conf.settings['max_key_fee']
        self.disable_max_key_fee = conf.settings['disable_max_key_fee']
        self.download_directory = conf.settings['download_directory']
        self.download_timeout = conf.settings['download_timeout']

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
        if not blob_hash:
            raise Exception("Nothing to download")

        rate_manager = rate_manager or self.session.payment_rate_manager
        timeout = timeout or 30
        return download_sd_blob(self.session, blob_hash, rate_manager, timeout)

    @defer.inlineCallbacks
    def _download_name(self, name, claim_dict, claim_id, timeout=None, file_name=None):
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
            self.analytics_manager.send_download_started(download_id, name, claim_dict)

            self.streams[claim_id] = GetStream(self.sd_identifier, self.session,
                                               self.exchange_rate_manager, self.max_key_fee,
                                               self.disable_max_key_fee,
                                               conf.settings['data_rate'], timeout,
                                               file_name)
            try:
                lbry_file, finished_deferred = yield self.streams[claim_id].start(claim_dict, name)
                finished_deferred.addCallback(
                    lambda _: self.analytics_manager.send_download_finished(download_id,
                                                                            name,
                                                                            claim_dict))
                result = yield self._get_lbry_file_dict(lbry_file, full_status=True)
                del self.streams[claim_id]
            except Exception as err:
                log.warning('Failed to get %s: %s', name, err)
                self.analytics_manager.send_download_errored(download_id, name, claim_dict)
                del self.streams[claim_id]
                result = {'error': err.message}
            defer.returnValue(result)

    @defer.inlineCallbacks
    def _publish_stream(self, name, bid, claim_dict, file_path=None, certificate_id=None,
                        claim_address=None, change_address=None):

        publisher = Publisher(self.session, self.lbry_file_manager, self.session.wallet,
                              certificate_id)
        parse_lbry_uri(name)
        if bid <= 0.0:
            raise Exception("Invalid bid")
        if not file_path:
            claim_out = yield publisher.publish_stream(name, bid, claim_dict, claim_address,
                                                       change_address)
        else:
            claim_out = yield publisher.create_and_publish_stream(name, bid, claim_dict, file_path,
                                                                  claim_address, change_address)
            if conf.settings['reflect_uploads']:
                d = reupload.reflect_stream(publisher.lbry_file)
                d.addCallbacks(lambda _: log.info("Reflected new publication to lbry://%s", name),
                               log.exception)
        self.analytics_manager.send_claim_action('publish')
        log.info("Success! Published to lbry://%s txid: %s nout: %d", name, claim_out['txid'],
                 claim_out['nout'])
        defer.returnValue(claim_out)

    def _get_long_count_timestamp(self):
        dt = utils.utcnow() - utils.datetime_obj(year=2012, month=12, day=21)
        return int(dt.total_seconds())

    @defer.inlineCallbacks
    def _resolve_name(self, name, force_refresh=False):
        """Resolves a name. Checks the cache first before going out to the blockchain.

        Args:
            name: the lbry://<name> to resolve
            force_refresh: if True, always go out to the blockchain to resolve.
        """

        parsed = parse_lbry_uri(name)
        resolution = yield self.session.wallet.resolve(parsed.name, check_cache=not force_refresh)
        if parsed.name in resolution:
            result = resolution[parsed.name]
            defer.returnValue(result)

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

        resolved = yield self.session.wallet.resolve(uri)

        if uri in resolved and 'claim' in resolved[uri]:
            claim = ClaimDict.load_dict(resolved[uri]['claim']['value'])
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
        fee_amount = 0.0 if not fee else self.exchange_rate_manager.convert_currency(fee.currency,
                                                                                     "LBC",
                                                                                     fee.amount)
        return data_cost + fee_amount

    @defer.inlineCallbacks
    def get_est_cost_from_uri(self, uri):
        """
        Resolve a name and return the estimated stream cost
        """

        resolved = yield self.session.wallet.resolve(uri)
        if resolved:
            claim_response = resolved[uri]
        else:
            claim_response = None

        result = None
        if claim_response and 'claim' in claim_response:
            if 'value' in claim_response['claim'] and claim_response['claim']['value'] is not None:
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

        claim = yield self.session.wallet.get_claim_by_claim_id(lbry_file.claim_id,
                                                                check_expire=False)

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
        if channel_name is not None:
            result['channel_name'] = channel_name
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
        log.debug("Collected %i lbry files", len(lbry_files))
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
    @AuthJSONRPCServer.flags(session_status="-s", dht_status="-d")
    def jsonrpc_status(self, session_status=False, dht_status=False):
        """
        Get daemon status

        Usage:
            status [-s] [-d]

        Options:
            -s  : include session status in results
            -d  : include dht network and peer status

        Returns:
            (dict) lbrynet-daemon status
            {
                'lbry_id': lbry peer id, base58
                'installation_id': installation id, base58
                'is_running': bool
                'is_first_run': bool
                'startup_status': {
                    'code': status code
                    'message': status message
                },
                'connection_status': {
                    'code': connection status code
                    'message': connection status message
                },
                'blockchain_status': {
                    'blocks': local blockchain height,
                    'blocks_behind': remote_height - local_height,
                    'best_blockhash': block hash of most recent block,
                },

                If given the session status option:
                    'session_status': {
                        'managed_blobs': count of blobs in the blob manager,
                        'managed_streams': count of streams in the file manager
                    }

                If given the dht status option:
                    'dht_status': {
                        'kbps_received': current kbps receiving,
                        'kbps_sent': current kdps being sent,
                        'total_bytes_sent': total bytes sent
                        'total_bytes_received': total bytes received
                        'queries_received': number of queries received per second
                        'queries_sent': number of queries sent per second
                        'recent_contacts': count of recently contacted peers
                        'unique_contacts': count of unique peers
                    }
            }
        """

        # on startup, the wallet or network won't be available but we still need this call to work
        has_wallet = self.session and self.session.wallet and self.session.wallet.network
        local_height = self.session.wallet.network.get_local_height() if has_wallet else 0
        remote_height = self.session.wallet.network.get_server_height() if has_wallet else 0
        best_hash = (yield self.session.wallet.get_best_blockhash()) if has_wallet else None

        response = {
            'lbry_id': base58.b58encode(self.lbryid),
            'installation_id': conf.settings.installation_id,
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
        if dht_status:
            response['dht_status'] = self.session.dht_node.get_bandwidth_stats()
        defer.returnValue(response)

    def jsonrpc_version(self):
        """
        Get lbry version information

        Usage:
            version

        Returns:
            (dict) Dictionary of lbry version information
            {
                'build': (str) build type (e.g. "dev", "rc", "release"),
                'ip': (str) remote ip, if available,
                'lbrynet_version': (str) lbrynet_version,
                'lbryum_version': (str) lbryum_version,
                'lbryschema_version': (str) lbryschema_version,
                'os_release': (str) os release string
                'os_system': (str) os name
                'platform': (str) platform string
                'processor': (str) processor type,
                'python_version': (str) python version,
            }
        """

        platform_info = self._get_platform()
        log.info("Get version info: " + json.dumps(platform_info))
        return self._render_response(platform_info)

    def jsonrpc_report_bug(self, message=None):
        """
        Report a bug to slack

        Usage:
            report_bug (<message> | --message=<message>)

        Returns:
            (bool) true if successful
        """

        platform_name = self._get_platform()['platform']
        report_bug_to_slack(
            message,
            conf.settings.installation_id,
            platform_name,
            get_lbrynet_version()
        )
        return self._render_response(True)

    def jsonrpc_settings_get(self):
        """
        Get daemon settings

        Usage:
            settings_get

        Returns:
            (dict) Dictionary of daemon settings
            See ADJUSTABLE_SETTINGS in lbrynet/conf.py for full list of settings
        """
        return self._render_response(conf.settings.get_adjustable_settings_dict())

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_settings_set(self, **kwargs):
        """
        Set daemon settings

        Usage:
            settings_set [<download_directory> | --download_directory=<download_directory>]
                         [<data_rate> | --data_rate=<data_rate>]
                         [<download_timeout> | --download_timeout=<download_timeout>]
                         [<peer_port> | --peer_port=<peer_port>]
                         [<max_key_fee> | --max_key_fee=<max_key_fee>]
                         [<disable_max_key_fee> | --disable_max_key_fee=<disable_max_key_fee>]
                         [<use_upnp> | --use_upnp=<use_upnp>]
                         [<run_reflector_server> | --run_reflector_server=<run_reflector_server>]
                         [<cache_time> | --cache_time=<cache_time>]
                         [<reflect_uploads> | --reflect_uploads=<reflect_uploads>]
                         [<share_usage_data> | --share_usage_data=<share_usage_data>]
                         [<peer_search_timeout> | --peer_search_timeout=<peer_search_timeout>]
                         [<sd_download_timeout> | --sd_download_timeout=<sd_download_timeout>]

        Options:
            <download_directory>, --download_directory=<download_directory>  : (str)
            <data_rate>, --data_rate=<data_rate>                             : (float), 0.0001
            <download_timeout>, --download_timeout=<download_timeout>        : (int), 180
            <peer_port>, --peer_port=<peer_port>                             : (int), 3333
            <max_key_fee>, --max_key_fee=<max_key_fee>   : (dict) maximum key fee for downloads,
                                                            in the format: {
                                                                "currency": <currency_symbol>,
                                                                "amount": <amount>
                                                            }. In the CLI, it must be an escaped
                                                            JSON string
                                                            Supported currency symbols:
                                                                LBC
                                                                BTC
                                                                USD
            <disable_max_key_fee>, --disable_max_key_fee=<disable_max_key_fee> : (bool), False
            <use_upnp>, --use_upnp=<use_upnp>            : (bool), True
            <run_reflector_server>, --run_reflector_server=<run_reflector_server>  : (bool), False
            <cache_time>, --cache_time=<cache_time>  : (int), 150
            <reflect_uploads>, --reflect_uploads=<reflect_uploads>  : (bool), True
            <share_usage_data>, --share_usage_data=<share_usage_data>  : (bool), True
            <peer_search_timeout>, --peer_search_timeout=<peer_search_timeout>  : (int), 3
            <sd_download_timeout>, --sd_download_timeout=<sd_download_timeout>  : (int), 3

        Returns:
            (dict) Updated dictionary of daemon settings
        """

        yield self._update_settings(kwargs)
        defer.returnValue(conf.settings.get_adjustable_settings_dict())

    def jsonrpc_help(self, command=None):
        """
        Return a useful message for an API command

        Usage:
            help [<command> | --command=<command>]

        Options:
            <command>, --command=<command>  : command to retrieve documentation for
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

        Usage:
            commands

        Returns:
            (list) list of available commands
        """
        return self._render_response(sorted([command for command in self.callable_methods.keys()]))

    @AuthJSONRPCServer.flags(include_unconfirmed='-u')
    def jsonrpc_wallet_balance(self, address=None, include_unconfirmed=False):
        """
        Return the balance of the wallet

        Usage:
            wallet_balance [<address> | --address=<address>] [-u]

        Options:
            <address>  :  If provided only the balance for this address will be given
            -u         :  Include unconfirmed

        Returns:
            (float) amount of lbry credits in wallet
        """
        if address is None:
            return self._render_response(float(self.session.wallet.get_balance()))
        else:
            return self._render_response(float(
                self.session.wallet.get_address_balance(address, include_unconfirmed)))

    @defer.inlineCallbacks
    def jsonrpc_daemon_stop(self):
        """
        Stop lbrynet-daemon

        Usage:
            daemon_stop

        Returns:
            (string) Shutdown message
        """

        log.info("Shutting down lbrynet daemon")
        response = yield self._render_response("Shutting down")
        reactor.callLater(0.1, reactor.fireSystemEvent, "shutdown")
        defer.returnValue(response)

    @defer.inlineCallbacks
    @AuthJSONRPCServer.flags(full_status='-f')
    def jsonrpc_file_list(self, **kwargs):
        """
        List files limited by optional filters

        Usage:
            file_list [--sd_hash=<sd_hash>] [--file_name=<file_name>] [--stream_hash=<stream_hash>]
                      [--claim_id=<claim_id>] [--outpoint=<outpoint>] [--rowid=<rowid>]
                      [--name=<name>]
                      [-f]

        Options:
            --sd_hash=<sd_hash>          : get file with matching sd hash
            --file_name=<file_name>      : get file with matching file name in the
                                           downloads folder
            --stream_hash=<stream_hash>  : get file with matching stream hash
            --claim_id=<claim_id>        : get file with matching claim id
            --outpoint=<outpoint>        : get file with matching claim outpoint
            --rowid=<rowid>              : get file with matching row id
            --name=<name>                : get file with matching associated name claim
            -f                           : full status, populate the 'message' and 'size' fields

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
    @AuthJSONRPCServer.flags(force='-f')
    def jsonrpc_resolve_name(self, name, force=False):
        """
        Resolve stream info from a LBRY name

        Usage:
            resolve_name <name> [-f]

        Options:
            -f  : force refresh and do not check cache

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

    @defer.inlineCallbacks
    def jsonrpc_claim_show(self, txid=None, nout=None, claim_id=None):
        """
        Resolve claim info from txid/nout or with claim ID

        Usage:
            claim_show [<txid> | --txid=<txid>] [<nout> | --nout=<nout>]
                       [<claim_id> | --claim_id=<claim_id>]

        Options:
            <txid>, --txid=<txid>              : look for claim with this txid, nout must
                                                    also be specified
            <nout>, --nout=<nout>              : look for claim with this nout, txid must
                                                    also be specified
            <claim_id>, --claim_id=<claim_id>  : look for claim with this claim id

        Returns:
            (dict) Dictionary containing claim info as below,

            {
                'txid': (str) txid of claim
                'nout': (int) nout of claim
                'amount': (float) amount of claim
                'value': (str) value of claim
                'height' : (int) height of claim takeover
                'claim_id': (str) claim ID of claim
                'supports': (list) list of supports associated with claim
            }

            if claim cannot be resolved, dictionary as below will be returned

            {
                'error': (str) reason for error
            }

        """
        if claim_id is not None and txid is None and nout is None:
            claim_results = yield self.session.wallet.get_claim_by_claim_id(claim_id)
        elif txid is not None and nout is not None and claim_id is None:
            outpoint = ClaimOutpoint(txid, nout)
            claim_results = yield self.session.wallet.get_claim_by_outpoint(outpoint)
        else:
            raise Exception("Must specify either txid/nout, or claim_id")
        response = yield self._render_response(claim_results)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    @AuthJSONRPCServer.flags(force='-f')
    def jsonrpc_resolve(self, force=False, uri=None, uris=[]):
        """
        Resolve given LBRY URIs

        Usage:
            resolve [-f] (<uri> | --uri=<uri>) [<uris>...]

        Options:
            -f  : force refresh and ignore cache

        Returns:
            Dictionary of results, keyed by uri
            '<uri>': {
                    If a resolution error occurs:
                    'error': Error message

                    If the uri resolves to a channel or a claim in a channel:
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

                    If the uri resolves to a channel:
                    'claims_in_channel': (int) number of claims in the channel,

                    If the uri resolves to a claim:
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

        uris = tuple(uris)
        if uri is not None:
            uris += (uri,)

        results = {}

        valid_uris = tuple()
        for u in uris:
            try:
                parse_lbry_uri(u)
                valid_uris += (u, )
            except URIParseError:
                results[u] = {"error": "%s is not a valid uri" % u}

        resolved = yield self.session.wallet.resolve(*valid_uris, check_cache=not force)

        for resolved_uri in resolved:
            results[resolved_uri] = resolved[resolved_uri]
        response = yield self._render_response(results)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_get(self, uri, file_name=None, timeout=None):
        """
        Download stream from a LBRY name.

        Usage:
            get <uri> [<file_name> | --file_name=<file_name>] [<timeout> | --timeout=<timeout>]


        Options:
            <file_name>           : specified name for the downloaded file
            <timeout>             : download timeout in number of seconds
            <download_directory>  : path to directory where file will be saved

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

        resolved_result = yield self.session.wallet.resolve(uri)
        if resolved_result and uri in resolved_result:
            resolved = resolved_result[uri]
        else:
            resolved = None

        if not resolved or 'value' not in resolved:
            if 'claim' not in resolved:
                raise Exception(
                    "Failed to resolve stream at lbry://{}".format(uri.replace("lbry://", "")))
            else:
                resolved = resolved['claim']

        name = resolved['name']
        claim_id = resolved['claim_id']
        claim_dict = ClaimDict.load_dict(resolved['value'])

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
            result = yield self._download_name(name, claim_dict, claim_id, timeout=timeout,
                                               file_name=file_name)
        response = yield self._render_response(result)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_file_set_status(self, status, **kwargs):
        """
        Start or stop downloading a file

        Usage:
            file_set_status <status> [--sd_hash=<sd_hash>] [--file_name=<file_name>]
                      [--stream_hash=<stream_hash>] [--claim_id=<claim_id>]
                      [--outpoint=<outpoint>] [--rowid=<rowid>]
                      [--name=<name>]

        Options:
            --sd_hash=<sd_hash>          : set status of file with matching sd hash
            --file_name=<file_name>      : set status of file with matching file name in the
                                           downloads folder
            --stream_hash=<stream_hash>  : set status of file with matching stream hash
            --claim_id=<claim_id>        : set status of file with matching claim id
            --outpoint=<outpoint>        : set status of file with matching claim outpoint
            --rowid=<rowid>              : set status of file with matching row id
            --name=<name>                : set status of file with matching associated name claim

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
    @AuthJSONRPCServer.flags(delete_from_download_dir='-f', delete_all='--delete_all')
    def jsonrpc_file_delete(self, delete_from_download_dir=False, delete_all=False, **kwargs):
        """
        Delete a LBRY file

        Usage:
            file_delete [-f] [--delete_all] [--sd_hash=<sd_hash>] [--file_name=<file_name>]
                        [--stream_hash=<stream_hash>] [--claim_id=<claim_id>]
                        [--outpoint=<outpoint>] [--rowid=<rowid>]
                        [--name=<name>]

        Options:
            -f, --delete_from_download_dir  : delete file from download directory,
                                                instead of just deleting blobs
            --delete_all                    : if there are multiple matching files,
                                                allow the deletion of multiple files.
                                                Otherwise do not delete anything.
            --sd_hash=<sd_hash>             : delete by file sd hash
            --file_name<file_name>          : delete by file name in downloads folder
            --stream_hash=<stream_hash>     : delete by file stream hash
            --claim_id=<claim_id>           : delete by file claim id
            --outpoint=<outpoint>           : delete by file claim outpoint
            --rowid=<rowid>                 : delete by file row id
            --name=<name>                   : delete by associated name claim of file

        Returns:
            (bool) true if deletion was successful
        """

        lbry_files = yield self._get_lbry_files(return_json=False, **kwargs)

        if len(lbry_files) > 1:
            if not delete_all:
                log.warning("There are %i files to delete, use narrower filters to select one",
                            len(lbry_files))
                response = yield self._render_response(False)
                defer.returnValue(response)
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
                                                              delete_file=delete_from_download_dir)
                log.info("Deleted file: %s", file_name)
            result = True

        response = yield self._render_response(result)
        defer.returnValue(response)

    @defer.inlineCallbacks
    def jsonrpc_stream_cost_estimate(self, uri, size=None):
        """
        Get estimated cost for a lbry stream

        Usage:
            stream_cost_estimate <uri> [<size> | --size=<size>]

        Options:
            <size>, --size=<size>  : stream size in bytes. if provided an sd blob won't be
                                     downloaded.

        Returns:
            (float) Estimated cost in lbry credits, returns None if uri is not
                resolveable
        """
        cost = yield self.get_est_cost(uri, size)
        defer.returnValue(cost)

    @AuthJSONRPCServer.auth_required
    @AuthJSONRPCServer.queued
    @defer.inlineCallbacks
    def jsonrpc_channel_new(self, channel_name, amount):
        """
        Generate a publisher key and create a new '@' prefixed certificate claim

        Usage:
            channel_new (<channel_name> | --channel_name=<channel_name>)
                        (<amount> | --amount=<amount>)

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
        self.analytics_manager.send_new_channel()
        log.info("Claimed a new channel! Result: %s", result)
        response = yield self._render_response(result)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_channel_list_mine(self):
        """
        Get my channels

        Usage:
            channel_list_mine

        Returns:
            (list) ClaimDict
        """

        result = yield self.session.wallet.channel_list()
        response = yield self._render_response(result)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    @AuthJSONRPCServer.queued
    @defer.inlineCallbacks
    def jsonrpc_publish(self, name, bid, metadata=None, file_path=None, fee=None, title=None,
                        description=None, author=None, language=None, license=None,
                        license_url=None, thumbnail=None, preview=None, nsfw=None, sources=None,
                        channel_name=None, channel_id=None,
                        claim_address=None, change_address=None):
        """
        Make a new name claim and publish associated data to lbrynet,
        update over existing claim if user already has a claim for name.

        Fields required in the final Metadata are:
            'title'
            'description'
            'author'
            'language'
            'license'
            'nsfw'

        Metadata can be set by either using the metadata argument or by setting individual arguments
        fee, title, description, author, language, license, license_url, thumbnail, preview, nsfw,
        or sources. Individual arguments will overwrite the fields specified in metadata argument.

        Usage:
            publish (<name> | --name=<name>) (<bid> | --bid=<bid>) [--metadata=<metadata>]
                    [--file_path=<file_path>] [--fee=<fee>] [--title=<title>]
                    [--description=<description>] [--author=<author>] [--language=<language>]
                    [--license=<license>] [--license_url=<license_url>] [--thumbnail=<thumbnail>]
                    [--preview=<preview>] [--nsfw=<nsfw>] [--sources=<sources>]
                    [--channel_name=<channel_name>] [--channel_id=<channel_id>]
                    [--claim_address=<claim_address>] [--change_address=<change_address>]

        Options:
            --metadata=<metadata>          : ClaimDict to associate with the claim.
            --file_path=<file_path>        : path to file to be associated with name. If provided,
                                             a lbry stream of this file will be used in 'sources'.
                                             If no path is given but a metadata dict is provided,
                                             the source from the given metadata will be used.
            --fee=<fee>                    : Dictionary representing key fee to download content:
                                              {
                                                'currency': currency_symbol,
                                                'amount': float,
                                                'address': str, optional
                                              }
                                              supported currencies: LBC, USD, BTC
                                              If an address is not provided a new one will be
                                              automatically generated. Default fee is zero.
            --title=<title>                : title of the publication
            --description=<description>    : description of the publication
            --author=<author>              : author of the publication
            --language=<language>          : language of the publication
            --license=<license>            : publication license
            --license_url=<license_url>    : publication license url
            --thumbnail=<thumbnail>        : thumbnail url
            --preview=<preview>            : preview url
            --nsfw=<nsfw>                  : title of the publication
            --sources=<sources>            : {'lbry_sd_hash':sd_hash} specifies sd hash of file
            --channel_name=<channel_name>  : name of the publisher channel name in the wallet
            --channel_id=<channel_id>      : claim id of the publisher channel, does not check
                                             for channel claim being in the wallet. This allows
                                             publishing to a channel where only the certificate
                                             private key is in the wallet.
           --claim_address=<claim_address> : address where the claim is sent to, if not specified
                                             new address wil automatically be created

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

        if bid >= self.session.wallet.get_balance():
            raise InsufficientFundsError('Insufficient funds. ' \
                                         'Make sure you have enough LBC to deposit')

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
            metadata['licenseUrl'] = license_url
        if thumbnail is not None:
            metadata['thumbnail'] = thumbnail
        if preview is not None:
            metadata['preview'] = preview
        if nsfw is not None:
            metadata['nsfw'] = bool(nsfw)

        metadata['version'] = '_0_1_0'

        # check for original deprecated format {'currency':{'address','amount'}}
        # add address, version to fee if unspecified
        if 'fee' in metadata:
            if len(metadata['fee'].keys()) == 1 and isinstance(metadata['fee'].values()[0], dict):
                raise Exception('Old format for fee no longer supported. ' \
                                'Fee must be specified as {"currency":,"address":,"amount":}')

            if 'amount' in metadata['fee'] and 'currency' in metadata['fee']:
                if not metadata['fee']['amount']:
                    log.warning("Stripping empty fee from published metadata")
                    del metadata['fee']
                elif 'address' not in metadata['fee']:
                    address = yield self.session.wallet.get_unused_address()
                    metadata['fee']['address'] = address
            if 'fee' in metadata and 'version' not in metadata['fee']:
                metadata['fee']['version'] = '_0_0_1'

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

        log.info("Publish: %s", {
            'name': name,
            'file_path': file_path,
            'bid': bid,
            'claim_address': claim_address,
            'change_address': change_address,
            'claim_dict': claim_dict,
        })

        if channel_id:
            certificate_id = channel_id
        elif channel_name:
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

        result = yield self._publish_stream(name, bid, claim_dict, file_path, certificate_id,
                                            claim_address, change_address)
        response = yield self._render_response(result)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_claim_abandon(self, claim_id=None, txid=None, nout=None):
        """
        Abandon a name and reclaim credits from the claim

        Usage:
            claim_abandon [<claim_id> | --claim_id=<claim_id>]
                          [<txid> | --txid=<txid>] [<nout> | --nout=<nout>]

        Return:
            (dict) Dictionary containing result of the claim
            {
                txid : (str) txid of resulting transaction
                fee : (float) fee paid for the transaction
            }
        """
        if claim_id is None and txid is None and nout is None:
            raise Exception('Must specify claim_id, or txid and nout')
        if txid is None and nout is not None:
            raise Exception('Must specify txid')
        if nout is None and txid is not None:
            raise Exception('Must specify nout')

        result = yield self.session.wallet.abandon_claim(claim_id, txid, nout)
        self.analytics_manager.send_claim_action('abandon')
        defer.returnValue(result)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_claim_new_support(self, name, claim_id, amount):
        """
        Support a name claim

        Usage:
            claim_new_support (<name> | --name=<name>) (<claim_id> | --claim_id=<claim_id>)
                              (<amount> | --amount=<amount>)

        Return:
            (dict) Dictionary containing result of the claim
            {
                txid : (str) txid of resulting support claim
                nout : (int) nout of the resulting support claim
                fee : (float) fee paid for the transaction
            }
        """

        result = yield self.session.wallet.support_claim(name, claim_id, amount)
        self.analytics_manager.send_claim_action('new_support')
        defer.returnValue(result)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_claim_send_to_address(self, claim_id, address, amount=None):
        """
        Send a name claim to an address

        Usage:
            claim_send_to_address (<claim_id> | --claim_id=<claim_id>)
                                  (<address> | --address=<address>)
                                  [<amount> | --amount=<amount>]

        Options:
            <amount>  : Amount of credits to claim name for, defaults to the current amount
                        on the claim
        """
        result = yield self.session.wallet.send_claim_to_address(claim_id, address, amount)
        response = yield self._render_response(result)
        defer.returnValue(response)

    # TODO: claim_list_mine should be merged into claim_list, but idk how to authenticate it -Grin
    @AuthJSONRPCServer.auth_required
    def jsonrpc_claim_list_mine(self):
        """
        List my name claims

        Usage:
            claim_list_mine

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
        d.addCallback(lambda claims: self._render_response(claims))
        return d

    @defer.inlineCallbacks
    def jsonrpc_claim_list(self, name):
        """
        List current claims and information about them for a given name

        Usage:
            claim_list (<name> | --name=<name>)

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
    @defer.inlineCallbacks
    def jsonrpc_claim_list_by_channel(self, page=0, page_size=10, uri=None, uris=[]):
        """
        Get paginated claims in a channel specified by a channel uri

        Usage:
            claim_list_by_channel (<uri> | --uri=<uri>) [<uris>...] [--page=<page>]
                                   [--page_size=<page_size>]

        Options:
            --page=<page>            : which page of results to return where page 1 is the first
                                       page, defaults to no pages
            --page_size=<page_size>  : number of results in a page, default of 10

        Returns:
            {
                 resolved channel uri: {
                    If there was an error:
                    'error': (str) error message

                    'claims_in_channel': the total number of results for the channel,

                    If a page of results was requested:
                    'returned_page': page number returned,
                    'claims_in_channel': [
                        {
                            'absolute_channel_position': (int) claim index number in sorted list of
                                                         claims which assert to be part of the
                                                         channel
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
                    ],
                }
            }
        """

        uris = tuple(uris)
        if uri is not None:
            uris += (uri, )

        results = {}

        valid_uris = tuple()
        for chan_uri in uris:
            try:
                parsed = parse_lbry_uri(chan_uri)
                if not parsed.is_channel:
                    results[chan_uri] = {"error": "%s is not a channel uri" % parsed.name}
                elif parsed.path:
                    results[chan_uri] = {"error": "%s is a claim in a channel" % parsed.path}
                else:
                    valid_uris += (chan_uri, )
            except URIParseError:
                results[chan_uri] = {"error": "%s is not a valid uri" % chan_uri}

        resolved = yield self.session.wallet.resolve(*valid_uris, check_cache=False, page=page,
                                                     page_size=page_size)
        for u in resolved:
            if 'error' in resolved[u]:
                results[u] = resolved[u]
            else:
                results[u] = {
                        'claims_in_channel': resolved[u]['claims_in_channel']
                    }
                if page:
                    results[u]['returned_page'] = page
                    results[u]['claims_in_channel'] = resolved[u].get('claims_in_channel', [])

        response = yield self._render_response(results)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_transaction_list(self):
        """
        List transactions belonging to wallet

        Usage:
            transaction_list

        Returns:
            (list) List of transactions
        """

        d = self.session.wallet.get_history()
        d.addCallback(lambda r: self._render_response(r))
        return d

    def jsonrpc_transaction_show(self, txid):
        """
        Get a decoded transaction from a txid

        Usage:
            transaction_show (<txid> | --txid=<txid>)

        Returns:
            (dict) JSON formatted transaction
        """

        d = self.session.wallet.get_transaction(txid)
        d.addCallback(lambda r: self._render_response(r))
        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_wallet_is_address_mine(self, address):
        """
        Checks if an address is associated with the current wallet.

        Usage:
            wallet_is_address_mine (<address> | --address=<address>)

        Returns:
            (bool) true, if address is associated with current wallet
        """

        d = self.session.wallet.address_is_mine(address)
        d.addCallback(lambda is_mine: self._render_response(is_mine))
        return d

    @AuthJSONRPCServer.auth_required
    def jsonrpc_wallet_public_key(self, address):
        """
        Get public key from wallet address

        Usage:
            wallet_public_key (<address> | --address=<address>)

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

        Usage:
            wallet_list

        Returns:
            List of wallet addresses
        """

        addresses = yield self.session.wallet.list_addresses()
        response = yield self._render_response(addresses)
        defer.returnValue(response)

    @AuthJSONRPCServer.auth_required
    def jsonrpc_wallet_new_address(self):
        """
        Generate a new wallet address

        Usage:
            wallet_new_address

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

        Usage:
            wallet_unused_address

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

    @AuthJSONRPCServer.deprecated("wallet_send")
    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_send_amount_to_address(self, amount, address):
        """
        Queue a payment of credits to an address

        Usage:
            send_amount_to_address (<amount> | --amount=<amount>) (<address> | --address=<address>)

        Returns:
            (bool) true if payment successfully scheduled
        """

        if amount < 0:
            raise NegativeFundsError()
        elif not amount:
            raise NullFundsError()

        reserved_points = self.session.wallet.reserve_points(address, amount)
        if reserved_points is None:
            raise InsufficientFundsError()
        yield self.session.wallet.send_points_to_address(reserved_points, amount)
        self.analytics_manager.send_credits_sent()
        defer.returnValue(True)

    @AuthJSONRPCServer.auth_required
    @defer.inlineCallbacks
    def jsonrpc_wallet_send(self, amount, address=None, claim_id=None):
        """
        Send credits. If given an address, send credits to it. If given a claim id, send a tip
        to the owner of a claim specified by uri. A tip is a claim support where the recipient
        of the support is the claim address for the claim being supported.

        Usage:
            wallet_send (<amount> | --amount=<amount>)
                        ((<address> | --address=<address>) | (<claim_id> | --claim_id=<claim_id>))

        Return:
            If sending to an address:
            (bool) true if payment successfully scheduled

            If sending a claim tip:
            (dict) Dictionary containing the result of the support
            {
                txid : (str) txid of resulting support claim
                nout : (int) nout of the resulting support claim
                fee : (float) fee paid for the transaction
            }
        """

        if address and claim_id:
            raise Exception("Given both an address and a claim id")
        elif not address and not claim_id:
            raise Exception("Not given an address or a claim id")
        if amount < 0:
            raise NegativeFundsError()
        elif not amount:
            raise NullFundsError()

        if address:
            if not base_decode(address, 58):
                raise Exception("Given an invalid address to send to")
            result = yield self.jsonrpc_send_amount_to_address(amount, address)
        else:
            validate_claim_id(claim_id)
            result = yield self.session.wallet.tip_claim(claim_id, amount)
            self.analytics_manager.send_claim_action('new_support')
        defer.returnValue(result)

    def jsonrpc_block_show(self, blockhash=None, height=None):
        """
        Get contents of a block

        Usage:
            block_show (<blockhash> | --blockhash=<blockhash>) | (<height> | --height=<height>)

        Options:
            <blockhash>, --blockhash=<blockhash>  : hash of the block to look up
            <height>, --height=<height>           : height of the block to look up

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
    @defer.inlineCallbacks
    def jsonrpc_blob_get(self, blob_hash, timeout=None, encoding=None, payment_rate_manager=None):
        """
        Download and return a blob

        Usage:
            blob_get (<blob_hash> | --blob_hash=<blob_hash>) [--timeout=<timeout>]
                     [--encoding=<encoding>] [--payment_rate_manager=<payment_rate_manager>]

        Options:
        --timeout=<timeout>                            : timeout in number of seconds
        --encoding=<encoding>                          : by default no attempt at decoding is made,
                                                         can be set to one of the
                                                         following decoders:
                                                            'json'
        --payment_rate_manager=<payment_rate_manager>  : if not given the default payment rate
                                                         manager will be used.
                                                         supported alternative rate managers:
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

        Usage:
            blob_delete (<blob_hash> | --blob_hash=<blob_hash)

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

    def jsonrpc_peer_list(self, blob_hash, timeout=None):
        """
        Get peers for blob hash

        Usage:
            peer_list (<blob_hash> | --blob_hash=<blob_hash>) [<timeout> | --timeout=<timeout>]

        Options:
            <timeout>, --timeout=<timeout>  : peer search timeout in seconds

        Returns:
            (list) List of contacts
        """

        timeout = timeout or conf.settings['peer_search_timeout']

        d = self.session.peer_finder.find_peers_for_blob(blob_hash, timeout=timeout)
        d.addCallback(lambda r: [[c.host, c.port, c.is_available()] for c in r])
        d.addCallback(lambda r: self._render_response(r))
        return d

    @defer.inlineCallbacks
    @AuthJSONRPCServer.flags(announce_all="-a")
    def jsonrpc_blob_announce(self, announce_all=None, blob_hash=None,
                              stream_hash=None, sd_hash=None):
        """
        Announce blobs to the DHT

        Usage:
            blob_announce [-a] [<blob_hash> | --blob_hash=<blob_hash>]
                          [<stream_hash> | --stream_hash=<stream_hash>]
                          [<sd_hash> | --sd_hash=<sd_hash>]

        Options:
            -a                                          : announce all the blobs possessed by user
            <blob_hash>, --blob_hash=<blob_hash>        : announce a blob, specified by blob_hash
            <stream_hash>, --stream_hash=<stream_hash>  : announce all blobs associated with
                                                            stream_hash
            <sd_hash>, --sd_hash=<sd_hash>              : announce all blobs associated with
                                                            sd_hash and the sd_hash itself

        Returns:
            (bool) true if successful
        """
        if announce_all:
            yield self.session.blob_manager.immediate_announce_all_blobs()
        elif blob_hash:
            blob_hashes = [blob_hash]
            yield self.session.blob_manager._immediate_announce(blob_hashes)
        elif stream_hash:
            blobs = yield self.get_blobs_for_stream_hash(stream_hash)
            blobs = [blob for blob in blobs if blob.is_validated()]
            blob_hashes = [blob.blob_hash for blob in blobs]
            yield self.session.blob_manager._immediate_announce(blob_hashes)
        elif sd_hash:
            blobs = yield self.get_blobs_for_sd_hash(sd_hash)
            blobs = [blob for blob in blobs if blob.is_validated()]
            blob_hashes = [blob.blob_hash for blob in blobs]
            blob_hashes.append(sd_hash)
            yield self.session.blob_manager._immediate_announce(blob_hashes)
        else:
            raise Exception('single argument must be specified')

        response = yield self._render_response(True)
        defer.returnValue(response)

    # TODO: This command should be deprecated in favor of blob_announce
    def jsonrpc_blob_announce_all(self):
        """
        Announce all blobs to the DHT

        Usage:
            blob_announce_all

        Returns:
            (str) Success/fail message
        """

        d = self.session.blob_manager.immediate_announce_all_blobs()
        d.addCallback(lambda _: self._render_response("Announced"))
        return d

    @defer.inlineCallbacks
    def jsonrpc_file_reflect(self, **kwargs):
        """
        Reflect all the blobs in a file matching the filter criteria

        Usage:
            file_reflect [--sd_hash=<sd_hash>] [--file_name=<file_name>]
                         [--stream_hash=<stream_hash>] [--claim_id=<claim_id>]
                         [--outpoint=<outpoint>] [--rowid=<rowid>] [--name=<name>]
                         [--reflector=<reflector>]

        Options:
            --sd_hash=<sd_hash>          : get file with matching sd hash
            --file_name=<file_name>      : get file with matching file name in the
                                           downloads folder
            --stream_hash=<stream_hash>  : get file with matching stream hash
            --claim_id=<claim_id>        : get file with matching claim id
            --outpoint=<outpoint>        : get file with matching claim outpoint
            --rowid=<rowid>              : get file with matching row id
            --name=<name>                : get file with matching associated name claim
            --reflector=<reflector>      : reflector server, ip address or url
                                           by default choose a server from the config

        Returns:
            (list) list of blobs reflected
        """

        reflector_server = kwargs.get('reflector', None)
        lbry_files = yield self._get_lbry_files(**kwargs)

        if len(lbry_files) > 1:
            raise Exception('Too many (%i) files found, need one' % len(lbry_files))
        elif not lbry_files:
            raise Exception('No file found')
        lbry_file = lbry_files[0]

        results = yield reupload.reflect_stream(lbry_file, reflector_server=reflector_server)
        defer.returnValue(results)

    @defer.inlineCallbacks
    @AuthJSONRPCServer.flags(needed="-n", finished="-f")
    def jsonrpc_blob_list(self, uri=None, stream_hash=None, sd_hash=None, needed=None,
                          finished=None, page_size=None, page=None):
        """
        Returns blob hashes. If not given filters, returns all blobs known by the blob manager

        Usage:
            blob_list [-n] [-f] [<uri> | --uri=<uri>] [<stream_hash> | --stream_hash=<stream_hash>]
                      [<sd_hash> | --sd_hash=<sd_hash>] [<page_size> | --page_size=<page_size>]
                      [<page> | --page=<page>]

        Options:
            -n                                          : only return needed blobs
            -f                                          : only return finished blobs
            <uri>, --uri=<uri>                          : filter blobs by stream in a uri
            <stream_hash>, --stream_hash=<stream_hash>  : filter blobs by stream hash
            <sd_hash>, --sd_hash=<sd_hash>              : filter blobs by sd hash
            <page_size>, --page_size=<page_size>        : results page size
            <page>, --page=<page>                       : page of results to return

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

    def jsonrpc_blob_reflect_all(self):
        """
        Reflects all saved blobs

        Usage:
            blob_reflect_all

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

        Usage:
            get_availability (<uri> | --uri=<uri>) [<sd_timeout> | --sd_timeout=<sd_timeout>]
                             [<peer_timeout> | --peer_timeout=<peer_timeout>]

        Options:
            <sd_timeout>, --sd_timeout=<sd_timeout>        : sd blob download timeout
            <peer_timeout>, --peer_timeout=<peer_timeout>  : how long to look for peers

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

        resolved_result = yield self.session.wallet.resolve(uri)
        if resolved_result and uri in resolved_result:
            resolved = resolved_result[uri]
        else:
            defer.returnValue(None)

        if 'claim' in resolved:
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

    @defer.inlineCallbacks
    @AuthJSONRPCServer.flags(a_arg='-a', b_arg='-b')
    def jsonrpc_cli_test_command(self, pos_arg, pos_args=[], pos_arg2=None, pos_arg3=None,
                                 a_arg=False, b_arg=False):
        """
        This command is only for testing the CLI argument parsing
        Usage:
            cli_test_command [-a] [-b] (<pos_arg> | --pos_arg=<pos_arg>)
                             [<pos_args>...] [--pos_arg2=<pos_arg2>]
                             [--pos_arg3=<pos_arg3>]

        Options:
            -a, --a_arg                        : a arg
            -b, --b_arg                        : b arg
            <pos_arg2>, --pos_arg2=<pos_arg2>  : pos arg 2
            <pos_arg3>, --pos_arg3=<pos_arg3>  : pos arg 3
        Returns:
            pos args
        """
        out = (pos_arg, pos_args, pos_arg2, pos_arg3, a_arg, b_arg)
        response = yield self._render_response(out)
        defer.returnValue(response)


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
