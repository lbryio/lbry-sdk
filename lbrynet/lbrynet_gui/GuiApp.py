import Tkinter as tk
import logging
import sys
import tkFont
import tkMessageBox
import ttk
from lbrynet.lbrynet_gui.LBRYGui import LBRYDownloader
from lbrynet.lbrynet_gui.StreamFrame import StreamFrame
import locale
import os
from twisted.internet import defer, reactor, tksupport, task


log = logging.getLogger(__name__)


class DownloaderApp(object):
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
            log.error(err.getErrorMessage())
            tkMessageBox.showerror(title="Start Error", message=err.getErrorMessage())
            return self.stop()

        d.addErrback(show_error_and_stop)
        return d

    def stop(self):

        def log_error(err):
            log.error(err.getErrorMessage())

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
                                         "lbry-dark-icon.ico"))
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
        ttk.Style().configure("Float.TEntry", padding=2)
        #ttk.Style().configure("A.TFrame", background="red")
        #ttk.Style().configure("B.TFrame", background="green")
        #ttk.Style().configure("B2.TFrame", background="#80FF80")
        #ttk.Style().configure("C.TFrame", background="orange")
        #ttk.Style().configure("D.TFrame", background="blue")
        #ttk.Style().configure("E.TFrame", background="yellow")
        #ttk.Style().configure("F.TFrame", background="#808080")
        #ttk.Style().configure("G.TFrame", background="#FF80FF")
        #ttk.Style().configure("H.TFrame", background="#0080FF")
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
        if os.name == "nt":
            logo_file = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), logo_file_name)
        else:
            logo_file = os.path.join(os.path.dirname(__file__), logo_file_name)

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
        if os.name == "nt":
            dropdown_file = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])),
                                         dropdown_file_name)
        else:
            dropdown_file = os.path.join(os.path.dirname(__file__), dropdown_file_name)

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

        def popup_wallet(event):
            self.wallet_menu.tk_popup(event.x_root, event.y_root)

        self.wallet_menu_button.bind("<Button-1>", popup_wallet)

        self.uri_frame = ttk.Frame(self.frame, style="B.TFrame")
        self.uri_frame.grid()

        self.uri_label = ttk.Label(
            self.uri_frame, text="lbry://"
        )
        self.uri_label.grid(row=0, column=0, sticky=tk.E, pady=2)

        self.entry_font = tkFont.Font(size=11)

        self.uri_entry = ttk.Entry(self.uri_frame, width=50, foreground="#222222", font=self.entry_font,
                                   state=tk.DISABLED)
        self.uri_entry.grid(row=0, column=1, padx=2, pady=2)

        def copy_command():
            self.uri_entry.event_generate('<Control-c>')

        def cut_command():
            self.uri_entry.event_generate('<Control-x>')

        def paste_command():
            self.uri_entry.event_generate('<Control-v>')

        def popup_uri(event):
            selection_menu = tk.Menu(
                self.master, tearoff=0
            )
            if self.uri_entry.selection_present():
                selection_menu.add_command(label="    Cut    ", command=cut_command)
                selection_menu.add_command(label="    Copy   ", command=copy_command)
            selection_menu.add_command(label="    Paste  ", command=paste_command)
            selection_menu.tk_popup(event.x_root, event.y_root)

        self.uri_entry.bind("<Button-3>", popup_uri)

        self.uri_button = ttk.Button(
            self.uri_frame, text="Go", command=self._open_stream,
            style='Lookup.LBRY.TButton', cursor=button_cursor
        )
        self.uri_button.grid(row=0, column=2, pady=2, padx=0)

    def _start_downloader(self):
        self.downloader = LBRYDownloader()
        d = self.downloader.start()
        d.addCallback(lambda _: self.downloader.check_first_run())
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
        self.uri_entry.config(state=tk.NORMAL)

    def _open_stream(self, event=None):
        if self.streams_frame is None:
            self.streams_frame = ttk.Frame(self.frame, style="B2.TFrame")
            self.streams_frame.grid(sticky=tk.E + tk.W)
        uri = self.uri_entry.get()
        self.uri_entry.delete(0, tk.END)
        stream_frame = StreamFrame(self, "lbry://" + uri)

        self.downloader.download_stream(stream_frame, uri)


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
