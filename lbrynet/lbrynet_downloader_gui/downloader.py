import Tkinter as tk
import ttk
import tkFont
import tkMessageBox
import logging
from lbrynet.lbryfile.client.LBRYFileDownloader import LBRYFileSaverFactory, LBRYFileOpenerFactory
from twisted.internet import tksupport, reactor, defer, task, threads
import sys
import os
import locale
import binascii
from Crypto import Random
from lbrynet.conf import MIN_BLOB_DATA_PAYMENT_RATE
from lbrynet.core.Session import LBRYSession
from lbrynet.core.LBRYcrdWallet import LBRYcrdWallet
from lbrynet.core.StreamDescriptor import StreamDescriptorIdentifier
from lbrynet.core.PaymentRateManager import PaymentRateManager
from lbrynet.lbryfile.LBRYFileMetadataManager import TempLBRYFileMetadataManager
from lbrynet.core import StreamDescriptor
from lbrynet.lbryfile.StreamDescriptor import LBRYFileStreamType, LBRYFileStreamDescriptorValidator
import requests


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
                                   known_dht_nodes=self.known_dht_nodes, dht_node_port=4446)
        return self.session.setup()

    def _setup_stream_info_manager(self):
        self.stream_info_manager = TempLBRYFileMetadataManager()
        return defer.succeed(True)

    def _setup_stream_identifier(self):
        self.sd_identifier.add_stream_info_validator(LBRYFileStreamType, LBRYFileStreamDescriptorValidator)
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
            info_validator, factories = info_and_factories
            stream_name, stream_size = get_info_from_validator(info_validator)
            if isinstance(stream_size, (int, long)):
                price = payment_rate_manager.get_effective_min_blob_data_payment_rate()
                estimated_cost = stream_size * 1.0 / 2**20 * price
            else:
                estimated_cost = "unknown"

            stream_frame.show_stream_metadata(stream_name, stream_size, estimated_cost)

            get_downloader_d = defer.Deferred()

            def create_downloader(f):

                def fire_get_downloader_d(downloader):
                    if not get_downloader_d.called:
                        get_downloader_d.callback(downloader)

                stream_frame.disable_download_buttons()
                download_options = [o.default for o in f.get_downloader_options(info_validator, payment_rate_manager)]
                d = f.make_downloader(info_validator, download_options,
                                      payment_rate_manager)
                d.addCallback(fire_get_downloader_d)

            for factory in factories:

                def choose_factory(f=factory):
                    create_downloader(f)

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


