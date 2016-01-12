from lbrynet.core.Error import UnknownNameError
from lbrynet.lbryfile.StreamDescriptor import LBRYFileStreamType
from lbrynet.lbryfile.client.LBRYFileDownloader import LBRYFileSaverFactory, LBRYFileOpenerFactory
from lbrynet.lbryfile.client.LBRYFileOptions import add_lbry_file_to_sd_identifier
from lbrynet.lbrynet_daemon.LBRYDownloader import GetStream, FetcherDaemon
from lbrynet.core.utils import generate_id
from lbrynet.lbrynet_console.LBRYSettings import LBRYSettings
from lbrynet.conf import MIN_BLOB_DATA_PAYMENT_RATE
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier
from lbrynet.core.Session import LBRYSession
from lbrynet.core.PTCWallet import PTCWallet
from lbrynet.core.LBRYcrdWallet import LBRYcrdWallet
from lbrynet.lbryfilemanager.LBRYFileManager import LBRYFileManager
from lbrynet.lbryfile.LBRYFileMetadataManager import DBLBRYFileMetadataManager, TempLBRYFileMetadataManager
from twisted.web import xmlrpc, server
from twisted.internet import defer, threads, reactor
from datetime import datetime
import logging
import os
import sys
import sqlite3

log = logging.getLogger(__name__)


class DummyDownloader(object):
    def __init__(self, directory, file_name):
        self.download_directory = directory
        self.file_name = file_name


