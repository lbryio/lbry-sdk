import binascii
import logging
import tkMessageBox
from Crypto import Random
from lbrynet.conf import MIN_BLOB_DATA_PAYMENT_RATE
from lbrynet.core import StreamDescriptor
from lbrynet.core.LBRYcrdWallet import LBRYcrdWallet
from lbrynet.core.PaymentRateManager import PaymentRateManager
from lbrynet.core.Session import LBRYSession
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier
from lbrynet.lbryfile.LBRYFileMetadataManager import TempLBRYFileMetadataManager
from lbrynet.lbryfile.StreamDescriptor import LBRYFileStreamType
from lbrynet.lbryfile.client.LBRYFileDownloader import LBRYFileSaverFactory, LBRYFileOpenerFactory
from lbrynet.lbryfile.client.LBRYFileOptions import add_lbry_file_to_sd_identifier
import os
import requests
from twisted.internet import threads, defer, task


class LBRYDownloader(object):
    def __init__(self):
        self.session = None
        self.known_dht_nodes = [('104.236.42.182', 4000)]
        self.conf_dir = os.path.join(os.path.expanduser("~"), ".lbrydownloader")
        self.data_dir = os.path.join(self.conf_dir, "blobfiles")
        self.wallet_dir = os.path.join(os.path.expanduser("~"), ".lbrycrd")
        self.wallet_conf = os.path.join(self.wallet_dir, "lbrycrd.conf")
        self.first_run = False
        if os.name == "nt":
            from lbrynet.winhelpers.knownpaths import get_path, FOLDERID, UserHandle
            self.download_directory = get_path(FOLDERID.Downloads, UserHandle.current)
        else:
            self.download_directory = os.getcwd()
        self.wallet_user = None
        self.wallet_password = None
        self.sd_identifier = StreamDescriptorIdentifier()
        self.wallet_rpc_port = 8332
        self.download_deferreds = []
        self.stream_frames = []

    def start(self):
        d = threads.deferToThread(self._create_directory)
        d.addCallback(lambda _: self._get_session())
        d.addCallback(lambda _: self._setup_stream_info_manager())
        d.addCallback(lambda _: self._setup_stream_identifier())
        return d

    def stop(self):
        dl = defer.DeferredList(self.download_deferreds)
        for stream_frame in self.stream_frames:
            stream_frame.cancel_func()
        if self.session is not None:
            dl.addBoth(lambda _: self.session.shut_down())
        return dl

    def get_new_address(self):
        return self.session.wallet.get_new_address()

    def _create_directory(self):
        if not os.path.exists(self.conf_dir):
            os.makedirs(self.conf_dir)
            logging.debug("Created the configuration directory: %s", str(self.conf_dir))
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            logging.debug("Created the data directory: %s", str(self.data_dir))
        if not os.path.exists(self.wallet_dir):
            os.makedirs(self.wallet_dir)
        if not os.path.exists(self.wallet_conf):
            lbrycrd_conf = open(self.wallet_conf, mode='w')
            self.wallet_user = "rpcuser"
            lbrycrd_conf.write("rpcuser=%s\n" % self.wallet_user)
            self.wallet_password = binascii.hexlify(Random.new().read(20))
            lbrycrd_conf.write("rpcpassword=%s\n" % self.wallet_password)
            lbrycrd_conf.write("server=1\n")
            lbrycrd_conf.close()
            self.first_run = True
        else:
            lbrycrd_conf = open(self.wallet_conf)
            for l in lbrycrd_conf:
                if l.startswith("rpcuser="):
                    self.wallet_user = l[8:-1]
                if l.startswith("rpcpassword="):
                    self.wallet_password = l[12:-1]
                if l.startswith("rpcport="):
                    self.wallet_rpc_port = int(l[8:-1])

    def _get_session(self):
        wallet = LBRYcrdWallet(self.wallet_user, self.wallet_password, "127.0.0.1", self.wallet_rpc_port,
                               start_lbrycrdd=True, wallet_dir=self.wallet_dir, wallet_conf=self.wallet_conf)
        self.session = LBRYSession(MIN_BLOB_DATA_PAYMENT_RATE, db_dir=self.conf_dir, blob_dir=self.data_dir,
                                   use_upnp=False, wallet=wallet,
                                   known_dht_nodes=self.known_dht_nodes, dht_node_port=4447)
        return self.session.setup()

    def _setup_stream_info_manager(self):
        self.stream_info_manager = TempLBRYFileMetadataManager()
        return defer.succeed(True)

    def _setup_stream_identifier(self):
        add_lbry_file_to_sd_identifier(self.sd_identifier)
        file_saver_factory = LBRYFileSaverFactory(self.session.peer_finder, self.session.rate_limiter,
                                                  self.session.blob_manager, self.stream_info_manager,
                                                  self.session.wallet, self.download_directory)
        self.sd_identifier.add_stream_downloader_factory(LBRYFileStreamType, file_saver_factory)
        file_opener_factory = LBRYFileOpenerFactory(self.session.peer_finder, self.session.rate_limiter,
                                                    self.session.blob_manager, self.stream_info_manager,
                                                    self.session.wallet)
        self.sd_identifier.add_stream_downloader_factory(LBRYFileStreamType, file_opener_factory)

    def do_first_run(self):
        if self.first_run is True:
            d = self.session.wallet.get_new_address()

            def send_request(url, data):
                r = requests.post(url, json=data)
                if r.status_code == 200:
                    return r.json()['credits_sent']
                return 0.0

            def log_error(err):
                logging.warning("unable to request free credits. %s", err.getErrorMessage())
                return 0.0

            def request_credits(address):
                url = "http://credreq.lbry.io/requestcredits"
                data = {"address": address}
                d = threads.deferToThread(send_request, url, data)
                d.addErrback(log_error)
                return d

            d.addCallback(request_credits)
            return d
        return defer.succeed(0.0)

    def _resolve_name(self, uri):
        return self.session.wallet.get_stream_info_for_name(uri)

    def download_stream(self, stream_frame, uri):
        resolve_d = self._resolve_name(uri)

        stream_frame.show_metadata_status("resolving name...")

        stream_frame.cancel_func = resolve_d.cancel
        payment_rate_manager = PaymentRateManager(self.session.base_payment_rate_manager)

        def update_stream_name(value):
            if 'name' in value:
                stream_frame.show_name(value['name'])
            if 'description' in value:
                stream_frame.show_description(value['description'])
            return value

        def get_sd_hash(value):
            if 'stream_hash' in value:
                return value['stream_hash']
            raise ValueError("Invalid stream")

        def get_sd_blob(sd_hash):
            stream_frame.show_metadata_status("name resolved, fetching metadata...")
            get_sd_d = StreamDescriptor.download_sd_blob(self.session, sd_hash,
                                                         payment_rate_manager)
            get_sd_d.addCallback(self.sd_identifier.get_info_and_factories_for_sd_blob)
            get_sd_d.addCallbacks(choose_download_factory, bad_sd_blob)
            return get_sd_d

        def get_info_from_validator(info_validator):
            stream_name = None
            stream_size = None
            for field, val in info_validator.info_to_show():
                if field == "suggested_file_name":
                    stream_name = val
                elif field == "stream_name" and stream_name is None:
                    stream_name = val
                elif field == "stream_size":
                    stream_size = int(val)
            if stream_size is None:
                stream_size = "unknown"
            if stream_name is None:
                stream_name = "unknown"
            return stream_name, stream_size

        def choose_download_factory(info_and_factories):
            info_validator, options, factories = info_and_factories
            stream_name, stream_size = get_info_from_validator(info_validator)
            if isinstance(stream_size, (int, long)):
                price = payment_rate_manager.get_effective_min_blob_data_payment_rate()
                estimated_cost = stream_size * 1.0 / 2**20 * price
            else:
                estimated_cost = "unknown"

            stream_frame.show_stream_metadata(stream_name, stream_size)

            available_options = options.get_downloader_options(info_validator, payment_rate_manager)

            stream_frame.show_download_options(available_options)

            get_downloader_d = defer.Deferred()

            def create_downloader(f, chosen_options):

                def fire_get_downloader_d(downloader):
                    if not get_downloader_d.called:
                        get_downloader_d.callback(downloader)

                stream_frame.disable_download_buttons()
                d = f.make_downloader(info_validator, chosen_options,
                                      payment_rate_manager)
                d.addCallback(fire_get_downloader_d)

            for factory in factories:

                def choose_factory(f=factory):
                    chosen_options = stream_frame.get_chosen_options()
                    create_downloader(f, chosen_options)

                stream_frame.add_download_factory(factory, choose_factory)

            get_downloader_d.addCallback(start_download)

            return get_downloader_d

        def show_stream_status(downloader):
            total_bytes = downloader.get_total_bytes()
            bytes_left_to_download = downloader.get_bytes_left_to_download()
            bytes_left_to_output = downloader.get_bytes_left_to_output()
            points_paid = payment_rate_manager.points_paid
            payment_rate = payment_rate_manager.get_effective_min_blob_data_payment_rate()
            points_remaining = 1.0 * bytes_left_to_download * payment_rate / 2**20
            stream_frame.show_progress(total_bytes, bytes_left_to_download, bytes_left_to_output,
                                       points_paid, points_remaining)

        def show_finished(arg, downloader):
            show_stream_status(downloader)
            stream_frame.show_download_done(payment_rate_manager.points_paid)
            return arg

        def start_download(downloader):
            l = task.LoopingCall(show_stream_status, downloader)
            l.start(1)
            d = downloader.start()
            stream_frame.cancel_func = downloader.stop

            def stop_looping_call(arg):
                l.stop()
                stream_frame.cancel_func = resolve_d.cancel
                return arg

            d.addBoth(stop_looping_call)
            d.addCallback(show_finished, downloader)
            return d

        def lookup_failed(err):
            stream_frame.show_metadata_status("name lookup failed")
            return err

        def bad_sd_blob(err):
            stream_frame.show_metadata_status("Unknown type or badly formed metadata")
            return err

        resolve_d.addCallback(update_stream_name)
        resolve_d.addCallback(get_sd_hash)
        resolve_d.addCallbacks(get_sd_blob, lookup_failed)

        def show_err(err):
            tkMessageBox.showerror(title="Download Error", message=err.getErrorMessage())
            logging.error(err.getErrorMessage())
            stream_frame.show_download_done(payment_rate_manager.points_paid)

        resolve_d.addErrback(lambda err: err.trap(defer.CancelledError))
        resolve_d.addErrback(show_err)
        self._add_download_deferred(resolve_d, stream_frame)

    def _add_download_deferred(self, d, stream_frame):
        self.download_deferreds.append(d)
        self.stream_frames.append(stream_frame)

        def remove_from_list():
            self.download_deferreds.remove(d)
            self.stream_frames.remove(stream_frame)

        d.addBoth(lambda _: remove_from_list())