class StreamFrame(object):
    def __init__(self, app, uri):
        self.app = app
        self.uri = uri
        self.cancel_func = None

        self.stream_frame = ttk.Frame(self.app.streams_frame, style="B.TFrame")

        self.stream_frame.pack(fill=tk.X, side=tk.BOTTOM, pady=(30, 0))

        self.stream_frame_header = ttk.Frame(self.stream_frame, style="C.TFrame")
        self.stream_frame_header.grid(sticky=tk.E + tk.W)

        self.uri_font = tkFont.Font(size=8)
        self.uri_label = ttk.Label(
            self.stream_frame_header, text=self.uri, font=self.uri_font, foreground="#666666"
        )
        self.uri_label.grid(row=0, column=0, sticky=tk.W)

        if os.name == "nt":
            close_cursor = ""
        else:
            close_cursor = "hand1"
        
        close_file_name = "close2.gif"
        try:
            close_file = os.path.join(os.path.dirname(__file__), close_file_name)
        except NameError:
            close_file = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "lbrynet",
                                      "lbrynet_downloader_gui", close_file_name)

        self.close_picture = tk.PhotoImage(
            file=close_file
        )
        self.close_button = ttk.Button(
            self.stream_frame_header, command=self.cancel, style="Stop.TButton", cursor=close_cursor
        )
        self.close_button.config(image=self.close_picture)
        self.close_button.grid(row=0, column=1, sticky=tk.E + tk.N)

        self.stream_frame_header.grid_columnconfigure(0, weight=1)

        self.stream_frame.grid_columnconfigure(0, weight=1)

        self.stream_frame_body = ttk.Frame(self.stream_frame, style="C.TFrame")
        self.stream_frame_body.grid(row=1, column=0, sticky=tk.E + tk.W)

        self.name_frame = ttk.Frame(self.stream_frame_body, style="D.TFrame")
        self.name_frame.grid(sticky=tk.W + tk.E)
        self.name_frame.grid_columnconfigure(0, weight=1)

        self.stream_frame_body.grid_columnconfigure(0, weight=1)

        self.info_frame = ttk.Frame(self.stream_frame_body, style="D.TFrame")
        self.info_frame.grid(sticky=tk.W + tk.E, row=1)
        self.info_frame.grid_columnconfigure(0, weight=1)

        self.metadata_frame = ttk.Frame(self.info_frame, style="E.TFrame")
        self.metadata_frame.grid(sticky=tk.W + tk.E)
        self.metadata_frame.grid_columnconfigure(0, weight=1)

        self.outer_button_frame = ttk.Frame(self.stream_frame_body, style="D.TFrame")
        self.outer_button_frame.grid(sticky=tk.W + tk.E, row=2)

        self.button_frame = ttk.Frame(self.outer_button_frame, style="E.TFrame")
        self.button_frame.pack(side=tk.TOP)

        self.status_label = None
        self.name_label = None
        self.bytes_downloaded_label = None
        self.bytes_outputted_label = None

        self.download_buttons = []
        self.name_font = None
        self.description_label = None
        self.file_name_frame = None
        self.cost_frame = None
        self.cost_description = None
        self.remaining_cost_description = None
        self.cost_label = None
        self.remaining_cost_label = None

    def cancel(self):
        if self.cancel_func is not None:
            self.cancel_func()
        self.stream_frame.destroy()
        self.app.stream_removed()

    def show_name(self, name):
        self.name_font = tkFont.Font(size=16)
        self.name_label = ttk.Label(
            self.name_frame, text=name, font=self.name_font
        )
        self.name_label.grid(row=0, column=0, sticky=tk.W)

    def show_description(self, description):
        if os.name == "nt":
            wraplength = 580
        else:
            wraplength = 600
        self.description_label = ttk.Label(
            self.name_frame, text=description, wraplength=wraplength
        )
        self.description_label.grid(row=1, column=0, sticky=tk.W)

    def show_metadata_status(self, value):
        if self.status_label is None:
            self.status_label = ttk.Label(
                self.metadata_frame, text=value
            )
            self.status_label.grid()
            self.metadata_frame.grid_columnconfigure(0, weight=1)
        else:
            self.status_label.config(text=value)

    @staticmethod
    def get_formatted_stream_size(stream_size):
        if isinstance(stream_size, (int, long)):
            if stream_size >= 2**40:
                units = "TB"
                factor = 2**40
            elif stream_size >= 2**30:
                units = "GB"
                factor = 2**30
            elif stream_size >= 2**20:
                units = "MB"
                factor = 2**20
            elif stream_size >= 2**10:
                units = "KB"
                factor = 2**10
            else:
                return str(stream_size) + " B"
            return "%.1f %s" % (round((stream_size * 1.0 / factor), 1), units)
        return stream_size

    def show_stream_metadata(self, stream_name, stream_size, estimated_cost):
        if self.status_label is not None:
            self.status_label.destroy()

        self.file_name_frame = ttk.Frame(self.metadata_frame, style="F.TFrame")
        self.file_name_frame.grid(row=0, column=0, sticky=tk.W)
        self.metadata_frame.grid_columnconfigure(0, weight=1, uniform="metadata")

        file_size_label = ttk.Label(
            self.file_name_frame,
            text=self.get_formatted_stream_size(stream_size)
        )
        file_size_label.grid(row=0, column=2)

        file_name_label = ttk.Label(
            self.file_name_frame,
            text=" - " + stream_name,
        )
        file_name_label.grid(row=0, column=3)

        self.outer_button_frame = ttk.Frame(self.stream_frame_body, style="D.TFrame")
        self.outer_button_frame.grid(sticky=tk.W + tk.E, row=2)

        self.cost_frame = ttk.Frame(self.outer_button_frame, style="F.TFrame")
        self.cost_frame.grid(row=0, column=0, sticky=tk.W+tk.N, pady=(0, 12))

        self.cost_label = ttk.Label(
            self.cost_frame,
            text=locale.format_string("%.2f LBC", (round(estimated_cost, 2),), grouping=True),
            foreground="red"
        )
        self.cost_label.grid(row=0, column=1, padx=(1, 0))

        self.button_frame = ttk.Frame(self.outer_button_frame, style="E.TFrame")
        self.button_frame.grid(row=0, column=1)

        self.outer_button_frame.grid_columnconfigure(0, weight=1, uniform="buttons")
        self.outer_button_frame.grid_columnconfigure(1, weight=2, uniform="buttons1")
        self.outer_button_frame.grid_columnconfigure(2, weight=1, uniform="buttons")

    def add_download_factory(self, factory, download_func):
        if os.name == "nt":
            button_cursor = ""
        else:
            button_cursor = "hand1"
        download_button = ttk.Button(
            self.button_frame, text=factory.get_description(), command=download_func,
            style='LBRY.TButton', cursor=button_cursor
        )
        self.download_buttons.append(download_button)
        download_button.grid(row=0, column=len(self.download_buttons) - 1, padx=5, pady=(1, 2))

    def disable_download_buttons(self):
        for download_button in self.download_buttons:
            download_button.config(state=tk.DISABLED)

    def remove_download_buttons(self):
        for download_button in self.download_buttons:
            download_button.destroy()
        self.download_buttons = []

    def show_progress(self, total_bytes, bytes_left_to_download, bytes_left_to_output, points_paid,
                      points_remaining):
        if self.bytes_outputted_label is None:
            self.remove_download_buttons()
            self.button_frame.destroy()
            self.outer_button_frame.grid_columnconfigure(2, weight=0, uniform="")

            self.bytes_outputted_label = ttk.Label(
                self.file_name_frame,
                text=""
            )
            self.bytes_outputted_label.grid(row=0, column=0)

            self.bytes_downloaded_label = ttk.Label(
                self.file_name_frame,
                text=""
            )
            self.bytes_downloaded_label.grid(row=0, column=1)

        if self.bytes_outputted_label.winfo_exists():
            self.bytes_outputted_label.config(
                text=self.get_formatted_stream_size(total_bytes - bytes_left_to_output) + " / "
            )
        if self.bytes_downloaded_label.winfo_exists():
            self.bytes_downloaded_label.config(
                text=self.get_formatted_stream_size(total_bytes - bytes_left_to_download) + " / "
            )
        if self.cost_label.winfo_exists():
            total_points = points_remaining + points_paid
            self.cost_label.config(text=locale.format_string("%.2f/%.2f LBC",
                                                             (round(points_paid, 2), round(total_points, 2)),
                                                             grouping=True))

    def show_download_done(self, total_points_paid):
        if self.bytes_outputted_label is not None and self.bytes_outputted_label.winfo_exists():
            self.bytes_outputted_label.destroy()
        if self.bytes_downloaded_label is not None and self.bytes_downloaded_label.winfo_exists():
            self.bytes_downloaded_label.destroy()
        if self.cost_label is not None and self.cost_label.winfo_exists():
            self.cost_label.config(text=locale.format_string("%.2f LBC",
                                                             (round(total_points_paid, 2),),
                                                             grouping=True))


