import binascii
import logging.handlers
import mimetypes
import os
import base58
import requests
import urllib
import json
import textwrap
import signal
from copy import deepcopy
from twisted.web import server
from twisted.internet import defer, threads, error, reactor
from twisted.internet.task import LoopingCall
from twisted.python.failure import Failure

from lbryschema.claim import ClaimDict
from lbryschema.uri import parse_lbry_uri
from lbryschema.error import URIParseError, DecodeError
from lbryschema.validator import validate_claim_id
from lbryschema.address import decode_address
from lbryschema.decode import smart_decode

# TODO: importing this when internet is disabled raises a socket.gaierror
from lbrynet.core.system_info import get_lbrynet_version
from lbrynet.database.storage import SQLiteStorage
from lbrynet import conf
from lbrynet.conf import LBRYCRD_WALLET, LBRYUM_WALLET
from lbrynet.reflector import reupload
from lbrynet.reflector import ServerFactory as reflector_server_factory
from lbrynet.core.log_support import configure_loggly_handler
from lbrynet.lbry_file.client.EncryptedFileDownloader import EncryptedFileSaverFactory
from lbrynet.lbry_file.client.EncryptedFileOptions import add_lbry_file_to_sd_identifier
from lbrynet.file_manager.EncryptedFileManager import EncryptedFileManager
from lbrynet.daemon.Downloader import GetStream
from lbrynet.daemon.Publisher import Publisher
from lbrynet.daemon.ExchangeRateManager import ExchangeRateManager
from lbrynet.daemon.auth.server import AuthJSONRPCServer
from lbrynet.core.PaymentRateManager import OnlyFreePaymentsManager
from lbrynet.core import utils, system_info
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier, download_sd_blob
from lbrynet.core.StreamDescriptor import EncryptedFileStreamType
from lbrynet.core.Session import Session
from lbrynet.core.Wallet import LBRYumWallet
from lbrynet.core.looping_call_manager import LoopingCallManager
from lbrynet.core.server.BlobRequestHandler import BlobRequestHandlerFactory
from lbrynet.core.server.ServerProtocol import ServerProtocolFactory
from lbrynet.core.Error import InsufficientFundsError, UnknownNameError
from lbrynet.core.Error import DownloadDataTimeout, DownloadSDTimeout
from lbrynet.core.Error import NullFundsError, NegativeFundsError
from lbrynet.dht.error import TimeoutError
from lbrynet.core.Peer import Peer
from lbrynet.core.SinglePeerDownloader import SinglePeerDownloader
from lbrynet.core.client.StandaloneBlobDownloader import StandaloneBlobDownloader

log = logging.getLogger(__name__)

