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
from lbrynet.conf import MIN_BLOB_DATA_PAYMENT_RATE
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier, download_sd_blob
from lbrynet.core.Session import LBRYSession
from lbrynet.core.PTCWallet import PTCWallet
from lbrynet.core.LBRYcrdWallet import LBRYcrdWallet
from lbrynet.lbryfilemanager.LBRYFileManager import LBRYFileManager
from lbrynet.lbryfile.LBRYFileMetadataManager import DBLBRYFileMetadataManager, TempLBRYFileMetadataManager
from twisted.web import xmlrpc, server
from twisted.internet import defer, threads, reactor, error
from datetime import datetime
import logging
import os
import sys
import json
import binascii
import webbrowser
import xmlrpclib
from decimal import Decimal

log = logging.getLogger(__name__)

#TODO add login credentials in a conf file

#issues with delete:
#TODO when stream is stopped the generated file is deleted

#functions to add:
#TODO send credits to address
#TODO alert if your copy of a lbry file is out of date with the name record


class LBRYDaemon(xmlrpc.XMLRPC):
    """
    LBRYnet daemon
    """

    def setup(self):
        def _set_vars():
            self.fetcher = None
            self.current_db_revision = 1
            self.run_server = True
            self.session = None
            self.known_dht_nodes = [('104.236.42.182', 4000)]
            self.db_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
            self.blobfile_dir = os.path.join(self.db_dir, "blobfiles")
            self.peer_port = 3333
            self.dht_node_port = 4444
            self.first_run = False
            if os.name == "nt":
                from lbrynet.winhelpers.knownpaths import get_path, FOLDERID, UserHandle
                self.download_directory = get_path(FOLDERID.Downloads, UserHandle.current)
                self.wallet_dir = os.path.join(get_path(FOLDERID.RoamingAppData, UserHandle.current), "lbrycrd")
            elif sys.platform == "darwin":
                self.download_directory = os.path.join(os.path.expanduser("~"), 'Downloads')
                self.wallet_dir = os.path.join(os.path.expanduser("~"), "Library/Application Support/lbrycrd")
            else:
                self.wallet_dir = os.path.join(os.path.expanduser("~"), ".lbrycrd")
                self.download_directory = os.path.join(os.path.expanduser("~"), 'Downloads')

            self.wallet_conf = os.path.join(self.wallet_dir, "lbrycrd.conf")
            self.wallet_user = None
            self.wallet_password = None
            self.sd_identifier = StreamDescriptorIdentifier()
            self.stream_info_manager = TempLBRYFileMetadataManager()
            self.wallet_rpc_port = 8332
            self.downloads = []
            self.stream_frames = []
            self.default_blob_data_payment_rate = MIN_BLOB_DATA_PAYMENT_RATE
            self.use_upnp = True
            self.start_lbrycrdd = True
            if os.name == "nt":
                self.lbrycrdd_path = "lbrycrdd.exe"
            else:
                self.lbrycrdd_path = "./lbrycrdd"
            self.delete_blobs_on_remove = True
            self.blob_request_payment_rate_manager = None
            self.lbry_file_metadata_manager = None
            self.lbry_file_manager = None
            self.settings = LBRYSettings(self.db_dir)
            self.wallet_type = "lbrycrd"
            self.lbrycrd_conf = os.path.join(self.wallet_dir, "lbrycrd.conf")
            self.autofetcher_conf = os.path.join(self.wallet_dir, "autofetcher.conf")
            self.files = []
            self.created_data_dir = False
            if not os.path.exists(self.db_dir):
                os.mkdir(self.db_dir)
                self.created_data_dir = True
            self.session_settings = None
            self.data_rate = MIN_BLOB_DATA_PAYMENT_RATE
            self.max_key_fee = 100.0
            self.query_handlers = {}

            return defer.succeed(None)

        def _disp_startup():
            print "Started LBRYnet daemon"
            print "The daemon can be shut down by running 'stop-lbrynet-daemon' in a terminal"
            return defer.succeed(None)

        d = defer.Deferred()
        d.addCallback(lambda _: _set_vars())
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
        d.addCallback(lambda _: _disp_startup())
        d.callback(None)

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

        dl = self.settings.get_server_running_status()
        dl.addCallback(restore_running_status)
        return dl

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

    def _shutdown(self):
        print 'Closing lbrynet session'
        d = self._stop_server()
        if self.session is not None:
            d.addCallback(lambda _: self.session.shut_down())
        return d

    def _update_settings(self):
        self.data_rate = self.session_settings['data_rate']
        self.max_key_fee = self.session_settings['max_key_fee']

    def _setup_fetcher(self):
        self.fetcher = FetcherDaemon(self.session, self.lbry_file_manager, self.lbry_file_metadata_manager,
                                     self.session.wallet, self.sd_identifier, self.autofetcher_conf)
        return defer.succeed(None)

    def _setup_data_directory(self):
        print "Loading databases..."
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
        d.addCallback(self._set_lbryid)
        d.addCallback(lambda _: self._get_lbrycrdd_path())
        return d

    def _set_lbryid(self, lbryid):
        if lbryid is None:
            return self._make_lbryid()
        else:
            self.lbryid = lbryid

    def _make_lbryid(self):
        self.lbryid = generate_id()
        d = self.settings.save_lbryid(self.lbryid)
        return d

    def _setup_lbry_file_manager(self):
        self.lbry_file_metadata_manager = DBLBRYFileMetadataManager(self.db_dir)
        d = self.lbry_file_metadata_manager.setup()

        def set_lbry_file_manager():
            self.lbry_file_manager = LBRYFileManager(self.session, self.lbry_file_metadata_manager, self.sd_identifier)
            return self.lbry_file_manager.setup()

        d.addCallback(lambda _: set_lbry_file_manager())

        return d

    def _get_session(self):
        def get_default_data_rate():
            d = self.settings.get_default_data_payment_rate()
            d.addCallback(lambda rate: {"default_data_payment_rate":
                                            rate if rate is not None else MIN_BLOB_DATA_PAYMENT_RATE})
            return d

        def get_wallet():
            if self.wallet_type == "lbrycrd":
                lbrycrdd_path = None
                if self.start_lbrycrdd is True:
                    lbrycrdd_path = self.lbrycrdd_path
                    if not lbrycrdd_path:
                        lbrycrdd_path = self.default_lbrycrdd_path
                d = defer.succeed(LBRYcrdWallet(self.db_dir, wallet_dir=self.wallet_dir, wallet_conf=self.lbrycrd_conf,
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
            self.session = LBRYSession(results['default_data_payment_rate'], db_dir=self.db_dir, lbryid=self.lbryid,
                                       blob_dir=self.blobfile_dir, dht_node_port=self.dht_node_port,
                                       known_dht_nodes=self.known_dht_nodes, peer_port=self.peer_port,
                                       use_upnp=self.use_upnp, wallet=results['wallet'])

        dl = defer.DeferredList([d1, d2], fireOnOneErrback=True)
        dl.addCallback(combine_results)
        dl.addCallback(create_session)
        dl.addCallback(lambda _: self.session.setup())
        return dl

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
                    print self.lbrycrdd_path

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

    def _setup_lbry_file_manager(self):
        self.lbry_file_metadata_manager = DBLBRYFileMetadataManager(self.db_dir)
        d = self.lbry_file_metadata_manager.setup()

        def set_lbry_file_manager():
            self.lbry_file_manager = LBRYFileManager(self.session, self.lbry_file_metadata_manager, self.sd_identifier)
            return self.lbry_file_manager.setup()

        d.addCallback(lambda _: set_lbry_file_manager())

        return d

    def _setup_lbry_file_opener(self):

        downloader_factory = LBRYFileOpenerFactory(self.session.peer_finder, self.session.rate_limiter,
                                                   self.session.blob_manager, self.stream_info_manager,
                                                   self.session.wallet)
        self.sd_identifier.add_stream_downloader_factory(LBRYFileStreamType, downloader_factory)
        return defer.succeed(True)

    def _download_name(self, name):
        def _disp_file(file):
            print '[' + str(datetime.now()) + ']' + ' Already downloaded: ' + str(file.stream_hash)
            d = self._path_from_lbry_file(file)
            return d

        def _get_stream(name):
            def _disp(stream):
                print '[' + str(datetime.now()) + ']' + ' Start stream: ' + stream['stream_hash']
                return stream

            d = self.session.wallet.get_stream_info_for_name(name)
            stream = GetStream(self.sd_identifier, self.session, self.session.wallet, self.lbry_file_manager,
                                                        max_key_fee=self.max_key_fee, data_rate=self.data_rate)
            d.addCallback(_disp)
            d.addCallback(lambda stream_info: stream.start(stream_info))
            d.addCallback(lambda _: self._path_from_name(name))

            return d

        d = self._check_history(name)
        d.addCallback(lambda lbry_file: _get_stream(name) if not lbry_file else _disp_file(lbry_file))
        d.addCallback(lambda _: self._check_history(name))
        d.addCallback(lambda lbry_file: self._path_from_lbry_file(lbry_file) if lbry_file else 'Not found')
        d.addErrback(lambda err: str(err))

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
            lbry_file = [file for file in self.lbry_file_manager.lbry_files if file.stream_name == file_name]
            if lbry_file:
                return lbry_file[0]
            else:
                return None

        def _check(info):
            stream_hash = info['stream_hash']
            path = os.path.join(self.blobfile_dir, stream_hash)
            if os.path.isfile(path):
                print "[" + str(datetime.now()) + "] Search for lbry_file, returning: " + stream_hash
                return defer.succeed(_get_lbry_file(path))
            else:
                print  "[" + str(datetime.now()) + "] Search for lbry_file didn't return anything"
                return defer.succeed(False)

        d = self._resolve_name(name)
        d.addCallbacks(_check, lambda _: False)
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
            return d

        d.addCallback(lambda _: finish_deletion(lbry_file))
        return d

    def _path_from_name(self, name):
        d = self._check_history(name)
        d.addCallback(lambda lbry_file: {'stream_hash': lbry_file.stream_hash,
                                         'path': os.path.join(self.download_directory, lbry_file.file_name)}
                                        if lbry_file else defer.fail(UnknownNameError))
        return d

    def _path_from_lbry_file(self, lbry_file):
        if lbry_file:
            r = {'stream_hash': lbry_file.stream_hash,
                 'path': os.path.join(self.download_directory, lbry_file.file_name)}
            return defer.succeed(r)
        else:
            return defer.fail(UnknownNameError)

    def _get_est_cost(self, name):
        def _check_est(d, name):
            if type(d.result) is float:
                print '[' + str(datetime.now()) + '] Cost est for lbry://' + name + ': ' + str(d.result) + 'LBC'
            else:
                print '[' + str(datetime.now()) + '] Timeout estimating cost for lbry://' + name + ', using key fee'
                d.cancel()
            return defer.succeed(None)

        def _to_dict(r):
            t = {}
            for i in r:
                t[i[0]] = i[1]
            return t

        def _add_key_fee(data_cost):
            d = self.session.wallet.get_stream_info_for_name(name)
            d.addCallback(lambda info: info['key_fee'] if 'key_fee' in info.keys() else 0.0)
            d.addCallback(lambda key_fee: key_fee + data_cost)
            return d

        d = self.session.wallet.get_stream_info_for_name(name)
        d.addCallback(lambda info: download_sd_blob(self.session, info['stream_hash'],
                                                    self.blob_request_payment_rate_manager))
        d.addCallback(self.sd_identifier.get_metadata_for_sd_blob)
        d.addCallback(lambda metadata: metadata.validator.info_to_show())
        d.addCallback(_to_dict)
        d.addCallback(lambda info: int(info['stream_size'])/1000000*self.data_rate)
        d.addCallback(_add_key_fee)
        d.addErrback(lambda _: _add_key_fee(0.0))
        reactor.callLater(3.0, _check_est, d, name)

        return d

    def xmlrpc_get_settings(self):
        """
        Get LBRY payment settings

        @return {'data_rate': float, 'max_key_fee': float}
        """

        if not self.session_settings:
            self.session_settings = {'data_rate': self.data_rate, 'max_key_fee': self.max_key_fee}

        print '[' + str(datetime.now()) + '] Get daemon settings'
        return self.session_settings

    def xmlrpc_set_settings(self, settings):
        """
        Set LBRY payment settings

        @param settings dict: {'data_rate': float, 'max_key_fee': float}
        """

        self.session_settings = settings
        self._update_settings()

        print '[' + str(datetime.now()) + '] Set daemon settings'
        return 'Set'

    def xmlrpc_start_fetcher(self):
        """
        Start autofetcher
        """

        self.fetcher.start()
        print '[' + str(datetime.now()) + '] Start autofetcher'
        return 'Started autofetching'

    def xmlrpc_stop_fetcher(self):
        """
        Stop autofetcher
        """

        self.fetcher.stop()
        print '[' + str(datetime.now()) + '] Stop autofetcher'
        return 'Stopped autofetching'

    def xmlrpc_fetcher_status(self):
        """
        Start autofetcher
        """

        print '[' + str(datetime.now()) + '] Get fetcher status'
        return str(self.fetcher.check_if_running())

    def xmlrpc_get_balance(self):
        """
        Get LBC balance
        """

        print '[' + str(datetime.now()) + '] Get balance'
        return str(self.session.wallet.wallet_balance)

    def xmlrpc_stop(self):
        """
        Stop lbrynet-daemon
        """

        def _disp_shutdown():
            print 'Shutting down lbrynet daemon'

        d = self._shutdown()
        d.addCallback(lambda _: _disp_shutdown())
        d.addCallback(lambda _: reactor.callLater(1.0, reactor.stop))

        return defer.succeed('Shutting down')

    def xmlrpc_get_lbry_files(self):
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

        print '[' + str(datetime.now()) + '] Get LBRY files'
        return r

    def xmlrpc_resolve_name(self, name):
        """
        Resolve stream info from a LBRY uri

        @param: name
        @return: info for name claim
        """

        def _disp(info):
            log.debug('[' + str(datetime.now()) + ']' + ' Resolved info: ' + str(info['stream_hash']))
            print '[' + str(datetime.now()) + ']' + ' Resolved info: ' + str(info['stream_hash'])
            return info

        d = self._resolve_name(name)
        d.addCallbacks(_disp, lambda _: str('UnknownNameError'))
        d.callback(None)
        return d

    def xmlrpc_get(self, name):
        """
        Download stream from a LBRY uri

        @param: name
        @return: {'stream_hash': hex string, 'path': path of download}
        """

        if name:
            d = self._download_name(name)
        else:
            d = defer.succeed('No name provided')
        return d

    def xmlrpc_stop_lbry_file(self, stream_hash):
        try:
            lbry_file = [f for f in self.lbry_file_manager.lbry_files if f.stream_hash == stream_hash][0]
        except IndexError:
            return defer.fail(UnknownNameError)

        if not lbry_file.stopped:
            d = self.lbry_file_manager.toggle_lbry_file_running(lbry_file)
            d.addCallback(lambda _: 'Stream has been stopped')
            d.addErrback(lambda err: str(err))
            return d
        else:
            return defer.succeed('Stream was already stopped')

    def xmlrpc_start_lbry_file(self, stream_hash):
        try:
            lbry_file = [f for f in self.lbry_file_manager.lbry_files if f.stream_hash == stream_hash][0]
        except IndexError:
            return defer.fail(UnknownNameError)

        if lbry_file.stopped:
            d = self.lbry_file_manager.toggle_lbry_file_running(lbry_file)
            d.callback(None)
            return defer.succeed('Stream started')
        else:
            return defer.succeed('Stream was already running')

    def xmlrpc_render_html(self, html):
        """
        Writes html to lbry.html in the downloads directory, then opens it with the browser

        @param html:
        """

        def _make_file(html, path):
            f = open(path, 'w')
            f.write(html)
            f.close()
            return defer.succeed(None)

        def _disp_err(err):
            print str(err.getTraceback())
            return err

        path = os.path.join(self.download_directory, 'lbry.html')

        d = defer.Deferred()
        d.addCallback(lambda _: _make_file(html, path))
        d.addCallback(lambda _: webbrowser.open('file://' + path))
        d.addErrback(_disp_err)
        d.callback(None)

        return d

    def xmlrpc_render_gui(self):
        """
        Opens the lbry web ui in a browser
        """

        def _disp_err(err):
            print str(err.getTraceback())
            return err
        d = defer.Deferred()
        d.addCallback(lambda _: webbrowser.open("file://" + str(os.path.join(self.download_directory, "lbryio/view/page/gui.html"))))
        d.addErrback(_disp_err)
        d.callback(None)

        return d

    def xmlrpc_search_nametrie(self, search):
        """
        Search the nametrie for claims beginning with search

        @param search:
        @return:
        """

        def _return_d(x):
            d = defer.Deferred()
            d.addCallback(lambda _: x)
            d.callback(None)

            return d

        def _clean(n):
            t = []
            for i in n:
                if i[0]:
                    if i[1][0][0] and i[1][1][0] and i[1][2][0]:
                        i[1][0][1]['value'] = str(i[1][0][1]['value'])
                        t.append([i[1][0][1], i[1][1][1], i[1][2][1]])
            return t

        def _parse(results):
            f = []
            for chain, meta, cost_est in results:
                t = {}
                if 'name' in chain.keys():
                    t['name'] = chain['name']
                if 'thumbnail' in meta.keys():
                    t['img'] = meta['thumbnail']
                else:
                    t['img'] = 'File://' + str(os.path.join(self.download_directory, "lbryio/web/img/Free-speech-flag.svg"))
                if 'name' in meta.keys():
                    t['title'] = meta['name']
                if 'description' in meta.keys():
                    t['description'] = meta['description']
                t['cost_est'] = cost_est
                f.append(t)

            return f

        def _disp(results):
            print '[' + str(datetime.now()) + '] Found ' + str(len(results)) + ' results'
            return results

        print '[' + str(datetime.now()) + '] Search nametrie: ' + search

        filtered_results = [n for n in self.session.wallet.get_nametrie() if n['name'].startswith(search)]
        if len(filtered_results) > 25:
            filtered_results = filtered_results[:25]
        filtered_results = [n for n in filtered_results if 'txid' in n.keys()]
        resolved_results = [defer.DeferredList([_return_d(n), self._resolve_name_wc(n['name']),
                                                self._get_est_cost(n['name'])])
                                                for n in filtered_results]

        d = defer.DeferredList(resolved_results)
        d.addCallback(_clean)
        d.addCallback(_parse)
        d.addCallback(_disp)

        return d

    def xmlrpc_delete_lbry_file(self, file_name):
        def _disp(file_name):
            print '[' + str(datetime.now()) + '] Deleted: ' + file_name
            return defer.succeed('Deleted: ' + file_name)

        lbry_files = [self._delete_lbry_file(f) for f in self.lbry_file_manager.lbry_files if file_name == f.file_name]
        d = defer.DeferredList(lbry_files)
        d.addCallback(lambda _: _disp(file_name))
        return d

    def xmlrpc_check(self, name):
        d = self._check_history(name)
        d.addCallback(lambda lbry_file: self._path_from_lbry_file(lbry_file) if lbry_file else 'Not found')
        d.addErrback(lambda err: str(err))

        return d

    def xmlrpc_publish(self, metadata):
        metadata = json.loads(metadata)

        required = ['name', 'file_path', 'bid']

        for r in required:
            if not r in metadata.keys():
                return defer.fail()

        # if not os.path.isfile(metadata['file_path']):
        #     return defer.fail()

        if not isinstance(metadata['bid'], float) and metadata['bid'] > 0.0:
            return defer.fail()

        name = metadata['name']
        file_path = metadata['file_path']
        bid = metadata['bid']

        if 'title' in metadata.keys():
            title = metadata['title']
        else:
            title = None

        if 'description' in metadata.keys():
            description = metadata['description']
        else:
            description = None

        if 'thumbnail' in metadata.keys():
            thumbnail = metadata['thumbnail']
        else:
            thumbnail = None

        if 'key_fee' in metadata.keys():
            if not float(metadata['key_fee']) == 0.0:
                if not 'key_fee_address' in metadata.keys():
                    return defer.fail()
            key_fee = metadata['key_fee']
        else:
            key_fee = 0.0

        if 'key_fee_address' in metadata.keys():
            key_fee_address = metadata['key_fee_address']
        else:
            key_fee_address = None

        if 'content_license' in metadata.keys():
            content_license = metadata['content_license']
        else:
            content_license = None

        p = Publisher(self.session, self.lbry_file_manager, self.session.wallet)
        d = p.start(name, file_path, bid, title, description, thumbnail, key_fee, key_fee_address, content_license)

        return d

    def xmlrpc_abandon_name(self, txid):
        def _disp(txid, tx):
            print '[' + str(datetime.now()) + '] Spent coins from claim tx ' + txid + ' --> ' + tx
            return tx

        d = defer.Deferred()
        d.addCallback(lambda _: self.session.wallet.abandon_name(txid))
        d.addCallback(lambda tx: _disp(txid, tx))
        d.addErrback(lambda err: str(err.getTraceback()))
        d.callback(None)

        return d

    def xmlrpc_get_name_claims(self):
        def _clean(claims):
            for c in claims:
                for k in c.keys():
                    if isinstance(c[k], Decimal):
                        c[k] = float(c[k])
            return claims

        d = self.session.wallet.get_name_claims()
        d.addCallback(_clean)

        return d

    def xmlrpc_get_time_behind_blockchain(self):
        d = self.session.wallet.get_most_recent_blocktime()
        d.addCallback(get_time_behind_blockchain)

        return d

    # def xmlrpc_update_name(self, metadata):
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

    def xmlrpc_toggle_fetcher_verbose(self):
        if self.fetcher.verbose:
            self.fetcher.verbose = False
        else:
            self.fetcher.verbose = True

        return self.fetcher.verbose


def main():
    try:
        d = xmlrpclib.ServerProxy('http://localhost:7080')
        d.stop()
    except:
        pass

    daemon = LBRYDaemon()
    daemon.setup()
    reactor.listenTCP(7080, server.Site(daemon))
    reactor.run()

if __name__ == '__main__':
    main()