class DummyStream(object):
    def __init__(self, row):
        download_directory = os.path.join(*row[2].split('/')[:-1])
        file_name = row[2].split('/')[len(row[2].split('/')) - 1]

        self.stream_hash = row[0]
        self.downloader = DummyDownloader(download_directory, file_name)
        self.is_dummy = True


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
            self.current_db_revision = 1
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
            self.rpc_conn = None
            self.files = []
            self.created_data_dir = False
            if not os.path.exists(self.db_dir):
                os.mkdir(self.db_dir)
                self.created_data_dir = True
            self.session_settings = None
            self.data_rate = 0.5
            self.max_key_fee = 100.0
            self.db = None
            self.cur = None
            return defer.succeed(None)

        def _disp_startup():
            print "Started LBRYnet daemon"
            return defer.succeed(None)

        d = defer.Deferred()
        d.addCallback(lambda _: _set_vars())
        d.addCallback(lambda _: threads.deferToThread(self._setup_data_directory))
        d.addCallback(lambda _: self._check_db_migration())
        d.addCallback(lambda _: self._get_settings())
        d.addCallback(lambda _: self.get_lbrycrdd_path())
        d.addCallback(lambda _: self._get_session())
        d.addCallback(lambda _: add_lbry_file_to_sd_identifier(self.sd_identifier))
        d.addCallback(lambda _: self._setup_stream_identifier())
        d.addCallback(lambda _: self._setup_lbry_file_manager())
        d.addCallback(lambda _: self._setup_lbry_file_opener())
        d.addCallback(lambda _: self._setup_fetcher())
        d.addCallback(lambda _: self._setup_daemon_db())
        d.addCallback(lambda _: _disp_startup())
        d.callback(None)

        return defer.succeed(None)

    def _shutdown(self):
        print 'Closing lbrynet session'
        if self.session is not None:
            d = self.session.shut_down()
        else:
            d = defer.Deferred()
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

    def _setup_daemon_db(self):
        self.db = sqlite3.connect(os.path.join(self.db_dir, 'daemon.sqlite'))
        self.cur = self.db.cursor()

        query = "create table if not exists history            \
                    (stream_hash char(96) primary key not null,\
                    uri text not null,                         \
                    path text not null);"

        self.cur.execute(query)
        self.db.commit()

        r = self.cur.execute("select * from history")
        files = r.fetchall()

        print "Checking files in download history still exist, pruning records of those that don't"

        for file in files:
            if not os.path.isfile(file[2]):
                print "Couldn't find", file[2], ", removing record"
                self.cur.execute("delete from history where stream_hash='" + file[0] + "'")
                self.db.commit()

        print "Done checking records"

        return defer.succeed(None)

    def _get_settings(self):
        d = self.settings.start()
        d.addCallback(lambda _: self.settings.get_lbryid())
        d.addCallback(self.set_lbryid)
        d.addCallback(lambda _: self.get_lbrycrdd_path())
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
            self.rpc_conn = self.session.wallet.get_rpc_conn_x()

        dl = defer.DeferredList([d1, d2], fireOnOneErrback=True)
        dl.addCallback(combine_results)
        dl.addCallback(create_session)
        dl.addCallback(lambda _: self.session.setup())
        return dl

    def get_lbrycrdd_path(self):
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

    def _download_name(self, history, name):
        def _disp(stream):
            print '[' + str(datetime.now()) + ']' + ' Downloading: ' + str(stream.stream_hash)
            log.debug('[' + str(datetime.now()) + ']' + ' Downloading: ' + str(stream.stream_hash))
            return defer.succeed(None)

        if history == 'UnknownNameError':
            return 'UnknownNameError'

        if not history:
            stream = GetStream(self.sd_identifier, self.session, self.session.wallet, self.lbry_file_manager,
                                                        max_key_fee=self.max_key_fee, data_rate=self.data_rate)

            self.downloads.append(stream)

            d = self.session.wallet.get_stream_info_for_name(name)
            d.addCallback(lambda stream_info: stream.start(stream_info))
            d.addCallback(lambda _: _disp(stream))
            d.addCallback(lambda _: {'ts': datetime.now(),'name': name})
            d.addErrback(lambda err: str(err.getTraceback()))
            return d

        else:
            self.downloads.append(DummyStream(history[0]))
            return defer.succeed(None)

    def _path_from_name(self, name):
        d = self.session.wallet.get_stream_info_for_name(name)
        d.addCallback(lambda stream_info: stream_info['stream_hash'])
        d.addCallback(lambda stream_hash: [{'stream_hash': stream.stream_hash,
                                            'path': os.path.join(stream.downloader.download_directory,
                                                                 stream.downloader.file_name)}
                                           for stream in self.downloads if stream.stream_hash == stream_hash][0])
        d.addErrback(lambda _: 'UnknownNameError')
        return d

    def _get_downloads(self):
        downloads = []
        for stream in self.downloads:
            try:
                downloads.append({'stream_hash': stream.stream_hash,
                        'path': os.path.join(stream.downloader.download_directory, stream.downloader.file_name)})
            except:
                pass
        return downloads

    def _resolve_name(self, name):
        d = defer.Deferred()
        d.addCallback(lambda _: self.session.wallet.get_stream_info_for_name(name))
        d.addErrback(lambda _: 'UnknownNameError')
        d.callback(None)
        return d

    def _check_history(self, name, metadata):
        if metadata == 'UnknownNameError':
            return 'UnknownNameError'

        r = self.cur.execute("select * from history where stream_hash='" + metadata['stream_hash'] + "'")
        files = r.fetchall()

        if files:
            if not os.path.isfile(files[0][2]):
                print "Couldn't find", files[0][2], ", trying to redownload it"
                self.cur.execute("delete from history where stream_hash='" + files[0][0] + "'")
                self.db.commit()
                return []
            else:
                return files
        else:
            return files

    def _add_to_history(self, name, path):
        if path == 'UnknownNameError':
            return 'UnknownNameError'

        r = self.cur.execute("select * from history where stream_hash='" + path['stream_hash'] + "'")
        files = r.fetchall()
        if not files:
            vals = path['stream_hash'], name, path['path']
            self.cur.execute("insert into history values (?, ?, ?)", vals)
            self.db.commit()
        else:
            print 'Already downloaded', path['stream_hash'], '->', path['path']

        return path

    def xmlrpc_get_settings(self):
        """
        Get LBRY payment settings
        """

        if not self.session_settings:
            self.session_settings = {'data_rate': self.data_rate, 'max_key_fee': self.max_key_fee}

        return self.session_settings

    def xmlrpc_set_settings(self, settings):
        self.session_settings = settings
        self._update_settings()

        return 'Set'

    def xmlrpc_start_fetcher(self):
        """
        Start autofetcher
        """

        self.fetcher.start()

        return str('Started autofetching')

    def xmlrpc_stop_fetcher(self):
        """
        Start autofetcher
        """

        self.fetcher.stop()

        return str('Started autofetching')

    def xmlrpc_fetcher_status(self):
        """
        Start autofetcher
        """

        return str(self.fetcher.check_if_running())

    def xmlrpc_get_balance(self):
        """
        Get LBC balance
        """

        return str(self.session.wallet.wallet_balance)

    def xmlrpc_stop(self):
        """
        Stop the reactor
        """

        def _disp_shutdown():
            print 'Shutting down lbrynet daemon'

        d = self._shutdown()
        d.addCallback(lambda _: self.db.close())
        d.addCallback(lambda _: _disp_shutdown())
        d.addCallback(lambda _: reactor.stop())

        return d

    def xmlrpc_get_lbry_files(self):
        """
        Get LBRY files

        @return: Managed LBRY files
        """

        return [[str(i), str(dir(i))] for i in self.lbry_file_manager.lbry_files]

    def xmlrpc_resolve_name(self, name):
        """
        Resolve stream info from a LBRY uri

        @param: name
        """

        def _disp(info):
            log.debug('[' + str(datetime.now()) + ']' + ' Resolved info: ' + str(info))
            print '[' + str(datetime.now()) + ']' + ' Resolved info: ' + str(info)
            return info

        d = defer.Deferred()
        d.addCallback(lambda _: self.session.wallet.get_stream_info_for_name(name))
        d.addCallbacks(_disp, lambda _: str('UnknownNameError'))
        d.callback(None)
        return d

    def xmlrpc_get_downloads(self):
        """
        Get files downloaded in this session

        @return: [{stream_hash, path}]
        """

        downloads = []

        for stream in self.downloads:
            try:
                downloads.append({'stream_hash': stream.stream_hash,
                        'path': os.path.join(stream.downloader.download_directory, stream.downloader.file_name)})
            except:
                pass

        return downloads

    def xmlrpc_download_name(self, name):
        """
        Download stream from a LBRY uri

        @param: name
        """

        def _disp(stream):
            print '[' + str(datetime.now()) + ']' + ' Downloading: ' + str(stream.stream_hash)
            log.debug('[' + str(datetime.now()) + ']' + ' Downloading: ' + str(stream.stream_hash))
            return defer.succeed(None)

        stream = GetStream(self.sd_identifier, self.session, self.session.wallet, self.lbry_file_manager,
                                                        max_key_fee=self.max_key_fee, data_rate=self.data_rate)

        self.downloads.append(stream)

        d = self.session.wallet.get_stream_info_for_name(name)
        d.addCallback(lambda stream_info: stream.start(stream_info))
        d.addCallback(lambda _: _disp(stream))
        d.addCallback(lambda _: {'ts': datetime.now(),'name': name})
        d.addErrback(lambda err: str(err.getTraceback()))
        return d

    def xmlrpc_path_from_name(self, name):
        """
        Get file path for a downloaded name

        @param: name
        @return: {stream_hash, path}:
        """

        d = self.session.wallet.get_stream_info_for_name(name)
        d.addCallback(lambda stream_info: stream_info['stream_hash'])
        d.addCallback(lambda stream_hash: [{'stream_hash': stream.stream_hash,
                                            'path': os.path.join(stream.downloader.download_directory,
                                                                 stream.downloader.file_name)}
                                           for stream in self.downloads if stream.stream_hash == stream_hash][0])
        d.addErrback(lambda _: 'UnknownNameError')
        return d

    def xmlrpc_get(self, name):
        """
        Download a name and return the path of the resulting file

        @param: name:
        @return: {stream_hash, path}:
        """

        d = self._resolve_name(name)
        d.addCallback(lambda metadata: self._check_history(name, metadata))
        d.addCallback(lambda hist: self._download_name(hist, name))
        d.addCallback(lambda _: self._path_from_name(name))
        d.addCallback(lambda path: self._add_to_history(name, path))
        return d


def main():
    daemon = LBRYDaemon()
    daemon.setup()
    reactor.listenTCP(7080, server.Site(daemon))
    reactor.run()

if __name__ == '__main__':
    main()