INITIALIZING_CODE = 'initializing'
LOADING_DB_CODE = 'loading_db'
LOADING_WALLET_CODE = 'loading_wallet'
LOADING_FILE_MANAGER_CODE = 'loading_file_manager'
LOADING_SERVER_CODE = 'loading_server'
STARTED_CODE = 'started'
WAITING_FOR_FIRST_RUN_CREDITS = 'waiting_for_credits'
WAITING_FOR_UNLOCK = 'waiting_for_wallet_unlock'
STARTUP_STAGES = [
    (INITIALIZING_CODE, 'Initializing'),
    (LOADING_DB_CODE, 'Loading databases'),
    (LOADING_WALLET_CODE, 'Catching up with the blockchain'),
    (LOADING_FILE_MANAGER_CODE, 'Setting up file manager'),
    (LOADING_SERVER_CODE, 'Starting lbrynet'),
    (STARTED_CODE, 'Started lbrynet'),
    (WAITING_FOR_FIRST_RUN_CREDITS, 'Waiting for first run credits'),
    (WAITING_FOR_UNLOCK, 'Waiting for user to unlock the wallet using the wallet_unlock command')
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
MAX_UPDATE_FEE_ESTIMATE = 0.3


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
    SD_HASH = 'sd_hash'
    FILE_NAME = 'file_name'
    STREAM_HASH = 'stream_hash'
    ROWID = "rowid"
    CLAIM_ID = "claim_id"
    OUTPOINT = "outpoint"
    TXID = "txid"
    NOUT = "nout"
    CHANNEL_CLAIM_ID = "channel_claim_id"
    CLAIM_NAME = "claim_name"
    CHANNEL_NAME = "channel_name"


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


class Daemon(AuthJSONRPCServer):
    """
    LBRYnet daemon, a jsonrpc interface to lbry functions
    """

    allowed_during_startup = [
        'daemon_stop', 'status', 'version', 'wallet_unlock'
    ]

    def __init__(self, analytics_manager):
        AuthJSONRPCServer.__init__(self, conf.settings['use_auth_http'])
        self.db_dir = conf.settings['data_dir']
        self.storage = SQLiteStorage(self.db_dir)
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
        self.auto_renew_claim_height_delta = conf.settings['auto_renew_claim_height_delta']

        self.startup_status = STARTUP_STAGES[0]
        self.connected_to_internet = True
        self.connection_status_code = None
        self.platform = None
        self.current_db_revision = 9
        self.db_revision_file = conf.settings.get_db_revision_filename()
        self.session = None
        self._session_id = conf.settings.get_session_id()
        # TODO: this should probably be passed into the daemon, or
        # possibly have the entire log upload functionality taken out
        # of the daemon, but I don't want to deal with that now

        self.analytics_manager = analytics_manager
        self.node_id = conf.settings.node_id

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
        self.lbry_file_manager = None

    @defer.inlineCallbacks
    def setup(self):
        reactor.addSystemEventTrigger('before', 'shutdown', self._shutdown)
        configure_loggly_handler()

        log.info("Starting lbrynet-daemon")

        self.looping_call_manager.start(Checker.INTERNET_CONNECTION, 3600)
        self.looping_call_manager.start(Checker.CONNECTION_STATUS, 30)
        self.exchange_rate_manager.start()

        yield self._initial_setup()
        yield threads.deferToThread(self._setup_data_directory)
        migrated = yield self._check_db_migration()
        yield self.storage.setup()
        yield self._get_session()
        yield self._check_wallet_locked()
        yield self._start_analytics()
        yield add_lbry_file_to_sd_identifier(self.sd_identifier)
        yield self._setup_stream_identifier()
        yield self._setup_lbry_file_manager()
        yield self._setup_query_handlers()
        yield self._setup_server()
        log.info("Starting balance: " + str(self.session.wallet.get_balance()))
        self.announced_startup = True
        self.startup_status = STARTUP_STAGES[5]
        log.info("Started lbrynet-daemon")

        ###
        # this should be removed with the next db revision
        if migrated:
            missing_channel_claim_ids = yield self.storage.get_unknown_certificate_ids()
            while missing_channel_claim_ids:  # in case there are a crazy amount lets batch to be safe
                batch = missing_channel_claim_ids[:100]
                _ = yield self.session.wallet.get_claims_by_ids(*batch)
                missing_channel_claim_ids = missing_channel_claim_ids[100:]
        ###

        self._auto_renew()

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

    def _update_connection_status(self):
        self.connection_status_code = CONNECTION_STATUS_CONNECTED

        if not self.connected_to_internet:
            self.connection_status_code = CONNECTION_STATUS_NETWORK

    @defer.inlineCallbacks
    def _auto_renew(self):
        # automatically renew claims
        # auto renew is turned off if 0 or some negative number
        if self.auto_renew_claim_height_delta < 1:
            defer.returnValue(None)
        if not self.session.wallet.network.get_remote_height():
            log.warning("Failed to get remote height, aborting auto renew")
            defer.returnValue(None)
        log.debug("Renewing claim")
        h = self.session.wallet.network.get_remote_height() + self.auto_renew_claim_height_delta
        results = yield self.session.wallet.claim_renew_all_before_expiration(h)
        for outpoint, result in results.iteritems():
            if result['success']:
                log.info("Renewed claim at outpoint:%s claim ID:%s, paid fee:%s",
                         outpoint, result['claim_id'], result['fee'])
            else:
                log.info("Failed to renew claim at outpoint:%s, reason:%s",
                         outpoint, result['reason'])

    def _start_server(self):
        if self.peer_port is not None:
            server_factory = ServerProtocolFactory(self.session.rate_limiter,
                                                   self.query_handlers,
                                                   self.session.peer_manager)

            try:
                log.info("Peer protocol listening on TCP %d", self.peer_port)
                self.lbry_server_port = reactor.listenTCP(self.peer_port, server_factory)
            except error.CannotListenError as e:
                import traceback
                log.error("Couldn't bind to port %d. Visit lbry.io/faq/how-to-change-port for"
                          " more details.", self.peer_port)
                log.error("%s", traceback.format_exc())
                raise ValueError("%s lbrynet may already be running on your computer." % str(e))
        return defer.succeed(True)

    def _start_reflector(self):
        if self.run_reflector_server:
            log.info("Starting reflector server")
            if self.reflector_port is not None:
                reflector_factory = reflector_server_factory(
                    self.session.peer_manager,
                    self.session.blob_manager,
                    self.lbry_file_manager
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

    @staticmethod
    def _already_shutting_down(sig_num, frame):
        log.info("Already shutting down")

    def _stop_streams(self):
        """stop pending GetStream downloads"""
        for sd_hash, stream in self.streams.iteritems():
            stream.cancel(reason="daemon shutdown")

    def _shutdown(self):
        # ignore INT/TERM signals once shutdown has started
        signal.signal(signal.SIGINT, self._already_shutting_down)
        signal.signal(signal.SIGTERM, self._already_shutting_down)

        log.info("Closing lbrynet session")
        log.info("Status at time of shutdown: " + self.startup_status[0])

        self._stop_streams()
        self.looping_call_manager.shutdown()
        if self.analytics_manager:
            self.analytics_manager.shutdown()

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
            'auto_renew_claim_height_delta': int
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
                    converted = setting_type(settings[key])
                    conf.settings.update({key: converted},
                                            data_types=(conf.TYPE_RUNTIME, conf.TYPE_PERSISTED))
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
            self._write_db_revision_file(self.current_db_revision)

    @defer.inlineCallbacks
    def _check_db_migration(self):
        old_revision = 1
        migrated = False
        if os.path.exists(self.db_revision_file):
            with open(self.db_revision_file, "r") as revision_read_handle:
                old_revision = int(revision_read_handle.read().strip())

        if old_revision > self.current_db_revision:
            raise Exception('This version of lbrynet is not compatible with the database\n'
                            'Your database is revision %i, expected %i' %
                            (old_revision, self.current_db_revision))
        if old_revision < self.current_db_revision:
            from lbrynet.database.migrator import dbmigrator
            log.info("Upgrading your databases (revision %i to %i)", old_revision, self.current_db_revision)
            yield threads.deferToThread(
                dbmigrator.migrate_db, self.db_dir, old_revision, self.current_db_revision
            )
            self._write_db_revision_file(self.current_db_revision)
            log.info("Finished upgrading the databases.")
            migrated = True
        defer.returnValue(migrated)

    @defer.inlineCallbacks
    def _setup_lbry_file_manager(self):
        log.info('Starting the file manager')
        self.startup_status = STARTUP_STAGES[3]
        self.lbry_file_manager = EncryptedFileManager(self.session, self.sd_identifier)
        yield self.lbry_file_manager.setup()
        log.info('Done setting up file manager')

    def _start_analytics(self):
        if not self.analytics_manager.is_started:
            self.analytics_manager.start()

    def _get_session(self):
        def get_wallet():
            if self.wallet_type == LBRYCRD_WALLET:
                raise ValueError('LBRYcrd Wallet is no longer supported')
            elif self.wallet_type == LBRYUM_WALLET:

                log.info("Using lbryum wallet")

                lbryum_servers = {address: {'t': str(port)}
                                  for address, port in conf.settings['lbryum_servers']}

                config = {
                    'auto_connect': True,
                    'chain': conf.settings['blockchain_name'],
                    'default_servers': lbryum_servers
                }

                if 'use_keyring' in conf.settings:
                    config['use_keyring'] = conf.settings['use_keyring']
                if conf.settings['lbryum_wallet_dir']:
                    config['lbryum_path'] = conf.settings['lbryum_wallet_dir']
                wallet = LBRYumWallet(self.storage, config)
                return defer.succeed(wallet)
            else:
                raise ValueError('Wallet Type {} is not valid'.format(self.wallet_type))

        d = get_wallet()

        def create_session(wallet):
            self.session = Session(
                conf.settings['data_rate'],
                db_dir=self.db_dir,
                node_id=self.node_id,
                blob_dir=self.blobfile_dir,
                dht_node_port=self.dht_node_port,
                known_dht_nodes=conf.settings['known_dht_nodes'],
                peer_port=self.peer_port,
                use_upnp=self.use_upnp,
                wallet=wallet,
                is_generous=conf.settings['is_generous_host'],
                external_ip=self.platform['ip'],
                storage=self.storage
            )
            self.startup_status = STARTUP_STAGES[2]

        d.addCallback(create_session)
        d.addCallback(lambda _: self.session.setup())
        return d

    @defer.inlineCallbacks
    def _check_wallet_locked(self):
        wallet = self.session.wallet
        if wallet.wallet.use_encryption:
            self.startup_status = STARTUP_STAGES[7]

        yield wallet.check_locked()

    def _setup_stream_identifier(self):
        file_saver_factory = EncryptedFileSaverFactory(
            self.session.peer_finder,
            self.session.rate_limiter,
            self.session.blob_manager,
            self.session.storage,
            self.session.wallet,
            self.download_directory
        )
        self.sd_identifier.add_stream_downloader_factory(EncryptedFileStreamType,
                                                         file_saver_factory)
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
        downloader = StandaloneBlobDownloader(
            blob_hash, self.session.blob_manager, self.session.peer_finder, self.session.rate_limiter,
            rate_manager, self.session.wallet, timeout
        )
        return downloader.download()

    @defer.inlineCallbacks
    def _get_stream_analytics_report(self, claim_dict):
        sd_hash = claim_dict.source_hash
        try:
            stream_hash = yield self.session.storage.get_stream_hash_for_sd_hash(sd_hash)
        except Exception:
            stream_hash = None
        report = {
            "sd_hash": sd_hash,
            "stream_hash": stream_hash,
        }
        blobs = {}
        try:
            sd_host = yield self.session.blob_manager.get_host_downloaded_from(sd_hash)
        except Exception:
            sd_host = None
        report["sd_blob"] = sd_host
        if stream_hash:
            blob_infos = yield self.session.storage.get_blobs_for_stream(stream_hash)
            report["known_blobs"] = len(blob_infos)
        else:
            blob_infos = []
            report["known_blobs"] = 0
        # for blob_hash, blob_num, iv, length in blob_infos:
        #     try:
        #         host = yield self.session.blob_manager.get_host_downloaded_from(blob_hash)
        #     except Exception:
        #         host = None
        #     if host:
        #         blobs[blob_num] = host
        # report["blobs"] = json.dumps(blobs)
        defer.returnValue(report)

    @defer.inlineCallbacks
    def _download_name(self, name, claim_dict, sd_hash, txid, nout, timeout=None, file_name=None):
        """
        Add a lbry file to the file manager, start the download, and return the new lbry file.
        If it already exists in the file manager, return the existing lbry file
        """

        @defer.inlineCallbacks
        def _download_finished(download_id, name, claim_dict):
            report = yield self._get_stream_analytics_report(claim_dict)
            self.analytics_manager.send_download_finished(download_id, name, report, claim_dict)

        @defer.inlineCallbacks
        def _download_failed(error, download_id, name, claim_dict):
            report = yield self._get_stream_analytics_report(claim_dict)
            self.analytics_manager.send_download_errored(error, download_id, name, claim_dict,
                                                         report)

        if sd_hash in self.streams:
            downloader = self.streams[sd_hash]
            result = yield downloader.finished_deferred
            defer.returnValue(result)
        else:
            download_id = utils.random_string()
            self.analytics_manager.send_download_started(download_id, name, claim_dict)

            self.streams[sd_hash] = GetStream(self.sd_identifier, self.session,
                                              self.exchange_rate_manager, self.max_key_fee,
                                              self.disable_max_key_fee,
                                              conf.settings['data_rate'], timeout)
            try:
                lbry_file, finished_deferred = yield self.streams[sd_hash].start(
                    claim_dict, name, txid, nout, file_name
                )
                finished_deferred.addCallbacks(
                    lambda _: _download_finished(download_id, name, claim_dict),
                    lambda e: _download_failed(e, download_id, name, claim_dict)
                )
                result = yield self._get_lbry_file_dict(lbry_file, full_status=True)
            except Exception as err:
                yield _download_failed(err, download_id, name, claim_dict)
                if isinstance(err, (DownloadDataTimeout, DownloadSDTimeout)):
                    log.warning('Failed to get %s (%s)', name, err)
                else:
                    log.error('Failed to get %s (%s)', name, err)
                if self.streams[sd_hash].downloader:
                    yield self.streams[sd_hash].downloader.stop(err)
                result = {'error': err.message}
            finally:
                del self.streams[sd_hash]
            defer.returnValue(result)

    @defer.inlineCallbacks
    def _publish_stream(self, name, bid, claim_dict, file_path=None, certificate_id=None,
                        claim_address=None, change_address=None):

        publisher = Publisher(self.session, self.lbry_file_manager, self.session.wallet,
                              certificate_id)
        parse_lbry_uri(name)
        if not file_path:
            stream_hash = yield self.storage.get_stream_hash_for_sd_hash(claim_dict['stream']['source']['source'])
            claim_out = yield publisher.publish_stream(name, bid, claim_dict, stream_hash, claim_address,
                                                       change_address)
        else:
            claim_out = yield publisher.create_and_publish_stream(name, bid, claim_dict, file_path,
                                                                  claim_address, change_address)
            if conf.settings['reflect_uploads']:
                d = reupload.reflect_file(publisher.lbry_file)
                d.addCallbacks(lambda _: log.info("Reflected new publication to lbry://%s", name),
                               log.exception)
        self.analytics_manager.send_claim_action('publish')
        log.info("Success! Published to lbry://%s txid: %s nout: %d", name, claim_out['txid'],
                 claim_out['nout'])
        defer.returnValue(claim_out)

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
        reactor.callLater(conf.settings['search_timeout'], _check_est, d)
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
            written_bytes = 0

        size = num_completed = num_known = status = None

        if full_status:
            size = yield lbry_file.get_total_bytes()
            file_status = yield lbry_file.status()
            num_completed = file_status.num_completed
            num_known = file_status.num_known
            status = file_status.running_status

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
            'download_path': full_path,
            'mime_type': mime_type,
            'key': key,
            'total_bytes': size,
            'written_bytes': written_bytes,
            'blobs_completed': num_completed,
            'blobs_in_stream': num_known,
            'status': status,
            'claim_id': lbry_file.claim_id,
            'txid': lbry_file.txid,
            'nout': lbry_file.nout,
            'outpoint': lbry_file.outpoint,
            'metadata': lbry_file.metadata,
            'channel_claim_id': lbry_file.channel_claim_id,
            'channel_name': lbry_file.channel_name,
            'claim_name': lbry_file.claim_name
        }
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
    def _get_lbry_files(self, return_json=False, full_status=True, **kwargs):
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

    def _get_single_peer_downloader(self):
        downloader = SinglePeerDownloader()
        downloader.setup(self.session.wallet)
        return downloader

    @defer.inlineCallbacks
    def _blob_availability(self, blob_hash, search_timeout, blob_timeout, downloader=None):
        if not downloader:
            downloader = self._get_single_peer_downloader()
        result = {}
        search_timeout = search_timeout or conf.settings['peer_search_timeout']
        blob_timeout = blob_timeout or conf.settings['sd_download_timeout']
        is_available = False
        reachable_peers = []
        unreachable_peers = []
        try:
            peers = yield self.jsonrpc_peer_list(blob_hash, search_timeout)
            peer_infos = [{"peer": Peer(x[0], x[1]),
                           "blob_hash": blob_hash,
                           "timeout": blob_timeout} for x in peers if x[2]]
            dl = []
            dl_peers = []
            dl_results = []
            for peer_info in peer_infos:
                d = downloader.download_temp_blob_from_peer(**peer_info)
                dl.append(d)
                dl_peers.append("%s:%i" % (peer_info['peer'].host, peer_info['peer'].port))
            for dl_peer, (success, download_result) in zip(dl_peers,
                                                           (yield defer.DeferredList(dl))):
                if success:
                    if download_result:
                        reachable_peers.append(dl_peer)
                    else:
                        unreachable_peers.append(dl_peer)
                    dl_results.append(download_result)
            is_available = any(dl_results)
        except Exception as err:
            result['error'] = "Failed to get peers for blob: %s" % err

        response = {
            'is_available': is_available,
            'reachable_peers': reachable_peers,
            'unreachable_peers': unreachable_peers,
        }
        defer.returnValue(response)

    ############################################################################
    #                                                                          #
    #                JSON-RPC API methods start here                           #
    #                                                                          #
    ############################################################################

    @defer.inlineCallbacks
    def jsonrpc_status(self, session_status=False):
        """
        Get daemon status

        Usage:
            status [--session_status]

        Options:
            --session_status  : (bool) include session status in results

        Returns:
            (dict) lbrynet-daemon status
            {
                'lbry_id': lbry peer id, base58,
                'installation_id': installation id, base58,
                'is_running': bool,
                'is_first_run': bool,
                'startup_status': {
                    'code': status code,
                    'message': status message
                },
                'connection_status': {
                    'code': connection status code,
                    'message': connection status message
                },
                'blockchain_status': {
                    'blocks': local blockchain height,
                    'blocks_behind': remote_height - local_height,
                    'best_blockhash': block hash of most recent block,
                },
                'wallet_is_encrypted': bool,

                If given the session status option:
                    'session_status': {
                        'managed_blobs': count of blobs in the blob manager,
                        'managed_streams': count of streams in the file manager
                        'announce_queue_size': number of blobs currently queued to be announced
                        'should_announce_blobs': number of blobs that should be announced
                    }
            }
        """

        # on startup, the wallet or network won't be available but we still need this call to work
        has_wallet = self.session and self.session.wallet and self.session.wallet.network
        local_height = self.session.wallet.network.get_local_height() if has_wallet else 0
        remote_height = self.session.wallet.network.get_server_height() if has_wallet else 0
        best_hash = (yield self.session.wallet.get_best_blockhash()) if has_wallet else None
        wallet_is_encrypted = has_wallet and self.session.wallet.wallet and \
                              self.session.wallet.wallet.use_encryption

        response = {
            'lbry_id': base58.b58encode(self.node_id),
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
            'wallet_is_encrypted': wallet_is_encrypted,
            'blocks_behind': remote_height - local_height,  # deprecated. remove from UI, then here
            'blockchain_status': {
                'blocks': local_height,
                'blocks_behind': remote_height - local_height,
                'best_blockhash': best_hash,
            }
        }
        if session_status:
            blobs = yield self.session.blob_manager.get_all_verified_blobs()
            announce_queue_size = self.session.hash_announcer.hash_queue_size()
            should_announce_blobs = yield self.session.blob_manager.count_should_announce_blobs()
            response['session_status'] = {
                'managed_blobs': len(blobs),
                'managed_streams': len(self.lbry_file_manager.lbry_files),
                'announce_queue_size': announce_queue_size,
                'should_announce_blobs': should_announce_blobs,
            }
        defer.returnValue(response)

    def jsonrpc_version(self):
        """
        Get lbry version information

        Usage:
            version

        Options:
            None

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

    # @AuthJSONRPCServer.deprecated() # deprecated actually disables the call
    def jsonrpc_report_bug(self, message=None):
        """
        Report a bug to slack

        Usage:
            report_bug (<message> | --message=<message>)

        Options:
            --message=<message> : (str) Description of the bug

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

        Options:
            None

        Returns:
            (dict) Dictionary of daemon settings
            See ADJUSTABLE_SETTINGS in lbrynet/conf.py for full list of settings
        """
        return self._render_response(conf.settings.get_adjustable_settings_dict())

    @defer.inlineCallbacks
    def jsonrpc_settings_set(self, **kwargs):
        """
        Set daemon settings

        Usage:
            settings_set [--download_directory=<download_directory>]
                         [--data_rate=<data_rate>]
                         [--download_timeout=<download_timeout>]
                         [--peer_port=<peer_port>]
                         [--max_key_fee=<max_key_fee>]
                         [--disable_max_key_fee=<disable_max_key_fee>]
                         [--use_upnp=<use_upnp>]
                         [--run_reflector_server=<run_reflector_server>]
                         [--cache_time=<cache_time>]
                         [--reflect_uploads=<reflect_uploads>]
                         [--share_usage_data=<share_usage_data>]
                         [--peer_search_timeout=<peer_search_timeout>]
                         [--sd_download_timeout=<sd_download_timeout>]
                         [--auto_renew_claim_height_delta=<auto_renew_claim_height_delta>]

        Options:
            --download_directory=<download_directory>  : (str) path of download directory
            --data_rate=<data_rate>                    : (float) 0.0001
            --download_timeout=<download_timeout>      : (int) 180
            --peer_port=<peer_port>                    : (int) 3333
            --max_key_fee=<max_key_fee>                : (dict) maximum key fee for downloads,
                                                          in the format:
                                                          {
                                                            'currency': <currency_symbol>,
                                                            'amount': <amount>
                                                          }.
                                                          In the CLI, it must be an escaped JSON string
                                                          Supported currency symbols: LBC, USD, BTC
            --disable_max_key_fee=<disable_max_key_fee> : (bool) False
            --use_upnp=<use_upnp>            : (bool) True
            --run_reflector_server=<run_reflector_server>  : (bool) False
            --cache_time=<cache_time>  : (int) 150
            --reflect_uploads=<reflect_uploads>  : (bool) True
            --share_usage_data=<share_usage_data>  : (bool) True
            --peer_search_timeout=<peer_search_timeout>  : (int) 3
            --sd_download_timeout=<sd_download_timeout>  : (int) 3
            --auto_renew_claim_height_delta=<auto_renew_claim_height_delta> : (int) 0
                claims set to expire within this many blocks will be
                automatically renewed after startup (if set to 0, renews
                will not be made automatically)


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
            --command=<command>  : (str) command to retrieve documentation for

        Returns:
            (str) Help message
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
            'help': textwrap.dedent(fn.__doc__ or '')
        })

    def jsonrpc_commands(self):
        """
        Return a list of available commands

        Usage:
            commands

        Options:
            None

        Returns:
            (list) list of available commands
        """
        return self._render_response(sorted([command for command in self.callable_methods.keys()]))

    def jsonrpc_wallet_balance(self, address=None, include_unconfirmed=False):
        """
        Return the balance of the wallet

        Usage:
            wallet_balance [<address> | --address=<address>] [--include_unconfirmed]

        Options:
            --address=<address>     : (str) If provided only the balance for this
                                      address will be given
            --include_unconfirmed   : (bool) Include unconfirmed

        Returns:
            (float) amount of lbry credits in wallet
        """
        if address is None:
            return self._render_response(float(self.session.wallet.get_balance()))
        else:
            return self._render_response(float(
                self.session.wallet.get_address_balance(address, include_unconfirmed)))

    @defer.inlineCallbacks
    def jsonrpc_wallet_unlock(self, password):
        """
        Unlock an encrypted wallet

        Usage:
            wallet_unlock (<password> | --password=<password>)

        Options:
            --password=<password> : (str) password for unlocking wallet

        Returns:
            (bool) true if wallet is unlocked, otherwise false
        """

        cmd_runner = self.session.wallet.get_cmd_runner()
        if cmd_runner.locked:
            d = self.session.wallet.wallet_unlocked_d
            d.callback(password)
            result = yield d
        else:
            result = True
        response = yield self._render_response(result)
        defer.returnValue(response)

    @defer.inlineCallbacks
    def jsonrpc_wallet_decrypt(self):
        """
        Decrypt an encrypted wallet, this will remove the wallet password

        Usage:
            wallet_decrypt

        Options:
            None

        Returns:
            (bool) true if wallet is decrypted, otherwise false
        """

        result = self.session.wallet.decrypt_wallet()
        response = yield self._render_response(result)
        defer.returnValue(response)

    @defer.inlineCallbacks
    def jsonrpc_wallet_encrypt(self, new_password):
        """
        Encrypt a wallet with a password, if the wallet is already encrypted this will update
        the password

        Usage:
            wallet_encrypt (<new_password> | --new_password=<new_password>)

        Options:
            --new_password=<new_password> : (str) password string to be used for encrypting wallet

        Returns:
            (bool) true if wallet is decrypted, otherwise false
        """

        self.session.wallet.encrypt_wallet(new_password)
        response = yield self._render_response(self.session.wallet.wallet.use_encryption)
        defer.returnValue(response)

    @defer.inlineCallbacks
    def jsonrpc_daemon_stop(self):
        """
        Stop lbrynet-daemon

        Usage:
            daemon_stop

        Options:
            None

        Returns:
            (string) Shutdown message
        """

        log.info("Shutting down lbrynet daemon")
        response = yield self._render_response("Shutting down")
        reactor.callLater(0.1, reactor.fireSystemEvent, "shutdown")
        defer.returnValue(response)

    @defer.inlineCallbacks
    def jsonrpc_file_list(self, **kwargs):
        """
        List files limited by optional filters

        Usage:
            file_list [--sd_hash=<sd_hash>] [--file_name=<file_name>] [--stream_hash=<stream_hash>]
                      [--rowid=<rowid>] [--claim_id=<claim_id>] [--outpoint=<outpoint>] [--txid=<txid>] [--nout=<nout>]
                      [--channel_claim_id=<channel_claim_id>] [--channel_name=<channel_name>]
                      [--claim_name=<claim_name>] [--full_status]

        Options:
            --sd_hash=<sd_hash>                    : (str) get file with matching sd hash
            --file_name=<file_name>                : (str) get file with matching file name in the
                                                     downloads folder
            --stream_hash=<stream_hash>            : (str) get file with matching stream hash
            --rowid=<rowid>                        : (int) get file with matching row id
            --claim_id=<claim_id>                  : (str) get file with matching claim id
            --outpoint=<outpoint>                  : (str) get file with matching claim outpoint
            --txid=<txid>                          : (str) get file with matching claim txid
            --nout=<nout>                          : (int) get file with matching claim nout
            --channel_claim_id=<channel_claim_id>  : (str) get file with matching channel claim id
            --channel_name=<channel_name>  : (str) get file with matching channel name
            --claim_name=<claim_name>              : (str) get file with matching claim name
            --full_status                          : (bool) full status, populate the
                                                     'message' and 'size' fields

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
                    'download_path': (str) download path of file,
                    'mime_type': (str) mime type of file,
                    'key': (str) key attached to file,
                    'total_bytes': (int) file size in bytes, None if full_status is false,
                    'written_bytes': (int) written size in bytes,
                    'blobs_completed': (int) num_completed, None if full_status is false,
                    'blobs_in_stream': (int) None if full_status is false,
                    'status': (str) downloader status, None if full_status is false,
                    'claim_id': (str) None if full_status is false or if claim is not found,
                    'outpoint': (str) None if full_status is false or if claim is not found,
                    'txid': (str) None if full_status is false or if claim is not found,
                    'nout': (int) None if full_status is false or if claim is not found,
                    'metadata': (dict) None if full_status is false or if claim is not found,
                    'channel_claim_id': (str) None if full_status is false or if claim is not found or signed,
                    'channel_name': (str) None if full_status is false or if claim is not found or signed,
                    'claim_name': (str) None if full_status is false or if claim is not found
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

        Usage:
            resolve_name (<name> | --name=<name>) [--force]

        Options:
            --name=<name> : (str) the name to resolve
            --force       : (bool) force refresh and do not check cache

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
            --txid=<txid>              : (str) look for claim with this txid, nout must
                                         also be specified
            --nout=<nout>              : (int) look for claim with this nout, txid must
                                         also be specified
            --claim_id=<claim_id>  : (str) look for claim with this claim id

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
            claim_results = yield self.session.wallet.get_claim_by_outpoint(txid, int(nout))
        else:
            raise Exception("Must specify either txid/nout, or claim_id")
        response = yield self._render_response(claim_results)
        defer.returnValue(response)

    @defer.inlineCallbacks
    def jsonrpc_resolve(self, force=False, uri=None, uris=[]):
        """
        Resolve given LBRY URIs

        Usage:
            resolve [--force] (<uri> | --uri=<uri>) [<uris>...]

        Options:
            --force  : (bool) force refresh and ignore cache
            --uri=<uri>    : (str) uri to resolve
            --uris=<uris>   : (list) uris to resolve

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
                        'permanent_url': (str) permanent url of the certificate claim,
                        'supports: (list) list of supports [{'txid': (str) txid,
                                                             'nout': (int) nout,
                                                             'amount': (float) amount}],
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
                        'permanent_url': (str) permanent url of the claim,
                        'channel_name': (str) channel name if claim is in a channel
                        'supports: (list) list of supports [{'txid': (str) txid,
                                                             'nout': (int) nout,
                                                             'amount': (float) amount}]
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
                valid_uris += (u,)
            except URIParseError:
                results[u] = {"error": "%s is not a valid uri" % u}

        resolved = yield self.session.wallet.resolve(*valid_uris, check_cache=not force)

        for resolved_uri in resolved:
            results[resolved_uri] = resolved[resolved_uri]
        response = yield self._render_response(results)
        defer.returnValue(response)

    @defer.inlineCallbacks
    def jsonrpc_get(self, uri, file_name=None, timeout=None):
        """
        Download stream from a LBRY name.

        Usage:
            get <uri> [<file_name> | --file_name=<file_name>] [<timeout> | --timeout=<timeout>]


        Options:
            --uri=<uri>              : (str) uri of the content to download
            --file_name=<file_name>  : (str) specified name for the downloaded file
            --timeout=<timeout>      : (int) download timeout in number of seconds

        Returns:
            (dict) Dictionary containing information about the stream
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
                'download_path': (str) download path of file,
                'mime_type': (str) mime type of file,
                'key': (str) key attached to file,
                'total_bytes': (int) file size in bytes, None if full_status is false,
                'written_bytes': (int) written size in bytes,
                'blobs_completed': (int) num_completed, None if full_status is false,
                'blobs_in_stream': (int) None if full_status is false,
                'status': (str) downloader status, None if full_status is false,
                'claim_id': (str) claim id,
                'outpoint': (str) claim outpoint string,
                'txid': (str) claim txid,
                'nout': (int) claim nout,
                'metadata': (dict) claim metadata,
                'channel_claim_id': (str) None if claim is not signed
                'channel_name': (str) None if claim is not signed
                'claim_name': (str) claim name
            }
        """

        timeout = timeout if timeout is not None else self.download_timeout

        parsed_uri = parse_lbry_uri(uri)
        if parsed_uri.is_channel and not parsed_uri.path:
            raise Exception("cannot download a channel claim, specify a /path")

        resolved_result = yield self.session.wallet.resolve(uri)
        if resolved_result and uri in resolved_result:
            resolved = resolved_result[uri]
        else:
            resolved = None

        if not resolved or 'value' not in resolved:
            if 'claim' not in resolved:
                raise Exception(
                    "Failed to resolve stream at lbry://{}".format(uri.replace("lbry://", ""))
                )
            else:
                resolved = resolved['claim']
        txid, nout, name = resolved['txid'], resolved['nout'], resolved['name']
        claim_dict = ClaimDict.load_dict(resolved['value'])
        sd_hash = claim_dict.source_hash

        if sd_hash in self.streams:
            log.info("Already waiting on lbry://%s to start downloading", name)
            yield self.streams[sd_hash].data_downloading_deferred

        lbry_file = yield self._get_lbry_file(FileID.SD_HASH, sd_hash, return_json=False)

        if lbry_file:
            if not os.path.isfile(os.path.join(lbry_file.download_directory, lbry_file.file_name)):
                log.info("Already have lbry file but missing file in %s, rebuilding it",
                         lbry_file.download_directory)
                yield lbry_file.start()
            else:
                log.info('Already have a file for %s', name)
            result = yield self._get_lbry_file_dict(lbry_file, full_status=True)
        else:
            result = yield self._download_name(name, claim_dict, sd_hash, txid, nout,
                                               timeout=timeout, file_name=file_name)
        response = yield self._render_response(result)
        defer.returnValue(response)

    @defer.inlineCallbacks
    def jsonrpc_file_set_status(self, status, **kwargs):
        """
        Start or stop downloading a file

        Usage:
            file_set_status (<status> | --status=<status>) [--sd_hash=<sd_hash>]
                      [--file_name=<file_name>] [--stream_hash=<stream_hash>] [--rowid=<rowid>]

        Options:
            --status=<status>            : (str) one of "start" or "stop"
            --sd_hash=<sd_hash>          : (str) set status of file with matching sd hash
            --file_name=<file_name>      : (str) set status of file with matching file name in the
                                           downloads folder
            --stream_hash=<stream_hash>  : (str) set status of file with matching stream hash
            --rowid=<rowid>              : (int) set status of file with matching row id

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

    @defer.inlineCallbacks
    def jsonrpc_file_delete(self, delete_from_download_dir=False, delete_all=False, **kwargs):
        """
        Delete a LBRY file

        Usage:
            file_delete [--delete_from_download_dir] [--delete_all] [--sd_hash=<sd_hash>] [--file_name=<file_name>]
                        [--stream_hash=<stream_hash>] [--rowid=<rowid>] [--claim_id=<claim_id>] [--txid=<txid>]
                        [--nout=<nout>] [--claim_name=<claim_name>] [--channel_claim_id=<channel_claim_id>]
                        [--channel_name=<channel_name>]

        Options:
            --delete_from_download_dir             : (bool) delete file from download directory,
                                                    instead of just deleting blobs
            --delete_all                           : (bool) if there are multiple matching files,
                                                     allow the deletion of multiple files.
                                                     Otherwise do not delete anything.
            --sd_hash=<sd_hash>                    : (str) delete by file sd hash
            --file_name<file_name>                 : (str) delete by file name in downloads folder
            --stream_hash=<stream_hash>            : (str) delete by file stream hash
            --rowid=<rowid>                        : (int) delete by file row id
            --claim_id=<claim_id>                  : (str) delete by file claim id
            --txid=<txid>                          : (str) delete by file claim txid
            --nout=<nout>                          : (int) delete by file claim nout
            --claim_name=<claim_name>              : (str) delete by file claim name
            --channel_claim_id=<channel_claim_id>  : (str) delete by file channel claim id
            --channel_name=<channel_name>                 : (str) delete by file channel claim name

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
                if lbry_file.sd_hash in self.streams:
                    del self.streams[lbry_file.sd_hash]
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
            stream_cost_estimate (<uri> | --uri=<uri>) [<size> | --size=<size>]

        Options:
            --uri=<uri>      : (str) uri to use
            --size=<size>  : (float) stream size in bytes. if provided an sd blob won't be
                                     downloaded.

        Returns:
            (float) Estimated cost in lbry credits, returns None if uri is not
                resolvable
        """
        cost = yield self.get_est_cost(uri, size)
        defer.returnValue(cost)

    @defer.inlineCallbacks
    def jsonrpc_channel_new(self, channel_name, amount):
        """
        Generate a publisher key and create a new '@' prefixed certificate claim

        Usage:
            channel_new (<channel_name> | --channel_name=<channel_name>)
                        (<amount> | --amount=<amount>)

        Options:
            --channel_name=<channel_name>    : (str) name of the channel prefixed with '@'
            --amount=<amount>                : (float) bid amount on the channel

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

        yield self.session.wallet.update_balance()
        if amount >= self.session.wallet.get_balance():
            balance = yield self.session.wallet.get_max_usable_balance_for_claim(channel_name)
            max_bid_amount = balance - MAX_UPDATE_FEE_ESTIMATE
            if balance <= MAX_UPDATE_FEE_ESTIMATE:
                raise InsufficientFundsError(
                    "Insufficient funds, please deposit additional LBC. Minimum additional LBC needed {}"
                .   format(MAX_UPDATE_FEE_ESTIMATE - balance))
            elif amount > max_bid_amount:
                raise InsufficientFundsError(
                    "Please lower the bid value, the maximum amount you can specify for this channel is {}"
                    .format(max_bid_amount))

        result = yield self.session.wallet.claim_new_channel(channel_name, amount)
        self.analytics_manager.send_new_channel()
        log.info("Claimed a new channel! Result: %s", result)
        response = yield self._render_response(result)
        defer.returnValue(response)

    @defer.inlineCallbacks
    def jsonrpc_channel_list(self):
        """
        Get certificate claim infos for channels that can be published to

        Usage:
            channel_list

        Options:
            None

        Returns:
            (list) ClaimDict, includes 'is_mine' field to indicate if the certificate claim
            is in the wallet.
        """

        result = yield self.session.wallet.channel_list()
        response = yield self._render_response(result)
        defer.returnValue(response)

    @AuthJSONRPCServer.deprecated("channel_list")
    def jsonrpc_channel_list_mine(self):
        """
        Get certificate claim infos for channels that can be published to (deprecated)

        Usage:
            channel_list_mine

        Options:
            None

        Returns:
            (list) ClaimDict
        """

        return self.jsonrpc_channel_list()

    @defer.inlineCallbacks
    def jsonrpc_channel_export(self, claim_id):
        """
        Export serialized channel signing information for a given certificate claim id

        Usage:
            channel_export (<claim_id> | --claim_id=<claim_id>)

        Options:
            --claim_id=<claim_id> : (str) Claim ID to export information about

        Returns:
            (str) Serialized certificate information
        """

        result = yield self.session.wallet.export_certificate_info(claim_id)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def jsonrpc_channel_import(self, serialized_certificate_info):
        """
        Import serialized channel signing information (to allow signing new claims to the channel)

        Usage:
            channel_import (<serialized_certificate_info> | --serialized_certificate_info=<serialized_certificate_info>)

        Options:
            --serialized_certificate_info=<serialized_certificate_info> : (str) certificate info

        Returns:
            (dict) Result dictionary
        """

        result = yield self.session.wallet.import_certificate_info(serialized_certificate_info)
        defer.returnValue(result)

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
            --name=<name>                  : (str) name of the content
            --bid=<bid>                    : (float) amount to back the claim
            --metadata=<metadata>          : (dict) ClaimDict to associate with the claim.
            --file_path=<file_path>        : (str) path to file to be associated with name. If provided,
                                             a lbry stream of this file will be used in 'sources'.
                                             If no path is given but a sources dict is provided,
                                             it will be used. If neither are provided, an
                                             error is raised.
            --fee=<fee>                    : (dict) Dictionary representing key fee to download content:
                                              {
                                                'currency': currency_symbol,
                                                'amount': float,
                                                'address': str, optional
                                              }
                                              supported currencies: LBC, USD, BTC
                                              If an address is not provided a new one will be
                                              automatically generated. Default fee is zero.
            --title=<title>                : (str) title of the publication
            --description=<description>    : (str) description of the publication
            --author=<author>              : (str) author of the publication
            --language=<language>          : (str) language of the publication
            --license=<license>            : (str) publication license
            --license_url=<license_url>    : (str) publication license url
            --thumbnail=<thumbnail>        : (str) thumbnail url
            --preview=<preview>            : (str) preview url
            --nsfw=<nsfw>                  : (bool) title of the publication
            --sources=<sources>            : (str) {'lbry_sd_hash': sd_hash} specifies sd hash of file
            --channel_name=<channel_name>  : (str) name of the publisher channel name in the wallet
            --channel_id=<channel_id>      : (str) claim id of the publisher channel, does not check
                                             for channel claim being in the wallet. This allows
                                             publishing to a channel where only the certificate
                                             private key is in the wallet.
           --claim_address=<claim_address> : (str) address where the claim is sent to, if not specified
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

        if not isinstance(bid, (float, int)):
            raise TypeError("Bid must be a float or an integer.")

        if bid <= 0.0:
            raise ValueError("Bid value must be greater than 0.0")

        yield self.session.wallet.update_balance()
        if bid >= self.session.wallet.get_balance():
            balance = yield self.session.wallet.get_max_usable_balance_for_claim(name)
            max_bid_amount = balance - MAX_UPDATE_FEE_ESTIMATE
            if balance <= MAX_UPDATE_FEE_ESTIMATE:
                raise InsufficientFundsError(
                    "Insufficient funds, please deposit additional LBC. Minimum additional LBC needed {}"
                    .format(MAX_UPDATE_FEE_ESTIMATE - balance))
            elif bid > max_bid_amount:
                raise InsufficientFundsError(
                    "Please lower the bid value, the maximum amount you can specify for this claim is {}."
                    .format(max_bid_amount))

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
                    address = yield self.session.wallet.get_least_used_address()
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

        # this will be used to verify the format with lbryschema
        claim_copy = deepcopy(claim_dict)
        if sources is not None:
            claim_dict['stream']['source'] = sources
            claim_copy['stream']['source'] = sources
        elif file_path is not None:
            if not os.path.isfile(file_path):
                raise Exception("invalid file path to publish")
            # since the file hasn't yet been made into a stream, we don't have
            # a valid Source for the claim when validating the format, we'll use a fake one
            claim_copy['stream']['source'] = {
                'version': '_0_0_1',
                'sourceType': 'lbry_sd_hash',
                'source': '0' * 96,
                'contentType': ''
            }
        else:
            # there is no existing source to use, and a file was not provided to make a new one
            raise Exception("no source provided to publish")
        try:
            ClaimDict.load_dict(claim_copy)
            # the metadata to use in the claim can be serialized by lbryschema
        except DecodeError as err:
            # there was a problem with a metadata field, raise an error here rather than
            # waiting to find out when we go to publish the claim (after having made the stream)
            raise Exception("invalid publish metadata: %s" % err.message)

        log.info("Publish: %s", {
            'name': name,
            'file_path': file_path,
            'bid': bid,
            'claim_address': claim_address,
            'change_address': change_address,
            'claim_dict': claim_dict,
            'channel_id': channel_id,
            'channel_name': channel_name
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

    @defer.inlineCallbacks
    def jsonrpc_claim_abandon(self, claim_id=None, txid=None, nout=None):
        """
        Abandon a name and reclaim credits from the claim

        Usage:
            claim_abandon [<claim_id> | --claim_id=<claim_id>]
                          [<txid> | --txid=<txid>] [<nout> | --nout=<nout>]

        Options:
            --claim_id=<claim_id> : (str) claim_id of the claim to abandon
            --txid=<txid> : (str) txid of the claim to abandon
            --nout=<nout> : (int) nout of the claim to abandon

        Returns:
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

    @defer.inlineCallbacks
    def jsonrpc_claim_new_support(self, name, claim_id, amount):
        """
        Support a name claim

        Usage:
            claim_new_support (<name> | --name=<name>) (<claim_id> | --claim_id=<claim_id>)
                              (<amount> | --amount=<amount>)

        Options:
            --name=<name> : (str) name of the claim to support
            --claim_id=<claim_id> : (str) claim_id of the claim to support
            --amount=<amount> : (float) amount of support

        Returns:
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

    @defer.inlineCallbacks
    def jsonrpc_claim_renew(self, outpoint=None, height=None):
        """
        Renew claim(s) or support(s)

        Usage:
            claim_renew (<outpoint> | --outpoint=<outpoint>) | (<height> | --height=<height>)

        Options:
            --outpoint=<outpoint> : (str) outpoint of the claim to renew
            --height=<height> : (str) update claims expiring before or at this block height

        Returns:
            (dict) Dictionary where key is the the original claim's outpoint and
            value is the result of the renewal
            {
                outpoint:{

                    'tx' : (str) hex encoded transaction
                    'txid' : (str) txid of resulting claim
                    'nout' : (int) nout of the resulting claim
                    'fee' : (float) fee paid for the claim transaction
                    'claim_id' : (str) claim ID of the resulting claim
                },
            }
        """

        if outpoint is None and height is None:
            raise Exception("must provide an outpoint or a height")
        elif outpoint is not None:
            if len(outpoint.split(":")) == 2:
                txid, nout = outpoint.split(":")
                nout = int(nout)
            else:
                raise Exception("invalid outpoint")
            result = yield self.session.wallet.claim_renew(txid, nout)
            result = {outpoint: result}
        else:
            height = int(height)
            result = yield self.session.wallet.claim_renew_all_before_expiration(height)
        defer.returnValue(result)

    @defer.inlineCallbacks
    def jsonrpc_claim_send_to_address(self, claim_id, address, amount=None):
        """
        Send a name claim to an address

        Usage:
            claim_send_to_address (<claim_id> | --claim_id=<claim_id>)
                                  (<address> | --address=<address>)
                                  [<amount> | --amount=<amount>]

        Options:
            --claim_id=<claim_id>   : (str) claim_id to send
            --address=<address>     : (str) address to send the claim to
            --amount<amount>        : (int) Amount of credits to claim name for, defaults to the current amount
                                            on the claim

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
        result = yield self.session.wallet.send_claim_to_address(claim_id, address, amount)
        response = yield self._render_response(result)
        defer.returnValue(response)

    # TODO: claim_list_mine should be merged into claim_list, but idk how to authenticate it -Grin
    def jsonrpc_claim_list_mine(self):
        """
        List my name claims

        Usage:
            claim_list_mine

        Options:
            None

        Returns:
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
                    'permanent_url': (str) permanent url of the claim,
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

        Options:
            --name=<name> : (str) name of the claim to list info about

        Returns:
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
                    'permanent_url': (str) permanent url of the claim,
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

    @defer.inlineCallbacks
    def jsonrpc_claim_list_by_channel(self, page=0, page_size=10, uri=None, uris=[]):
        """
        Get paginated claims in a channel specified by a channel uri

        Usage:
            claim_list_by_channel (<uri> | --uri=<uri>) [<uris>...] [--page=<page>]
                                   [--page_size=<page_size>]

        Options:
            --uri=<uri>              : (str) uri of the channel
            --uris=<uris>            : (list) uris of the channel
            --page=<page>            : (int) which page of results to return where page 1 is the first
                                             page, defaults to no pages
            --page_size=<page_size>  : (int) number of results in a page, default of 10

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
                            'supports: (list) list of supports [{'txid': (str) txid,
                                                                 'nout': (int) nout,
                                                                 'amount': (float) amount}],
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
            uris += (uri,)

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
                    valid_uris += (chan_uri,)
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

    def jsonrpc_transaction_list(self):
        """
        List transactions belonging to wallet

        Usage:
            transaction_list

        Options:
            None

        Returns:
            (list) List of transactions

            {
                "claim_info": (list) claim info if in txn [{
                                                        "address": (str) address of claim,
                                                        "balance_delta": (float) bid amount,
                                                        "amount": (float) claim amount,
                                                        "claim_id": (str) claim id,
                                                        "claim_name": (str) claim name,
                                                        "nout": (int) nout
                                                        }],
                "abandon_info": (list) abandon info if in txn [{
                                                        "address": (str) address of abandoned claim,
                                                        "balance_delta": (float) returned amount,
                                                        "amount": (float) claim amount,
                                                        "claim_id": (str) claim id,
                                                        "claim_name": (str) claim name,
                                                        "nout": (int) nout
                                                        }],
                "confirmations": (int) number of confirmations for the txn,
                "date": (str) date and time of txn,
                "fee": (float) txn fee,
                "support_info": (list) support info if in txn [{
                                                        "address": (str) address of support,
                                                        "balance_delta": (float) support amount,
                                                        "amount": (float) support amount,
                                                        "claim_id": (str) claim id,
                                                        "claim_name": (str) claim name,
                                                        "is_tip": (bool),
                                                        "nout": (int) nout
                                                        }],
                "timestamp": (int) timestamp,
                "txid": (str) txn id,
                "update_info": (list) update info if in txn [{
                                                        "address": (str) address of claim,
                                                        "balance_delta": (float) credited/debited
                                                        "amount": (float) absolute amount,
                                                        "claim_id": (str) claim id,
                                                        "claim_name": (str) claim name,
                                                        "nout": (int) nout
                                                        }],
                "value": (float) value of txn
            }

        """

        d = self.session.wallet.get_history()
        d.addCallback(lambda r: self._render_response(r))
        return d

    def jsonrpc_transaction_show(self, txid):
        """
        Get a decoded transaction from a txid

        Usage:
            transaction_show (<txid> | --txid=<txid>)

        Options:
            --txid=<txid>  : (str) txid of the transaction

        Returns:
            (dict) JSON formatted transaction
        """

        d = self.session.wallet.get_transaction(txid)
        d.addCallback(lambda r: self._render_response(r))
        return d

    def jsonrpc_wallet_is_address_mine(self, address):
        """
        Checks if an address is associated with the current wallet.

        Usage:
            wallet_is_address_mine (<address> | --address=<address>)

        Options:
            --address=<address>  : (str) address to check

        Returns:
            (bool) true, if address is associated with current wallet
        """

        d = self.session.wallet.address_is_mine(address)
        d.addCallback(lambda is_mine: self._render_response(is_mine))
        return d

    def jsonrpc_wallet_public_key(self, address):
        """
        Get public key from wallet address

        Usage:
            wallet_public_key (<address> | --address=<address>)

        Options:
            --address=<address>  : (str) address for which to get the public key

        Returns:
            (list) list of public keys associated with address.
                Could contain more than one public key if multisig.
        """

        d = self.session.wallet.get_pub_keys(address)
        d.addCallback(lambda r: self._render_response(r))
        return d

    @defer.inlineCallbacks
    def jsonrpc_wallet_list(self):
        """
        List wallet addresses

        Usage:
            wallet_list

        Options:
            None

        Returns:
            List of wallet addresses
        """

        addresses = yield self.session.wallet.list_addresses()
        response = yield self._render_response(addresses)
        defer.returnValue(response)

    def jsonrpc_wallet_new_address(self):
        """
        Generate a new wallet address

        Usage:
            wallet_new_address

        Options:
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

    def jsonrpc_wallet_unused_address(self):
        """
        Return an address containing no balance, will create
        a new address if there is none.

        Usage:
            wallet_unused_address

        Options:
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

    @AuthJSONRPCServer.deprecated("wallet_send")
    @defer.inlineCallbacks
    def jsonrpc_send_amount_to_address(self, amount, address):
        """
        Queue a payment of credits to an address

        Usage:
            send_amount_to_address (<amount> | --amount=<amount>) (<address> | --address=<address>)

        Options:
            --amount=<amount>     : (float) amount to send
            --address=<address>   : (str) address to send credits to

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

    @defer.inlineCallbacks
    def jsonrpc_wallet_send(self, amount, address=None, claim_id=None):
        """
        Send credits. If given an address, send credits to it. If given a claim id, send a tip
        to the owner of a claim specified by uri. A tip is a claim support where the recipient
        of the support is the claim address for the claim being supported.

        Usage:
            wallet_send (<amount> | --amount=<amount>)
                        ((<address> | --address=<address>) | (<claim_id> | --claim_id=<claim_id>))

        Options:
            --amount=<amount>      : (float) amount of credit to send
            --address=<address>    : (str) address to send credits to
            --claim_id=<claim_id>  : (float) claim_id of the claim to send to tip to

        Returns:
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
            # raises an error if the address is invalid
            decode_address(address)
            result = yield self.jsonrpc_send_amount_to_address(amount, address)
        else:
            validate_claim_id(claim_id)
            result = yield self.session.wallet.tip_claim(claim_id, amount)
            self.analytics_manager.send_claim_action('new_support')
        defer.returnValue(result)

    @defer.inlineCallbacks
    def jsonrpc_wallet_prefill_addresses(self, num_addresses, amount, no_broadcast=False):
        """
        Create new addresses, each containing `amount` credits

        Usage:
            wallet_prefill_addresses [--no_broadcast]
                                     (<num_addresses> | --num_addresses=<num_addresses>)
                                     (<amount> | --amount=<amount>)

        Options:
            --no_broadcast                    : (bool) whether to broadcast or not
            --num_addresses=<num_addresses>   : (int) num of addresses to create
            --amount=<amount>                 : (float) initial amount in each address

        Returns:
            (dict) the resulting transaction
        """

        if amount < 0:
            raise NegativeFundsError()
        elif not amount:
            raise NullFundsError()

        broadcast = not no_broadcast
        tx = yield self.session.wallet.create_addresses_with_balance(
            num_addresses, amount, broadcast=broadcast)
        tx['broadcast'] = broadcast
        defer.returnValue(tx)

    @defer.inlineCallbacks
    def jsonrpc_utxo_list(self):
        """
        List unspent transaction outputs

        Usage:
            utxo_list

        Options:
            None

        Returns:
            (list) List of unspent transaction outputs (UTXOs)
            [
                {
                    "address": (str) the output address
                    "amount": (float) unspent amount
                    "height": (int) block height
                    "is_claim": (bool) is the tx a claim
                    "is_coinbase": (bool) is the tx a coinbase tx
                    "is_support": (bool) is the tx a support
                    "is_update": (bool) is the tx an update
                    "nout": (int) nout of the output
                    "txid": (str) txid of the output
                },
                ...
            ]
        """

        unspent = yield self.session.wallet.list_unspent()
        for i, utxo in enumerate(unspent):
            utxo['txid'] = utxo.pop('prevout_hash')
            utxo['nout'] = utxo.pop('prevout_n')
            utxo['amount'] = utxo.pop('value')
            utxo['is_coinbase'] = utxo.pop('coinbase')
            unspent[i] = utxo

        defer.returnValue(unspent)

    def jsonrpc_block_show(self, blockhash=None, height=None):
        """
        Get contents of a block

        Usage:
            block_show (<blockhash> | --blockhash=<blockhash>) | (<height> | --height=<height>)

        Options:
            --blockhash=<blockhash>  : (str) hash of the block to look up
            --height=<height>        : (int) height of the block to look up

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

    @defer.inlineCallbacks
    def jsonrpc_blob_get(self, blob_hash, timeout=None, encoding=None, payment_rate_manager=None):
        """
        Download and return a blob

        Usage:
            blob_get (<blob_hash> | --blob_hash=<blob_hash>) [--timeout=<timeout>]
                     [--encoding=<encoding>] [--payment_rate_manager=<payment_rate_manager>]

        Options:
        --blob_hash=<blob_hash>                        : (str) blob hash of the blob to get
        --timeout=<timeout>                            : (int) timeout in number of seconds
        --encoding=<encoding>                          : (str) by default no attempt at decoding
                                                         is made, can be set to one of the
                                                         following decoders:
                                                            'json'
        --payment_rate_manager=<payment_rate_manager>  : (str) if not given the default payment rate
                                                         manager will be used.
                                                         supported alternative rate managers:
                                                            'only-free'

        Returns:
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
            blob_file.close()
        else:
            result = "Downloaded blob %s" % blob_hash

        response = yield self._render_response(result)
        defer.returnValue(response)

    @defer.inlineCallbacks
    def jsonrpc_blob_delete(self, blob_hash):
        """
        Delete a blob

        Usage:
            blob_delete (<blob_hash> | --blob_hash=<blob_hash)

        Options:
            --blob_hash=<blob_hash>  : (str) blob hash of the blob to delete

        Returns:
            (str) Success/fail message
        """

        if blob_hash not in self.session.blob_manager.blobs:
            response = yield self._render_response("Don't have that blob")
            defer.returnValue(response)
        try:
            stream_hash = yield self.session.storage.get_stream_hash_for_sd_hash(blob_hash)
            yield self.session.storage.delete_stream(stream_hash)
        except Exception as err:
            pass
        yield self.session.blob_manager.delete_blobs([blob_hash])
        response = yield self._render_response("Deleted %s" % blob_hash)
        defer.returnValue(response)

    @defer.inlineCallbacks
    def jsonrpc_peer_list(self, blob_hash, timeout=None):
        """
        Get peers for blob hash

        Usage:
            peer_list (<blob_hash> | --blob_hash=<blob_hash>) [<timeout> | --timeout=<timeout>]

        Options:
            --blob_hash=<blob_hash>  : (str) find available peers for this blob hash
            --timeout=<timeout>      : (int) peer search timeout in seconds

        Returns:
            (list) List of contact dictionaries {'host': <peer ip>, 'port': <peer port>, 'node_id': <peer node id>}
        """

        if not utils.is_valid_blobhash(blob_hash):
            raise Exception("invalid blob hash")

        finished_deferred = self.session.dht_node.getPeersForBlob(binascii.unhexlify(blob_hash), True)

        def _trigger_timeout():
            if not finished_deferred.called:
                log.debug("Peer search for %s timed out", blob_hash)
                finished_deferred.cancel()

        timeout = timeout or conf.settings['peer_search_timeout']
        self.session.dht_node.reactor_callLater(timeout, _trigger_timeout)

        peers = yield finished_deferred
        results = [
            {
                "host": host,
                "port": port,
                "node_id": node_id
            }
            for host, port, node_id in peers
        ]
        defer.returnValue(results)

    @defer.inlineCallbacks
    def jsonrpc_blob_announce(self, blob_hash=None, stream_hash=None, sd_hash=None):
        """
        Announce blobs to the DHT

        Usage:
            blob_announce [<blob_hash> | --blob_hash=<blob_hash>]
                          [<stream_hash> | --stream_hash=<stream_hash>] | [<sd_hash> | --sd_hash=<sd_hash>]

        Options:
            --blob_hash=<blob_hash>        : (str) announce a blob, specified by blob_hash
            --stream_hash=<stream_hash>    : (str) announce all blobs associated with
                                             stream_hash
            --sd_hash=<sd_hash>            : (str) announce all blobs associated with
                                             sd_hash and the sd_hash itself

        Returns:
            (bool) true if successful
        """

        blob_hashes = []
        if blob_hash:
            blob_hashes.append(blob_hash)
        elif stream_hash or sd_hash:
            if sd_hash and stream_hash:
                raise Exception("either the sd hash or the stream hash should be provided, not both")
            if sd_hash:
                stream_hash = yield self.storage.get_stream_hash_for_sd_hash(sd_hash)
            blobs = yield self.storage.get_blobs_for_stream(stream_hash, only_completed=True)
            blob_hashes.extend(blob.blob_hash for blob in blobs if blob.blob_hash is not None)
        else:
            raise Exception('single argument must be specified')
        yield self.storage.should_single_announce_blobs(blob_hashes, immediate=True)
        response = yield self._render_response(True)
        defer.returnValue(response)

    @defer.inlineCallbacks
    def jsonrpc_file_reflect(self, **kwargs):
        """
        Reflect all the blobs in a file matching the filter criteria

        Usage:
            file_reflect [--sd_hash=<sd_hash>] [--file_name=<file_name>]
                         [--stream_hash=<stream_hash>] [--rowid=<rowid>]
                         [--reflector=<reflector>]

        Options:
            --sd_hash=<sd_hash>          : (str) get file with matching sd hash
            --file_name=<file_name>      : (str) get file with matching file name in the
                                           downloads folder
            --stream_hash=<stream_hash>  : (str) get file with matching stream hash
            --rowid=<rowid>              : (int) get file with matching row id
            --reflector=<reflector>      : (str) reflector server, ip address or url
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

        results = yield reupload.reflect_file(lbry_file, reflector_server=reflector_server)
        defer.returnValue(results)

    @defer.inlineCallbacks
    def jsonrpc_blob_list(self, uri=None, stream_hash=None, sd_hash=None, needed=None,
                          finished=None, page_size=None, page=None):
        """
        Returns blob hashes. If not given filters, returns all blobs known by the blob manager

        Usage:
            blob_list [--needed] [--finished] [<uri> | --uri=<uri>]
                      [<stream_hash> | --stream_hash=<stream_hash>]
                      [<sd_hash> | --sd_hash=<sd_hash>]
                      [<page_size> | --page_size=<page_size>]
                      [<page> | --page=<page>]

        Options:
            --needed                     : (bool) only return needed blobs
            --finished                   : (bool) only return finished blobs
            --uri=<uri>                  : (str) filter blobs by stream in a uri
            --stream_hash=<stream_hash>  : (str) filter blobs by stream hash
            --sd_hash=<sd_hash>          : (str) filter blobs by sd hash
            --page_size=<page_size>      : (int) results page size
            --page=<page>                : (int) page of results to return

        Returns:
            (list) List of blob hashes
        """
        if uri or stream_hash or sd_hash:
            if uri:
                metadata = yield self._resolve_name(uri)
                sd_hash = utils.get_sd_hash(metadata)
                stream_hash = yield self.session.storage.get_stream_hash_for_sd_hash(sd_hash)
            elif stream_hash:
                sd_hash = yield self.session.storage.get_sd_blob_hash_for_stream(stream_hash)
            elif sd_hash:
                stream_hash = yield self.session.storage.get_stream_hash_for_sd_hash(sd_hash)
                sd_hash = yield self.session.storage.get_sd_blob_hash_for_stream(stream_hash)
            if stream_hash:
                crypt_blobs = yield self.session.storage.get_blobs_for_stream(stream_hash)
                blobs = [self.session.blob_manager.blobs[crypt_blob.blob_hash] for crypt_blob in crypt_blobs
                         if crypt_blob.blob_hash is not None]
            else:
                blobs = []
            # get_blobs_for_stream does not include the sd blob, so we'll add it manually
            if sd_hash in self.session.blob_manager.blobs:
                blobs = [self.session.blob_manager.blobs[sd_hash]] + blobs
        else:
            blobs = self.session.blob_manager.blobs.itervalues()

        if needed:
            blobs = [blob for blob in blobs if not blob.get_is_verified()]
        if finished:
            blobs = [blob for blob in blobs if blob.get_is_verified()]

        blob_hashes = [blob.blob_hash for blob in blobs if blob.blob_hash]
        page_size = page_size or len(blob_hashes)
        page = page or 0
        start_index = page * page_size
        stop_index = start_index + page_size
        blob_hashes_for_return = blob_hashes[start_index:stop_index]
        response = yield self._render_response(blob_hashes_for_return)
        defer.returnValue(response)

    def jsonrpc_blob_reflect(self, blob_hashes, reflector_server=None):
        """
        Reflects specified blobs

        Usage:
            blob_reflect (<blob_hashes>...) [--reflector_server=<reflector_server>]

        Options:
            --reflector_server=<reflector_server>          : (str) reflector address

        Returns:
            (list) reflected blob hashes
        """

        d = reupload.reflect_blob_hashes(blob_hashes, self.session.blob_manager, reflector_server)
        d.addCallback(lambda r: self._render_response(r))
        return d

    def jsonrpc_blob_reflect_all(self):
        """
        Reflects all saved blobs

        Usage:
            blob_reflect_all

        Options:
            None

        Returns:
            (bool) true if successful
        """

        d = self.session.blob_manager.get_all_verified_blobs()
        d.addCallback(reupload.reflect_blob_hashes, self.session.blob_manager)
        d.addCallback(lambda r: self._render_response(r))
        return d

    @defer.inlineCallbacks
    def jsonrpc_peer_ping(self, node_id):
        """
        Find and ping a peer by node id

        Usage:
            peer_ping (<node_id> | --node_id=<node_id>)

        Options:
            None

        Returns:
            (str) pong, or {'error': <error message>} if an error is encountered
        """

        contact = None
        try:
            contact = yield self.session.dht_node.findContact(node_id.decode('hex'))
        except TimeoutError:
            result = {'error': 'timeout finding peer'}
            defer.returnValue(result)
        if not contact:
            defer.returnValue({'error': 'peer not found'})
        try:
            result = yield contact.ping()
        except TimeoutError:
            result = {'error': 'ping timeout'}
        defer.returnValue(result)

    def jsonrpc_routing_table_get(self):
        """
        Get DHT routing information

        Usage:
            routing_table_get

        Options:
            None

        Returns:
            (dict) dictionary containing routing and contact information
            {
                "buckets": {
                    <bucket index>: [
                        {
                            "address": (str) peer address,
                            "node_id": (str) peer node id,
                            "blobs": (list) blob hashes announced by peer
                        }
                    ]
                },
                "contacts": (list) contact node ids,
                "blob_hashes": (list) all of the blob hashes stored by peers in the list of buckets,
                "node_id": (str) the local dht node id
            }
        """

        result = {}
        data_store = deepcopy(self.session.dht_node._dataStore._dict)
        datastore_len = len(data_store)
        hosts = {}

        if datastore_len:
            for k, v in data_store.iteritems():
                for value, lastPublished, originallyPublished, originalPublisherID in v:
                    try:
                        contact = self.session.dht_node._routingTable.getContact(
                            originalPublisherID)
                    except ValueError:
                        continue
                    if contact in hosts:
                        blobs = hosts[contact]
                    else:
                        blobs = []
                    blobs.append(k.encode('hex'))
                    hosts[contact] = blobs

        contact_set = []
        blob_hashes = []
        result['buckets'] = {}

        for i in range(len(self.session.dht_node._routingTable._buckets)):
            for contact in self.session.dht_node._routingTable._buckets[i]._contacts:
                contacts = result['buckets'].get(i, [])
                if contact in hosts:
                    blobs = hosts[contact]
                    del hosts[contact]
                else:
                    blobs = []
                host = {
                    "address": contact.address,
                    "node_id": contact.id.encode("hex"),
                    "blobs": blobs,
                }
                for blob_hash in blobs:
                    if blob_hash not in blob_hashes:
                        blob_hashes.append(blob_hash)
                contacts.append(host)
                result['buckets'][i] = contacts
                if contact.id.encode('hex') not in contact_set:
                    contact_set.append(contact.id.encode("hex"))

        result['contacts'] = contact_set
        result['blob_hashes'] = blob_hashes
        result['node_id'] = self.session.dht_node.node_id.encode('hex')
        return self._render_response(result)

    def jsonrpc_blob_availability(self, blob_hash, search_timeout=None, blob_timeout=None):
        """
        Get blob availability

        Usage:
            blob_availability (<blob_hash>) [<search_timeout> | --search_timeout=<search_timeout>]
                              [<blob_timeout> | --blob_timeout=<blob_timeout>]

        Options:
            --blob_hash=<blob_hash>           : (str) check availability for this blob hash
            --search_timeout=<search_timeout> : (int) how long to search for peers for the blob
                                                in the dht
            --blob_timeout=<blob_timeout>     : (int) how long to try downloading from a peer

        Returns:
            (dict) {
                "is_available": <bool, true if blob is available from a peer from peer list>
                "reachable_peers": ["<ip>:<port>"],
                "unreachable_peers": ["<ip>:<port>"]
            }
        """

        return self._blob_availability(blob_hash, search_timeout, blob_timeout)

    @AuthJSONRPCServer.deprecated("stream_availability")
    def jsonrpc_get_availability(self, uri, sd_timeout=None, peer_timeout=None):
        """
        Get stream availability for lbry uri

        Usage:
            get_availability (<uri> | --uri=<uri>) [<sd_timeout> | --sd_timeout=<sd_timeout>]
                             [<peer_timeout> | --peer_timeout=<peer_timeout>]

        Options:
            --uri=<uri>                    : (str) check availability for this uri
            --sd_timeout=<sd_timeout>      : (int) sd blob download timeout
            --peer_timeout=<peer_timeout>  : (int) how long to look for peers

        Returns:
            (float) Peers per blob / total blobs
        """

        return self.jsonrpc_stream_availability(uri, peer_timeout, sd_timeout)

    @defer.inlineCallbacks
    def jsonrpc_stream_availability(self, uri, search_timeout=None, blob_timeout=None):
        """
        Get stream availability for lbry uri

        Usage:
            stream_availability (<uri> | --uri=<uri>)
                                [<search_timeout> | --search_timeout=<search_timeout>]
                                [<blob_timeout> | --blob_timeout=<blob_timeout>]

        Options:
            --uri=<uri>                       : (str) check availability for this uri
            --search_timeout=<search_timeout> : (int) how long to search for peers for the blob
                                                in the dht
            --blob_timeout=<blob_timeout>   : (int) how long to try downloading from a peer

        Returns:
            (dict) {
                'is_available': <bool>,
                'did_decode': <bool>,
                'did_resolve': <bool>,
                'is_stream': <bool>,
                'num_blobs_in_stream': <int>,
                'sd_hash': <str>,
                'sd_blob_availability': <dict> see `blob_availability`,
                'head_blob_hash': <str>,
                'head_blob_availability': <dict> see `blob_availability`,
                'use_upnp': <bool>,
                'upnp_redirect_is_set': <bool>,
                'error': <None> | <str> error message
            }
        """

        search_timeout = search_timeout or conf.settings['peer_search_timeout']
        blob_timeout = blob_timeout or conf.settings['sd_download_timeout']

        response = {
            'is_available': False,
            'did_decode': False,
            'did_resolve': False,
            'is_stream': False,
            'num_blobs_in_stream': None,
            'sd_hash': None,
            'sd_blob_availability': {},
            'head_blob_hash': None,
            'head_blob_availability': {},
            'use_upnp': conf.settings['use_upnp'],
            'upnp_redirect_is_set': len(self.session.upnp_redirects) > 0,
            'error': None
        }

        try:
            resolved_result = yield self.session.wallet.resolve(uri)
            response['did_resolve'] = True
        except UnknownNameError:
            response['error'] = "Failed to resolve name"
            defer.returnValue(response)
        except URIParseError:
            response['error'] = "Invalid URI"
            defer.returnValue(response)

        try:
            claim_obj = smart_decode(resolved_result[uri]['claim']['hex'])
            response['did_decode'] = True
        except DecodeError:
            response['error'] = "Failed to decode claim value"
            defer.returnValue(response)

        response['is_stream'] = claim_obj.is_stream
        if not claim_obj.is_stream:
            response['error'] = "Claim for \"%s\" does not contain a stream" % uri
            defer.returnValue(response)

        sd_hash = claim_obj.source_hash
        response['sd_hash'] = sd_hash
        head_blob_hash = None
        downloader = self._get_single_peer_downloader()
        have_sd_blob = sd_hash in self.session.blob_manager.blobs
        try:
            sd_blob = yield self.jsonrpc_blob_get(sd_hash, timeout=blob_timeout,
                                                  encoding="json")
            if not have_sd_blob:
                yield self.jsonrpc_blob_delete(sd_hash)
            if sd_blob and 'blobs' in sd_blob:
                response['num_blobs_in_stream'] = len(sd_blob['blobs']) - 1
                head_blob_hash = sd_blob['blobs'][0]['blob_hash']
                head_blob_availability = yield self._blob_availability(head_blob_hash,
                                                                       search_timeout,
                                                                       blob_timeout,
                                                                       downloader)
                response['head_blob_availability'] = head_blob_availability
        except Exception as err:
            response['error'] = err
        response['head_blob_hash'] = head_blob_hash
        response['sd_blob_availability'] = yield self._blob_availability(sd_hash,
                                                                         search_timeout,
                                                                         blob_timeout,
                                                                         downloader)
        response['is_available'] = response['sd_blob_availability'].get('is_available') and \
                                   response['head_blob_availability'].get('is_available')
        defer.returnValue(response)

    @defer.inlineCallbacks
    def jsonrpc_cli_test_command(self, pos_arg, pos_args=[], pos_arg2=None, pos_arg3=None,
                                 a_arg=False, b_arg=False):
        """
        This command is only for testing the CLI argument parsing
        Usage:
            cli_test_command [--a_arg] [--b_arg] (<pos_arg> | --pos_arg=<pos_arg>)
                             [<pos_args>...] [--pos_arg2=<pos_arg2>]
                             [--pos_arg3=<pos_arg3>]

        Options:
            --a_arg                            : a arg
            --b_arg                            : b arg
            --pos_arg=<pos_arg>                : pos arg
            --pos_args=<pos_args>              : pos args
            --pos_arg2=<pos_arg2>              : pos arg 2
            --pos_arg3=<pos_arg3>              : pos arg 3
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
