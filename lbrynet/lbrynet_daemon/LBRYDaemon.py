import locale
import os
import sys
import simplejson as json
import binascii
import subprocess
import logging
import logging.handlers
import requests
import base64
import base58
import platform
import json

from twisted.web import server, resource, static
from twisted.internet import defer, threads, error, reactor
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
from lbrynet.lbrynet_console.ControlHandlers import get_time_behind_blockchain
from lbrynet.core.Error import UnknownNameError
from lbrynet.lbryfile.StreamDescriptor import LBRYFileStreamType
from lbrynet.lbryfile.client.LBRYFileDownloader import LBRYFileSaverFactory, LBRYFileOpenerFactory
from lbrynet.lbryfile.client.LBRYFileOptions import add_lbry_file_to_sd_identifier
from lbrynet.lbrynet_daemon.LBRYDownloader import GetStream, FetcherDaemon
from lbrynet.lbrynet_daemon.LBRYPublisher import Publisher
from lbrynet.core.utils import generate_id
from lbrynet.lbrynet_console.LBRYSettings import LBRYSettings
from lbrynet.conf import MIN_BLOB_DATA_PAYMENT_RATE, DEFAULT_MAX_SEARCH_RESULTS, KNOWN_DHT_NODES, DEFAULT_MAX_KEY_FEE
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

log = logging.getLogger(__name__)
handler = logging.handlers.RotatingFileHandler(LOG_FILENAME, maxBytes=262144, backupCount=5)
log.addHandler(handler)

STARTUP_STAGES = [
                    ('initializing', 'Initializing...'),
                    ('loading_db', 'Loading databases...'),
                    ('loading_wallet', 'Catching up with blockchain... %s'),
                    ('loading_file_manager', 'Setting up file manager'),
                    ('loading_server', 'Starting lbrynet'),
                    ('started', 'Started lbrynet')
                  ]


BAD_REQUEST = 400
NOT_FOUND = 404
OK_CODE = 200
# TODO add login credentials in a conf file
# TODO alert if your copy of a lbry file is out of date with the name record


class Bunch:
    def __init__(self, params):
        self.__dict__.update(params)