class AddressWindow(object):
    def __init__(self, root, address):
        self.root = root
        self.address = address

    def show(self):
        window = tk.Toplevel(self.root, background="#FFFFFF")
        window.transient(self.root)
        window.wm_title("New address")
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        window.resizable(0, 0)

        text_box = tk.Text(window, width=35, height=1, relief=tk.FLAT, borderwidth=0,
                           highlightthickness=0)
        text_box.insert(tk.END, self.address)
        text_box.grid(row=0, padx=10, pady=5, columnspan=2)
        text_box.config(state='normal')

        def copy_to_clipboard():
            self.root.clipboard_clear()
            self.root.clipboard_append(text_box.get('1.0', 'end-1c'))

        def copy_command():
            text_box.event_generate("<Control-c>")

        copy_menu = tk.Menu(
            self.root, tearoff=0
        )
        copy_menu.add_command(label="    Copy   ", command=copy_command)

        def popup(event):
            if text_box.tag_ranges("sel"):
                copy_menu.tk_popup(event.x_root, event.y_root)

        text_box.bind("<Button-3>", popup)

        copy_button = ttk.Button(
            window, text="Copy", command=copy_to_clipboard, style="LBRY.TButton"
        )
        copy_button.grid(row=1, column=0, pady=(0, 5), padx=5, sticky=tk.E)

        done_button = ttk.Button(
            window, text="OK", command=window.destroy, style="LBRY.TButton"
        )
        done_button.grid(row=1, column=1, pady=(0, 5), padx=5, sticky=tk.W)
        window.focus_set()


