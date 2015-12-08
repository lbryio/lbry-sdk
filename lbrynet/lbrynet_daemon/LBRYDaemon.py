import os
from lbrynet.lbryfile.StreamDescriptor import LBRYFileStreamType
from lbrynet.lbryfile.client.LBRYFileDownloader import LBRYFileSaverFactory, LBRYFileOpenerFactory
from lbrynet.lbryfile.client.LBRYFileOptions import add_lbry_file_to_sd_identifier
from lbrynet.core.client.AutoDownloader import GetStream
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


class LBRYDaemon(xmlrpc.XMLRPC):
    """
    LBRYnet daemon
    """

    def setup(self):
        def _set_vars():
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
            else:
                self.download_directory = os.path.join(os.path.expanduser("~"), 'Downloads')
                self.wallet_dir = os.path.join(os.path.expanduser("~"), ".lbrycrd")
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
            self.lbrycrd_dir = os.path.join(os.path.expanduser("~"), ".lbrycrd")
            self.lbrycrd_conf = os.path.join(self.lbrycrd_dir, "lbrycrd.conf")
            self.rpc_conn = None
            self.files = []
            return defer.succeed(None)

        d = defer.Deferred()
        d.addCallback(lambda _: _set_vars())
        d.addCallback(lambda _: self._get_settings())
        d.addCallback(lambda _: self.get_lbrycrdd_path())
        d.addCallback(lambda _: self._get_session())
        d.addCallback(lambda _: add_lbry_file_to_sd_identifier(self.sd_identifier))
        d.addCallback(lambda _: self._setup_stream_identifier())
        d.addCallback(lambda _: self._setup_lbry_file_manager())
        d.addCallback(lambda _: self._setup_lbry_file_opener())
        d.callback(None)

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
                d = defer.succeed(LBRYcrdWallet(self.db_dir, wallet_dir=self.lbrycrd_dir, wallet_conf=self.lbrycrd_conf,
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

    def xmlrpc_get_balance(self):
        """
        Get LBC balance
        """
        return str(self.session.wallet.wallet_balance)

    def xmlrpc_stop(self):
        """
        Stop the reactor
        """

        reactor.stop()
        return defer.succeed('Stopping')

    def xmlrpc_resolve_name(self, name):
        """
        Resolve stream info from a LBRY uri
        """

        def _disp(info):
            print '[' + str(datetime.now()) + ']' + ' Resolved info: ' + str(info)
            return info

        d = defer.Deferred()
        d.addCallback(lambda _: self.session.wallet.get_stream_info_for_name(name))
        d.addErrback(lambda _: 'UnknownNameError')
        d.addCallback(_disp)
        d.callback(None)
        return d

    def xmlrpc_get_downloads(self):
        """
        Get downloads
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
        """

        def _disp():
            try:
                stream = self.downloads[-1]
                print '[' + str(datetime.now()) + ']' + ' Downloading: ' + str(stream.stream_hash)
                return defer.succeed(None)
            except:
                pass

        stream = GetStream(self.sd_identifier, self.session, self.session.wallet, self.lbry_file_manager, 25.0)
        self.downloads.append(stream)

        d = self.session.wallet.get_stream_info_for_name(name)
        d.addCallback(lambda stream_info: stream.start(stream_info))
        d.addCallback(lambda _: _disp())
        # d.addCallback(lambda _: self.files.append({'name': name, 'stream_hash': stream.stream_hash,
        #                  'path': os.path.join(stream.downloader.download_directory, stream.downloader.file_name)}))
        d.addCallback(lambda _: {'ts': datetime.now(),'name': name})
        d.addErrback(lambda _: 'UnknownNameError')

        return d

    def xmlrpc_path_from_name(self, name):
        d = self.session.wallet.get_stream_info_for_name(name)
        d.addCallback(lambda stream_info: stream_info['stream_hash'])
        d.addCallback(lambda stream_hash: [{'stream_hash': stream.stream_hash,
                                            'path': os.path.join(stream.downloader.download_directory,
                                                                 stream.downloader.file_name)}
                                           for stream in self.downloads if stream.stream_hash == stream_hash])
        return d
    

def main():
    daemon = LBRYDaemon()
    daemon.setup()
    reactor.listenTCP(7080, server.Site(daemon))
    reactor.run()

if __name__ == '__main__':
    main()