class LBRYDaemon(jsonrpc.JSONRPC):
    """
    LBRYnet daemon, a jsonrpc interface to lbry functions
    """

    isLeaf = True

    def __init__(self, ui_version_info, wallet_type="lbryum"):
        jsonrpc.JSONRPC.__init__(self)
        reactor.addSystemEventTrigger('before', 'shutdown', self._shutdown)

        self.startup_status = STARTUP_STAGES[0]
        self.startup_message = None
        self.announced_startup = False
        self.query_handlers = {}
        self.ui_version = ui_version_info.replace('\n', '')
        self.wallet_type = wallet_type
        self.session_settings = None
        self.first_run = None
        self.log_file = LOG_FILENAME
        self.fetcher = None
        self.current_db_revision = 1
        self.run_server = True
        self.session = None
        self.known_dht_nodes = KNOWN_DHT_NODES

        if os.name == "nt":
            from lbrynet.winhelpers.knownpaths import get_path, FOLDERID, UserHandle
            self.download_directory = get_path(FOLDERID.Downloads, UserHandle.current)
            self.db_dir = os.path.join(get_path(FOLDERID.RoamingAppData, UserHandle.current), "lbrynet")
            self.lbrycrdd_path = "lbrycrdd.exe"
            if wallet_type == "lbrycrd":
                self.wallet_dir = os.path.join(get_path(FOLDERID.RoamingAppData, UserHandle.current), "lbrycrd")
            else:
                self.wallet_dir = os.path.join(get_path(FOLDERID.RoamingAppData, UserHandle.current), "lbryum")
        elif sys.platform == "darwin":
            self.download_directory = os.path.join(os.path.expanduser("~"), 'Downloads')
            self.db_dir = user_data_dir("LBRY")
            self.lbrycrdd_path = "./lbrycrdd"
            if wallet_type == "lbrycrd":
                self.wallet_dir = user_data_dir("lbrycrd")
            else:
                self.wallet_dir = user_data_dir("LBRY")
        else:
            self.download_directory = os.getcwd()
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

        self.sd_identifier = StreamDescriptorIdentifier()
        self.stream_info_manager = TempLBRYFileMetadataManager()
        self.settings = LBRYSettings(self.db_dir)
        self.blob_request_payment_rate_manager = None
        self.lbry_file_metadata_manager = None
        self.lbry_file_manager = None

        #defaults for settings otherwise loaded from daemon_settings.json
        self.default_settings = {
            'run_on_startup': False,
            'data_rate': MIN_BLOB_DATA_PAYMENT_RATE,
            'max_key_fee': DEFAULT_MAX_KEY_FEE,
            'default_download_directory': self.download_directory,
            'max_upload': 0.0,
            'max_download': 0.0,
            'upload_log': True,
            'search_timeout': 3.0,
            'max_search_results': DEFAULT_MAX_SEARCH_RESULTS,
            'wallet_type': wallet_type,
            'delete_blobs_on_remove': True,
            'peer_port': 3333,
            'dht_node_port': 4444,
            'use_upnp': True,
            'start_lbrycrdd': True,
        }
        if os.path.isfile(self.daemon_conf):
            #load given settings, set missing settings to defaults
            temp_settings = self.default_settings
            f = open(self.daemon_conf, "r")
            s = json.loads(f.read())
            f.close()
            for k in temp_settings.keys():
                if k in s.keys():
                    if type(temp_settings[k]) == type(s[k]):
                        temp_settings[k] = s[k]
                        self.__dict__[k] = s[k]
            f = open(self.daemon_conf, "w")
            f.write(json.dumps(temp_settings))
            f.close()
        else:
            log.info("Writing default settings: " + json.dumps(self.default_settings) + " --> " + str(self.daemon_conf))
            f = open(self.daemon_conf, "w")
            f.write(json.dumps(self.default_settings))
            f.close()
            for k in self.default_settings.keys():
                self.__dict__[k] = self.default_settings[k]

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
            if functionPath not in ['is_running', 'is_first_run',
                                    'get_time_behind_blockchain', 'stop',
                                    'daemon_status', 'get_start_notice',
                                    'version', 'check_for_new_version']:
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
            def _get_lbry_files_json():
                r = []
                for f in self.lbry_file_manager.lbry_files:
                    if f.key:
                        t = {'completed': f.completed, 'file_name': f.file_name, 'key': binascii.b2a_hex(f.key),
                             'points_paid': f.points_paid, 'stopped': f.stopped, 'stream_hash': f.stream_hash,
                             'stream_name': f.stream_name, 'suggested_file_name': f.suggested_file_name,
                             'upload_allowed': f.upload_allowed}

                    else:
                        t = {'completed': f.completed, 'file_name': f.file_name, 'key': None,
                             'points_paid': f.points_paid,
                             'stopped': f.stopped, 'stream_hash': f.stream_hash, 'stream_name': f.stream_name,
                             'suggested_file_name': f.suggested_file_name, 'upload_allowed': f.upload_allowed}

                    r.append(t)
                return json.dumps(r)

            log.info("LBRY Files: " + _get_lbry_files_json())
            log.info("Starting balance: " + str(self.session.wallet.wallet_balance))

            return defer.succeed(None)

        def _announce_startup():
            self.announced_startup = True
            self.startup_status = STARTUP_STAGES[5]
            log.info("[" + str(datetime.now()) + "] Started lbrynet-daemon")
            return defer.succeed(None)

        log.info("[" + str(datetime.now()) + "] Starting lbrynet-daemon")

        d = defer.Deferred()
        d.addCallback(lambda _: self._initial_setup())
        d.addCallback(self._set_daemon_settings)
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
        d.addCallback(lambda _: self._setup_fetcher())
        d.addCallback(lambda _: _log_starting_vals())
        d.addCallback(lambda _: _announce_startup())
        d.callback(None)

        return defer.succeed(None)

    def _initial_setup(self):
        def _log_platform():
            msg = {
                "processor": platform.processor(),
                "python version: ": platform.python_version(),
                "lbrynet version: ": lbrynet_version,
                "lbryum version: ": lbryum_version,
                "ui_version": self.ui_version,
                # 'ip': json.load(urlopen('http://jsonip.com'))['ip'],
            }
            if sys.platform == "darwin":
                msg['osx version'] = platform.mac_ver()[0] + " " + platform.mac_ver()[2]
            else:
                msg['platform'] = platform.platform()

            log.info("Platform: " + json.dumps(msg))
            return defer.succeed(None)

        def _load_daemon_conf():
            if os.path.isfile(self.daemon_conf):
                return json.loads(open(self.daemon_conf, "r").read())
            else:
                log.info("Writing default settings : " + json.dumps(self.default_settings) + " --> " + str(self.daemon_conf))
                f = open(self.daemon_conf, "w")
                f.write(json.dumps(self.default_settings))
                f.close()
                return self.default_settings

        d = _log_platform()
        d.addCallback(lambda _: _load_daemon_conf())

        return d

    def _set_daemon_settings(self, settings):
        self.session_settings = settings
        return defer.succeed(None)

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

    def _upload_log(self):
        if self.session_settings['upload_log']:
            LOG_URL = "https://lbry.io/log-upload"
            f = open(self.log_file, "r")
            t = datetime.now()
            log_name = base58.b58encode(self.lbryid)[:20] + "-" + str(t.month) + "-" + str(t.day) + "-" + str(t.year) + "-" + str(t.hour) + "-" + str(t.minute)
            params = {'name': log_name, 'log': f.read()}
            f.close()
            requests.post(LOG_URL, params)

        return defer.succeed(None)

    def _shutdown(self):
        log.info("Closing lbrynet session")
        d = self._upload_log()
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
            elif k == 'default_download_directory':
                if type(settings['default_download_directory']) is unicode:
                    if os.path.isdir(settings['default_download_directory']):
                        self.session_settings['default_download_directory'] = settings['default_download_directory']
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

        f = open(self.daemon_conf, "w")
        f.write(json.dumps(self.session_settings))
        f.close()

        return defer.succeed(True)

    def _setup_fetcher(self):
        self.fetcher = FetcherDaemon(self.session, self.lbry_file_manager, self.lbry_file_metadata_manager,
                                     self.session.wallet, self.sd_identifier, self.autofetcher_conf)
        return defer.succeed(None)

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
                                                     delete_data=True)
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
        dl.addCallback(lambda _: self._check_first_run())
        dl.addCallback(self._show_first_run_result)
        return dl

    def _check_first_run(self):
        def _set_first_run_false():
            log.info("Not first run")
            self.first_run = False
            return 0.0

        d = self.session.wallet.is_first_run()

        d.addCallback(lambda is_first_run: self._do_first_run() if is_first_run else _set_first_run_false())
        return d

    def _do_first_run(self):
        self.first_run = True
        d = self.session.wallet.get_new_address()

        def send_request(url, data):
            log.info("Requesting first run credits")
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

    def _show_first_run_result(self, credits_received):
        if credits_received != 0.0:
            points_string = locale.format_string("%.2f LBC", (round(credits_received, 2),), grouping=True)
            self.startup_message = "Thank you for testing the alpha version of LBRY! You have been given %s for free because we love you. Please give them a few minutes to show up while you catch up with our blockchain." % points_string
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
                                                  self.session.wallet, self.session_settings['default_download_directory'])
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

    def _download_name(self, name, timeout=DEFAULT_TIMEOUT, download_directory=None):
        if not download_directory:
            download_directory = self.session_settings['default_download_directory']
        elif not os.path.isdir(download_directory):
            download_directory = self.session_settings['default_download_directory']

        def _disp_file(f):
            file_path = os.path.join(self.session_settings['default_download_directory'], f.file_name)
            log.info("[" + str(datetime.now()) + "] Already downloaded: " + str(f.stream_hash) + " --> " + file_path)
            return defer.succeed(f)

        def _get_stream(name):
            def _disp(stream):
                stream_hash = stream['stream_hash']
                if isinstance(stream_hash, dict):
                    stream_hash = stream_hash['sd_hash']

                log.info("[" + str(datetime.now()) + "] Start stream: " + stream_hash)
                return stream

            d = self.session.wallet.get_stream_info_for_name(name)
            stream = GetStream(self.sd_identifier, self.session, self.session.wallet, self.lbry_file_manager,
                               max_key_fee=self.max_key_fee, data_rate=self.data_rate, timeout=timeout,
                               download_directory=download_directory)
            d.addCallback(_disp)
            d.addCallback(lambda stream_info: stream.start(stream_info))
            d.addCallback(lambda _: self._path_from_name(name))

            return d

        d = self._check_history(name)
        d.addCallback(lambda lbry_file: _get_stream(name) if not lbry_file else _disp_file(lbry_file))
        d.addCallback(lambda _: self._path_from_name(name))
        d.addErrback(lambda err: defer.fail(NOT_FOUND))

        return d

    def _resolve_name(self, name):
        d = defer.Deferred()
        d.addCallback(lambda _: self.session.wallet.get_stream_info_for_name(name))
        d.addErrback(lambda _: defer.fail(UnknownNameError))

        return d

    def _resolve_name_wc(self, name):
        d = defer.Deferred()
        d.addCallback(lambda _: self.session.wallet.get_stream_info_for_name(name))
        d.addErrback(lambda _: defer.fail(UnknownNameError))
        d.callback(None)

        return d

    def _check_history(self, name):
        def _get_lbry_file(path):
            f = open(path, 'r')
            l = json.loads(f.read())
            f.close()

            file_name = l['stream_name'].decode('hex')

            for lbry_file in self.lbry_file_manager.lbry_files:
                if lbry_file.stream_name == file_name:
                    if sys.platform == "darwin":
                        if os.path.isfile(os.path.join(self.session_settings['default_download_directory'], lbry_file.stream_name)):
                            return lbry_file
                        else:
                            return False
                    else:
                        return lbry_file
            else:
                return False

        def _check(info):
            stream_hash = info['stream_hash']
            if isinstance(stream_hash, dict):
                stream_hash = stream_hash['sd_hash']

            path = os.path.join(self.blobfile_dir, stream_hash)
            if os.path.isfile(path):
                log.info("[" + str(datetime.now()) + "] Search for lbry_file, returning: " + stream_hash)
                return defer.succeed(_get_lbry_file(path))
            else:
                log.info("[" + str(datetime.now()) + "] Search for lbry_file didn't return anything")
                return defer.succeed(False)

        d = self._resolve_name(name)
        d.addCallback(_check)
        d.callback(None)

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
            d.addCallback(lambda _: os.remove(os.path.join(self.session_settings['default_download_directory'], lbry_file.file_name)) if
                          os.path.isfile(os.path.join(self.session_settings['default_download_directory'], lbry_file.file_name)) else defer.succeed(None))
            return d

        d.addCallback(lambda _: finish_deletion(lbry_file))
        return d

    def _path_from_name(self, name):
        d = self._check_history(name)
        d.addCallback(lambda lbry_file: {'stream_hash': lbry_file.stream_hash,
                                         'path': os.path.join(self.session_settings['default_download_directory'], lbry_file.file_name)}
                                        if lbry_file else defer.fail(UnknownNameError))
        return d

    def _path_from_lbry_file(self, lbry_file):
        if lbry_file:
            r = {'stream_hash': lbry_file.stream_hash,
                 'path': os.path.join(self.session_settings['default_download_directory'], lbry_file.file_name)}
            return defer.succeed(r)
        else:
            return defer.fail(UnknownNameError)

    def _get_est_cost(self, name):
        def _check_est(d, name):
            if type(d.result) is float:
                log.info("[" + str(datetime.now()) + "] Cost est for lbry://" + name + ": " + str(d.result) + "LBC")
            else:
                log.info("[" + str(datetime.now()) + "] Timeout estimating cost for lbry://" + name + ", using key fee")
                d.cancel()
            return defer.succeed(None)

        def _add_key_fee(data_cost):
            d = self.session.wallet.get_stream_info_for_name(name)
            d.addCallback(lambda info: data_cost + info['key_fee'] if 'key_fee' in info.keys() else data_cost)
            return d

        d = self.session.wallet.get_stream_info_for_name(name)
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

    def _render_response(self, result, code):
        return defer.succeed({'result': result, 'code': code})

    def jsonrpc_is_running(self):
        """
        Returns true if daemon completed startup, otherwise returns false
        """

        log.info("[" + str(datetime.now()) + "] is_running: " + str(self.announced_startup))

        if self.announced_startup:
            return self._render_response(True, OK_CODE)
        else:
            return self._render_response(False, OK_CODE)

    def jsonrpc_daemon_status(self):
        """
        Returns {'status_message': startup status message, 'status_code': status_code}
        """

        r = {'status_code': self.startup_status[0], 'status_message': self.startup_status[1]}
        try:
            if self.startup_status[0] == 'loading_wallet':
                r['status_message'] = r['status_message'] % (str(self.session.wallet.blocks_behind_alert) + " blocks behind")
                r['progress'] = self.session.wallet.catchup_progress
        except:
            pass
        log.info("[" + str(datetime.now()) + "] daemon status: " + str(r))
        return self._render_response(r, OK_CODE)

    def jsonrpc_is_first_run(self):
        """
        Get True/False if can be determined, if wallet still is being set up returns None
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
        Get any special message to be displayed at startup, such as a first run notice
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
        """

        msg = {
            "lbrynet version: ": lbrynet_version,
            "lbryum version: ": lbryum_version,
            "ui_version": self.ui_version,
        }

        log.info("[" + str(datetime.now()) + "] Get version info: " + json.dumps(msg))
        return self._render_response(msg, OK_CODE)

    def jsonrpc_get_settings(self):
        """
        Get LBRY payment settings

        @return {'data_rate': float, 'max_key_fee': float, 'max_upload': float (0.0 for unlimited),
                 'default_download_directory': string, 'run_on_startup': bool,
                 'max_download': float (0.0 for unlimited)}
        """

        log.info("[" + str(datetime.now()) + "] Get daemon settings")
        return self._render_response(self.session_settings, OK_CODE)

    def jsonrpc_set_settings(self, p):
        """
        Set LBRY payment settings

        @param settings: {'data_rate': float, 'max_key_fee': float, 'max_upload': float (0.0 for unlimited),
                          'default_download_directory': string, 'run_on_startup': bool,
                          'max_download': float (0.0 for unlimited)}
        """

        def _log_settings_change(params):
            log.info("[" + str(datetime.now()) + "] Set daemon settings to " + str(params))

        d = self._update_settings(p)
        d.addCallback(lambda _: _log_settings_change(p))
        d.addCallback(lambda _: self._render_response(self.session_settings, OK_CODE))

        return d

    def jsonrpc_start_fetcher(self):
        """
        Start automatically downloading new name claims as they happen

        @return: confirmation message
        """

        self.fetcher.start()
        log.info('[' + str(datetime.now()) + '] Start autofetcher')
        # self._log_to_slack('[' + str(datetime.now()) + '] Start autofetcher')
        return self._render_response("Started autofetching claims", OK_CODE)

    def jsonrpc_stop_fetcher(self):
        """
        Stop automatically downloading new name claims as they happen

        @return: confirmation message
        """

        self.fetcher.stop()
        log.info('[' + str(datetime.now()) + '] Stop autofetcher')
        return self._render_response("Stopped autofetching claims", OK_CODE)

    def jsonrpc_fetcher_status(self):
        """
        Get fetcher status

        @return: True/False
        """

        log.info("[" + str(datetime.now()) + "] Get fetcher status")
        return self._render_response(self.fetcher.check_if_running(), OK_CODE)

    def jsonrpc_get_balance(self):
        """
        Get LBC balance

        @return: balance
        """

        log.info("[" + str(datetime.now()) + "] Get balance")
        return self._render_response(float(self.session.wallet.wallet_balance), OK_CODE)

    def jsonrpc_stop(self):
        """
        Stop lbrynet-daemon

        @return: shutdown message
        """

        def _disp_shutdown():
            log.info("Shutting down lbrynet daemon")

        d = self._shutdown()
        d.addCallback(lambda _: _disp_shutdown())
        d.addCallback(lambda _: reactor.callLater(1.0, reactor.stop))

        return self._render_response("Shutting down", OK_CODE)

    def jsonrpc_get_lbry_files(self):
        """
        Get LBRY files

        @return: List of managed LBRY files
        """

        r = []
        for f in self.lbry_file_manager.lbry_files:
            if f.key:
                t = {'completed': f.completed, 'file_name': f.file_name, 'key': binascii.b2a_hex(f.key),
                     'points_paid': f.points_paid, 'stopped': f.stopped, 'stream_hash': f.stream_hash,
                     'stream_name': f.stream_name, 'suggested_file_name': f.suggested_file_name,
                     'upload_allowed': f.upload_allowed}

            else:
                t = {'completed': f.completed, 'file_name': f.file_name, 'key': None, 'points_paid': f.points_paid,
                     'stopped': f.stopped, 'stream_hash': f.stream_hash, 'stream_name': f.stream_name,
                     'suggested_file_name': f.suggested_file_name, 'upload_allowed': f.upload_allowed}

            r.append(json.dumps(t))

        log.info("[" + str(datetime.now()) + "] Get LBRY files")
        return self._render_response(r, OK_CODE)

    def jsonrpc_resolve_name(self, p):
        """
        Resolve stream info from a LBRY uri

        @param: {'name': name to look up}
        @return: info for name claim
        """
        params = Bunch(p)

        def _disp(info):
            stream_hash = info['stream_hash']
            if isinstance(stream_hash, dict):
                stream_hash = stream_hash['sd_hash']

            log.info("[" + str(datetime.now()) + "] Resolved info: " + stream_hash)

            return self._render_response(info, OK_CODE)

        d = self._resolve_name(params.name)
        d.addCallbacks(_disp, lambda _: server.failure)
        d.callback(None)
        return d

    def jsonrpc_get(self, p):
        """
        Download stream from a LBRY uri

        @param: name, optional: download_directory
        @return: {'stream_hash': hex string, 'path': path of download}
        """

        if 'timeout' not in p.keys():
            timeout = DEFAULT_TIMEOUT
        else:
            timeout = p['timeout']

        if 'download_directory' not in p.keys():
            download_directory = self.session_settings['default_download_directory']
        else:
            download_directory = p['download_directory']

        if 'name' in p.keys():
            name = p['name']
            d = self._download_name(name=name, timeout=timeout, download_directory=download_directory)
            d.addCallbacks(lambda message: self._render_response(message, OK_CODE),
                           lambda err: self._render_response('error', NOT_FOUND))
        else:
            d = self._render_response('error', BAD_REQUEST)

        return d

    # def jsonrpc_stop_lbry_file(self, p):
    #     params = Bunch(p)
    #
    #     try:
    #         lbry_file = [f for f in self.lbry_file_manager.lbry_files if f.stream_hash == params.stream_hash][0]
    #     except IndexError:
    #         return defer.fail(UnknownNameError)
    #
    #     if not lbry_file.stopped:
    #         d = self.lbry_file_manager.toggle_lbry_file_running(lbry_file)
    #         d.addCallback(lambda _: self._render_response("Stream has been stopped", OK_CODE))
    #         d.addErrback(lambda err: self._render_response(err.getTraceback(), ))
    #         return d
    #     else:
    #         return json.dumps({'result': 'Stream was already stopped'})
    #
    # def jsonrpc_start_lbry_file(self, p):
    #     params = Bunch(p)
    #
    #     try:
    #         lbry_file = [f for f in self.lbry_file_manager.lbry_files if f.stream_hash == params.stream_hash][0]
    #     except IndexError:
    #         return defer.fail(UnknownNameError)
    #
    #     if lbry_file.stopped:
    #         d = self.lbry_file_manager.toggle_lbry_file_running(lbry_file)
    #         d.callback(None)
    #         return json.dumps({'result': 'Stream started'})
    #     else:
    #         return json.dumps({'result': 'Stream was already running'})

    def jsonrpc_search_nametrie(self, p):
        """
        Search the nametrie for claims beginning with search

        @param {'search': search string}
        @return: List of search results
        """

        params = Bunch(p)

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
                d2 = self._resolve_name_wc(claim['name'])
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
                consolidated_results.append(t)
                # log.info(str(t))
            return consolidated_results

        log.info('[' + str(datetime.now()) + '] Search nametrie: ' + params.search)

        d = self.session.wallet.get_nametrie()
        d.addCallback(lambda trie: [claim for claim in trie if claim['name'].startswith(params.search) and 'txid' in claim])
        d.addCallback(lambda claims: claims[:self.max_search_results])
        d.addCallback(resolve_claims)
        d.addCallback(_clean)
        d.addCallback(_disp)
        d.addCallback(lambda results: self._render_response(results, OK_CODE))

        return d

    def jsonrpc_delete_lbry_file(self, p):
        """
        Delete a lbry file

        @param {'file_name': string}
        @return: confirmation message
        """

        def _disp(file_name):
            log.info("[" + str(datetime.now()) + "] Deleted: " + file_name)
            return self._render_response("Deleted: " + file_name, OK_CODE)

        if "file_name" in p.keys():
            lbry_files = [self._delete_lbry_file(f) for f in self.lbry_file_manager.lbry_files
                                                    if p['file_name'] == f.file_name]
            d = defer.DeferredList(lbry_files)
            d.addCallback(lambda _: _disp(p['file_name']))
            return d

    def jsonrpc_publish(self, p):
        """
        Make a new name claim

        @param:
        @return:
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
        Abandon and reclaim credits from a name claim

        @param: {'txid': string}
        @return: txid
        """
        params = Bunch(p)

        def _disp(x):
            log.info("[" + str(datetime.now()) + "] Abandoned name claim tx " + str(x))
            return self._render_response(x, OK_CODE)

        d = defer.Deferred()
        d.addCallback(lambda _: self.session.wallet.abandon_name(params.txid))
        d.addCallback(_disp)
        d.callback(None)

        return d

    def jsonrpc_get_name_claims(self):
        """
        Get name claims

        @return: list of name claims
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

    def jsonrpc_get_time_behind_blockchain(self):
        """
        Get time behind blockchain

        @return: time behind blockchain
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

        @return: new wallet address
        """
        def _disp(address):
            log.info("[" + str(datetime.now()) + "] Got new wallet address: " + address)
            return defer.succeed(address)

        d = self.session.wallet.get_new_address()
        d.addCallback(_disp)
        d.addCallback(lambda address: self._render_response(address, OK_CODE))
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

    def jsonrpc_toggle_fetcher_verbose(self):
        if self.fetcher.verbose:
            self.fetcher.verbose = False
        else:
            self.fetcher.verbose = True

        return self._render_response(self.fetcher.verbose, OK_CODE)

    def jsonrpc_check_for_new_version(self):
        def _get_lbryum_version():
            r = urlopen("https://rawgit.com/lbryio/lbryum/master/lib/version.py").read().split('\n')
            version = next(line.split("=")[1].split("#")[0].replace(" ", "")
                           for line in r if "ELECTRUM_VERSION" in line)
            version = version.replace("'", "")
            return version

        def _get_lbrynet_version():
            r = urlopen("https://rawgit.com/lbryio/lbry/master/lbrynet/__init__.py").read().split('\n')
            vs = next(i for i in r if 'version =' in i).split("=")[1].replace(" ", "")
            vt = tuple(int(x) for x in vs[1:-1].split(','))
            return ".".join([str(x) for x in vt])

        if (lbrynet_version >= _get_lbrynet_version()) and (lbryum_version >= _get_lbryum_version()):
            return self._render_response(False, OK_CODE)
        else:
            return self._render_response(True, OK_CODE)

    def jsonrpc___dir__(self):
        return ['is_running', 'get_settings', 'set_settings', 'start_fetcher', 'stop_fetcher', 'fetcher_status',
                'get_balance', 'stop', 'get_lbry_files', 'resolve_name', 'get', 'search_nametrie',
                'delete_lbry_file', 'check', 'publish', 'abandon_name', 'get_name_claims',
                'get_time_behind_blockchain', 'get_new_address', 'toggle_fetcher_verbose', 'check_for_new_version']


class LBRYDaemonCommandHandler(object):
    def __init__(self, command):
        self._api = jsonrpc.Proxy(API_CONNECTION_STRING)
        self.command = command

    def run(self, params=None):
        if params:
            d = self._api.callRemote(self.command, params)
        else:
            d = self._api.callRemote(self.command)
        return d


class LBRYindex(resource.Resource):
    def __init__(self, ui_dir):
        resource.Resource.__init__(self)
        self.ui_dir = ui_dir

    isLeaf = False

    def _delayed_render(self, request, results):
        request.write(str(results))
        request.finish()

    def getChild(self, name, request):
        if name == '':
            return self
        return resource.Resource.getChild(self, name, request)

    def render_GET(self, request):
        return static.File(os.path.join(self.ui_dir, "index.html")).render_GET(request)


class LBRYFileRender(resource.Resource):
    isLeaf = False

    def render_GET(self, request):
        if 'name' in request.args.keys():
            api = jsonrpc.Proxy(API_CONNECTION_STRING)
            d = api.callRemote("get", {'name': request.args['name'][0]})
            d.addCallback(lambda results: static.File(results['path']).render_GET(request))

            return server.NOT_DONE_YET
        else:
            return server.failure