class WelcomeWindow(object):
    def __init__(self, root, points_sent):
        self.root = root
        self.points_sent = points_sent

    def show(self):
        window = tk.Toplevel(self.root, background="#FFFFFF")
        window.transient(self.root)
        window.wm_title("Welcome to LBRY")
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        window.resizable(0, 0)

        text_box = tk.Text(window, width=45, height=3, relief=tk.FLAT, borderwidth=0,
                           highlightthickness=0)

        points_string = locale.format_string("%.2f LBC", (round(self.points_sent, 2),),
                                             grouping=True)

        text_box.insert(tk.END, "Thank you for using LBRY! You have been\n"
                                "given %s for free because we love\n"
                                "you. Please give them 60 seconds to show up." % points_string)
        text_box.grid(row=0, padx=10, pady=5, columnspan=2)
        text_box.config(state='normal')

        window.focus_set()


class App(object):
    def __init__(self):
        self.master = None
        self.downloader = None
        self.wallet_balance_check = None
        self.streams_frame = None

    def start(self):

        d = defer.maybeDeferred(self._start_root)
        d.addCallback(lambda _: self._draw_main())
        d.addCallback(lambda _: self._start_downloader())
        d.addCallback(lambda _: self._start_checking_wallet_balance())
        d.addCallback(lambda _: self._enable_lookup())

        def show_error_and_stop(err):
            logging.error(err.getErrorMessage())
            tkMessageBox.showerror(title="Start Error", message=err.getErrorMessage())
            return self.stop()

        d.addErrback(show_error_and_stop)
        return d

    def stop(self):

        def log_error(err):
            logging.error(err.getErrorMessage())

        if self.downloader is not None:
            d = self.downloader.stop()
        else:
            d = defer.succeed(True)
        d.addErrback(log_error)
        d.addCallback(lambda _: self._stop_checking_wallet_balance())
        d.addErrback(log_error)
        d.addCallback(lambda _: reactor.stop())
        d.addErrback(log_error)
        return d

    def _start_root(self):
        if os.name == "nt":
            button_foreground = "#104639"
            lookup_button_padding = 10
        else:
            button_foreground = "#FFFFFF"
            lookup_button_padding = 11
    
        root = tk.Tk()
        root.resizable(0, 0)
        root.wm_title("LBRY")

        tksupport.install(root)

        if os.name == "nt":
            root.iconbitmap(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])),
                                         "lbrynet", "lbrynet_downloader_gui", "lbry-dark-icon.ico"))
        else:
            root.wm_iconbitmap("@" + os.path.join(os.path.dirname(__file__), "lbry-dark-icon.xbm"))

        root.button_font = tkFont.Font(size=9)

        ttk.Style().configure(".", background="#FFFFFF")
        ttk.Style().configure("LBRY.TButton", background="#104639", foreground=button_foreground,
                              borderwidth=1, relief="solid", font=root.button_font)
        ttk.Style().map("LBRY.TButton",
                        background=[('pressed', "#104639"),
                                    ('active', "#104639")])
        #ttk.Style().configure("LBRY.TButton.border", background="#808080")
        ttk.Style().configure("Lookup.LBRY.TButton", padding=lookup_button_padding)
        ttk.Style().configure("Stop.TButton", padding=1, background="#FFFFFF", relief="flat", borderwidth=0)
        ttk.Style().configure("TEntry", padding=11)
        #ttk.Style().configure("A.TFrame", background="red")
        #ttk.Style().configure("B.TFrame", background="green")
        #ttk.Style().configure("B2.TFrame", background="#80FF80")
        #ttk.Style().configure("C.TFrame", background="orange")
        #ttk.Style().configure("D.TFrame", background="blue")
        #ttk.Style().configure("E.TFrame", background="yellow")
        #ttk.Style().configure("F.TFrame", background="#808080")
        #ttk.Style().configure("LBRY.TProgressbar", background="#104639", orient="horizontal", thickness=5)
        #ttk.Style().configure("LBRY.TProgressbar")
        #ttk.Style().layout("Horizontal.LBRY.TProgressbar", ttk.Style().layout("Horizontal.TProgressbar"))
        
        root.configure(background="#FFFFFF")

        root.protocol("WM_DELETE_WINDOW", self.stop)

        self.master = root

    def _draw_main(self):
        self.frame = ttk.Frame(self.master, style="A.TFrame")
        self.frame.grid(padx=20, pady=20)

        logo_file_name = "lbry-dark-242x80.gif"
        try:
            logo_file = os.path.join(os.path.dirname(__file__), logo_file_name)
        except NameError:
            logo_file = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "lbrynet",
                                     "lbrynet_downloader_gui", logo_file_name)

        self.logo_picture = tk.PhotoImage(file=logo_file)

        self.logo_frame = ttk.Frame(self.frame, style="B.TFrame")
        self.logo_frame.grid(pady=5, sticky=tk.W + tk.E)

        self.dummy_frame = ttk.Frame(self.logo_frame, style="C.TFrame")  # keeps the logo in the middle
        self.dummy_frame.grid(row=0, column=1, padx=5)

        self.logo_label = ttk.Label(self.logo_frame, image=self.logo_picture)
        self.logo_label.grid(row=0, column=1, padx=5)

        self.wallet_balance_frame = ttk.Frame(self.logo_frame, style="C.TFrame")
        self.wallet_balance_frame.grid(sticky=tk.E + tk.N, row=0, column=2)

        self.logo_frame.grid_columnconfigure(0, weight=1, uniform="a")
        self.logo_frame.grid_columnconfigure(1, weight=2, uniform="b")
        self.logo_frame.grid_columnconfigure(2, weight=1, uniform="a")

        self.wallet_balance = ttk.Label(
            self.wallet_balance_frame,
            text=" -- LBC"
        )
        self.wallet_balance.grid(row=0, column=0)

        dropdown_file_name = "drop_down.gif"
        try:
            dropdown_file = os.path.join(os.path.dirname(__file__), dropdown_file_name)
        except NameError:
            dropdown_file = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "lbrynet",
                                         "lbrynet_downloader_gui", dropdown_file_name)

        self.dropdown_picture = tk.PhotoImage(
            file=dropdown_file
        )

        def get_new_address():
            def show_address(address):
                w = AddressWindow(self.master, address)
                w.show()
            d = defer.maybeDeferred(self.downloader.get_new_address)
            d.addCallback(show_address)

            def show_error(err):
                tkMessageBox.showerror(title="Failed to get new address", message=err.getErrorMessage())

            d.addErrback(show_error)

        self.wallet_menu = tk.Menu(
            self.master, tearoff=0
        )
        self.wallet_menu.add_command(label="Get new LBRYcrd address", command=get_new_address)

        if os.name == "nt":
            button_cursor = ""
        else:
            button_cursor = "hand1"

        self.wallet_menu_button = ttk.Button(self.wallet_balance_frame, image=self.dropdown_picture,
                                             style="Stop.TButton", cursor=button_cursor)
        self.wallet_menu_button.grid(row=0, column=1, padx=(5, 0))

        def popup(event):
            self.wallet_menu.tk_popup(event.x_root, event.y_root)

        self.wallet_menu_button.bind("<Button-1>", popup)

        self.uri_frame = ttk.Frame(self.frame, style="B.TFrame")
        self.uri_frame.grid()

        self.uri_label = ttk.Label(
            self.uri_frame, text="lbry://"
        )
        self.uri_label.grid(row=0, column=0, sticky=tk.E, pady=2)

        self.entry_font = tkFont.Font(size=11)

        self.uri_entry = ttk.Entry(self.uri_frame, width=50, foreground="#222222", font=self.entry_font)
        self.uri_entry.grid(row=0, column=1, padx=2, pady=2)

        def copy_command():
            self.uri_entry.event_generate('<Control-c>')

        def cut_command():
            self.uri_entry.event_generate('<Control-x>')

        def paste_command():
            self.uri_entry.event_generate('<Control-v>')

        def popup(event):
            selection_menu = tk.Menu(
                self.master, tearoff=0
            )
            if self.uri_entry.selection_present():
                selection_menu.add_command(label="    Cut    ", command=cut_command)
                selection_menu.add_command(label="    Copy   ", command=copy_command)
            selection_menu.add_command(label="    Paste  ", command=paste_command)
            selection_menu.tk_popup(event.x_root, event.y_root)

        self.uri_entry.bind("<Button-3>", popup)

        self.uri_button = ttk.Button(
            self.uri_frame, text="Go", command=self._open_stream,
            style='Lookup.LBRY.TButton', cursor=button_cursor
        )
        self.uri_button.grid(row=0, column=2, pady=2, padx=0)

    def _start_downloader(self):
        self.downloader = LBRYDownloader()
        d = self.downloader.start()
        d.addCallback(lambda _: self.downloader.do_first_run())
        d.addCallback(self._show_welcome_message)
        return d

    def _show_welcome_message(self, points_sent):
        if points_sent != 0.0:
            w = WelcomeWindow(self.master, points_sent)
            w.show()

    def stream_removed(self):
        if self.streams_frame is not None:
            if len(self.streams_frame.winfo_children()) == 0:
                self.streams_frame.destroy()
                self.streams_frame = None

    def _start_checking_wallet_balance(self):

        def set_balance(balance):
            self.wallet_balance.configure(text=locale.format_string("%.2f LBC", (round(balance, 2),),
                                                                    grouping=True))

        def update_balance():
            balance = self.downloader.session.wallet.get_available_balance()
            set_balance(balance)

        def start_looping_call():
            self.wallet_balance_check = task.LoopingCall(update_balance)
            self.wallet_balance_check.start(5)

        d = self.downloader.session.wallet.get_balance()
        d.addCallback(set_balance)
        d.addCallback(lambda _: start_looping_call())

    def _stop_checking_wallet_balance(self):
        if self.wallet_balance_check is not None:
            self.wallet_balance_check.stop()

    def _enable_lookup(self):
        self.uri_entry.bind('<Return>', self._open_stream)

    def _open_stream(self, event=None):
        if self.streams_frame is None:
            self.streams_frame = ttk.Frame(self.frame, style="B2.TFrame")
            self.streams_frame.grid(sticky=tk.E + tk.W)
        uri = self.uri_entry.get()
        self.uri_entry.delete(0, tk.END)
        stream_frame = StreamFrame(self, "lbry://" + uri)

        self.downloader.download_stream(stream_frame, uri)


def start_downloader():

    log_format = "(%(asctime)s)[%(filename)s:%(lineno)s] %(funcName)s(): %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=log_format, filename="downloader.log")
    sys.stdout = open("downloader.out.log", 'w')
    sys.stderr = open("downloader.err.log", 'w')

    locale.setlocale(locale.LC_ALL, '')

    app = App()

    d = task.deferLater(reactor, 0, app.start)

    reactor.run()

if __name__ == "__main__":
    start_downloader()