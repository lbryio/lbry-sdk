import Tkinter as tk
import sys
import tkFont
import ttk
import locale
import os


class StreamFrame(object):
    def __init__(self, app, uri):
        self.app = app
        self.uri = uri
        self.stream_hash = None
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
            self.button_cursor = ""
        else:
            self.button_cursor = "hand1"

        close_file_name = "close2.gif"
        if os.name == "nt":
            close_file = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "lbrynet",
                                      "lbrynet_downloader_gui", close_file_name)
        else:
            close_file = os.path.join(os.path.dirname(__file__), close_file_name)

        self.close_picture = tk.PhotoImage(
            file=close_file
        )
        self.close_button = ttk.Button(
            self.stream_frame_header, command=self.cancel, style="Stop.TButton", cursor=self.button_cursor
        )
        self.close_button.config(image=self.close_picture)
        self.close_button.grid(row=0, column=1, sticky=tk.E + tk.N)

        self.stream_frame_header.grid_columnconfigure(0, weight=1)

        self.stream_frame.grid_columnconfigure(0, weight=1)

        self.stream_frame_body = ttk.Frame(self.stream_frame, style="C.TFrame")
        self.stream_frame_body.grid(row=1, column=0, sticky=tk.E + tk.W)

        self.name_frame = ttk.Frame(self.stream_frame_body, style="D.TFrame")
        self.name_frame.grid(sticky=tk.W + tk.E)
        self.name_frame.grid_columnconfigure(0, weight=16)
        self.name_frame.grid_columnconfigure(1, weight=1)

        self.stream_frame_body.grid_columnconfigure(0, weight=1)

        self.metadata_frame = ttk.Frame(self.stream_frame_body, style="D.TFrame")
        self.metadata_frame.grid(sticky=tk.W + tk.E, row=1)
        self.metadata_frame.grid_columnconfigure(0, weight=1)

        self.options_frame = ttk.Frame(self.stream_frame_body, style="D.TFrame")

        self.outer_button_frame = ttk.Frame(self.stream_frame_body, style="D.TFrame")
        self.outer_button_frame.grid(sticky=tk.W + tk.E, row=4)

        #show_options_picture_file_name = "show_options.gif"
        #if os.name == "nt":
        #    show_options_picture_file = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])),
        #                                             "lbrynet", "lbrynet_downloader_gui",
        #                                             show_options_picture_file_name)
        #else:
        #    show_options_picture_file = os.path.join(os.path.dirname(__file__),
        #                                             show_options_picture_file_name)

        #self.show_options_picture = tk.PhotoImage(
        #    file=show_options_picture_file
        #)

        #hide_options_picture_file_name = "hide_options.gif"
        #if os.name == "nt":
        #    hide_options_picture_file = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])),
        #                                             "lbrynet", "lbrynet_downloader_gui",
        #                                             hide_options_picture_file_name)
        #else:
        #    hide_options_picture_file = os.path.join(os.path.dirname(__file__),
        #                                             hide_options_picture_file_name)

        #self.hide_options_picture = tk.PhotoImage(
        #    file=hide_options_picture_file
        #)

        #self.show_options_button = None

        self.status_label = None
        #self.name_label = None
        self.name_text = None
        self.estimated_cost_frame = None
        self.bytes_downloaded_label = None
        self.button_frame = None
        self.download_buttons = []
        self.option_frames = []
        self.name_font = None
        self.description_text = None
        #self.description_label = None
        self.file_name_frame = None
        self.cost_frame = None
        self.cost_description = None
        self.remaining_cost_description = None
        self.cost_label = None
        self.remaining_cost_label = None
        self.progress_frame = None

    def cancel(self):
        if self.cancel_func is not None:
            self.cancel_func()
        self.stream_frame.destroy()
        self.app.stream_removed()

    def _resize_text(self, text_widget):
        actual_height = text_widget.tk.call(text_widget._w, "count", "-displaylines", "0.0", "end")
        text_widget.config(height=int(actual_height))

    def show_name(self, name):
        self.name_font = tkFont.Font(size=16)
        #self.name_label = ttk.Label(
        #    self.name_frame, text=name, font=self.name_font
        #)
        #self.name_label.grid(row=0, column=0, sticky=tk.W)
        self.name_text = tk.Text(
            self.name_frame, font=self.name_font, wrap=tk.WORD, relief=tk.FLAT, borderwidth=0,
            highlightthickness=0, width=1, height=1
        )
        self.name_text.insert(tk.INSERT, name)
        self.name_text.config(state=tk.DISABLED)
        self.name_text.grid(row=0, column=0, sticky=tk.W+tk.E+tk.N+tk.S)
        self.name_text.update()
        self._resize_text(self.name_text)

    def show_description(self, description):
        #if os.name == "nt":
        #    wraplength = 580
        #else:
        #    wraplength = 600
        #self.description_label = ttk.Label(
        #    self.name_frame, text=description, wraplength=wraplength
        #)
        #self.description_label.grid(row=1, column=0, sticky=tk.W)
        self.description_text = tk.Text(
            self.name_frame, wrap=tk.WORD, relief=tk.FLAT, borderwidth=0,
            highlightthickness=0, width=1, height=1
        )
        self.description_text.insert(tk.INSERT, description)
        self.description_text.config(state=tk.DISABLED)
        self.description_text.grid(row=1, column=0, sticky=tk.W+tk.E+tk.N+tk.S)
        self.description_text.update()
        self._resize_text(self.description_text)

    def show_thumbnail(self, url=None):
        thumbnail = None
        if url is not None:
            import urllib2
            import base64
            response = urllib2.urlopen(url)
            thumbnail_data = base64.b64encode(response.read())
            thumbnail = tk.PhotoImage(data=thumbnail_data)
            current_width = thumbnail.width()
            current_height = thumbnail.height()
            max_width = 130
            max_height = 90
            scale_ratio = max(1.0 * current_width / max_width, 1.0 * current_height / max_height)
            if scale_ratio < 1:
                scale_ratio = 1
            else:
                scale_ratio = int(scale_ratio + 1)
            thumbnail = thumbnail.subsample(scale_ratio)
        if thumbnail is not None:
            label = ttk.Label(self.name_frame, image=thumbnail)
            label.safekeeping = thumbnail
            label.grid(row=0, column=1, rowspan=2, sticky=tk.E+tk.N+tk.W+tk.S)
            label.update()
            self.description_text.update()
            self.name_text.update()
            self._resize_text(self.description_text)
            self._resize_text(self.name_text)

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

    def show_stream_metadata(self, stream_name, stream_size, stream_cost):
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

        self.estimated_cost_frame = ttk.Frame(self.metadata_frame, style="F.TFrame")
        self.estimated_cost_frame.grid(row=1, column=0, sticky=tk.W)

        estimated_cost_label = ttk.Label(
            self.estimated_cost_frame,
            text=locale.format_string("%.2f LBC",
                                      (round(stream_cost, 2)), grouping=True),
            foreground="red"
        )
        estimated_cost_label.grid(row=1, column=2)

        self.button_frame = ttk.Frame(self.outer_button_frame, style="E.TFrame")
        self.button_frame.grid(row=0, column=1)

        self.outer_button_frame.grid_columnconfigure(0, weight=1, uniform="buttons")
        self.outer_button_frame.grid_columnconfigure(1, weight=2, uniform="buttons1")
        self.outer_button_frame.grid_columnconfigure(2, weight=1, uniform="buttons")

    def add_download_factory(self, factory, download_func):
        download_button = ttk.Button(
            self.button_frame, text=factory.get_description(), command=download_func,
            style='LBRY.TButton', cursor=self.button_cursor
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

    def get_option_widget(self, option_type, option_frame):
        if option_type.value == float:
            entry_frame = ttk.Frame(
                option_frame,
                style="H.TFrame"
            )
            entry_frame.grid()
            col = 0
            if option_type.short_description is not None:
                entry_label = ttk.Label(
                    entry_frame,
                    #text=option_type.short_description
                    text=""
                )
                entry_label.grid(row=0, column=0, sticky=tk.W)
                col = 1
            entry = ttk.Entry(
                entry_frame,
                width=10,
                style="Float.TEntry"
            )
            entry_frame.entry = entry
            entry.grid(row=0, column=col, sticky=tk.W)
            return entry_frame
        if option_type.value == bool:
            bool_frame = ttk.Frame(
                option_frame,
                style="H.TFrame"
            )
            bool_frame.chosen_value = tk.BooleanVar()
            true_text = "True"
            false_text = "False"
            if option_type.bool_options_description is not None:
                true_text, false_text = option_type.bool_options_description
            true_radio_button = ttk.Radiobutton(
                bool_frame, text=true_text, variable=bool_frame.chosen_value, value=True
            )
            true_radio_button.grid(row=0, sticky=tk.W)
            false_radio_button = ttk.Radiobutton(
                bool_frame, text=false_text, variable=bool_frame.chosen_value, value=False
            )
            false_radio_button.grid(row=1, sticky=tk.W)
            return bool_frame
        label = ttk.Label(
            option_frame,
            text=""
        )
        return label

    def show_download_options(self, options):
        left_padding = 20
        for option in options:
            f = ttk.Frame(
                self.options_frame,
                style="E.TFrame"
            )
            f.grid(sticky=tk.W + tk.E, padx=left_padding)
            self.option_frames.append((option, f))
            description_label = ttk.Label(
                f,
                text=option.long_description
            )
            description_label.grid(row=0, sticky=tk.W)
            if len(option.option_types) > 1:
                f.chosen_type = tk.IntVar()
                choices_frame = ttk.Frame(
                    f,
                    style="F.TFrame"
                )
                f.choices_frame = choices_frame
                choices_frame.grid(row=1, sticky=tk.W, padx=left_padding)
                choices_frame.choices = []
                for i, option_type in enumerate(option.option_types):
                    choice_frame = ttk.Frame(
                        choices_frame,
                        style="G.TFrame"
                    )
                    choice_frame.grid(sticky=tk.W)
                    option_text = ""
                    if option_type.short_description is not None:
                        option_text = option_type.short_description
                    option_radio_button = ttk.Radiobutton(
                        choice_frame, text=option_text, variable=f.chosen_type, value=i
                    )
                    option_radio_button.grid(row=0, column=0, sticky=tk.W)
                    option_widget = self.get_option_widget(option_type, choice_frame)
                    option_widget.grid(row=0, column=1, sticky=tk.W)
                    choices_frame.choices.append(option_widget)
                    if i == 0:
                        option_radio_button.invoke()
            else:
                choice_frame = ttk.Frame(
                    f,
                    style="F.TFrame"
                )
                choice_frame.grid(sticky=tk.W, padx=left_padding)
                option_widget = self.get_option_widget(option.option_types[0], choice_frame)
                option_widget.grid(row=0, column=0, sticky=tk.W)
                f.option_widget = option_widget
        #self.show_options_button = ttk.Button(
        #    self.stream_frame_body, command=self._toggle_show_options, style="Stop.TButton",
        #    cursor=self.button_cursor
        #)
        #self.show_options_button.config(image=self.show_options_picture)
        #self.show_options_button.grid(sticky=tk.W, row=2, column=0)

    def _get_chosen_option(self, option_type, option_widget):
        if option_type.value == float:
            return float(option_widget.entry.get())
        if option_type.value == bool:
            return option_widget.chosen_value.get()
        return option_type.value

    def get_chosen_options(self):
        chosen_options = []
        for o, f in self.option_frames:
            if len(o.option_types) > 1:
                chosen_index = f.chosen_type.get()
                option_type = o.option_types[chosen_index]
                option_widget = f.choices_frame.choices[chosen_index]
                chosen_options.append(self._get_chosen_option(option_type, option_widget))
            else:
                option_type = o.option_types[0]
                option_widget = f.option_widget
                chosen_options.append(self._get_chosen_option(option_type, option_widget))
        return chosen_options

    #def _toggle_show_options(self):
    #    if self.options_frame.winfo_ismapped():
    #        self.show_options_button.config(image=self.show_options_picture)
    #        self.options_frame.grid_forget()
    #    else:
    #        self.show_options_button.config(image=self.hide_options_picture)
    #        self.options_frame.grid(sticky=tk.W + tk.E, row=3)

    def show_progress(self, total_bytes, bytes_left_to_download, points_paid,
                      points_remaining):
        if self.bytes_downloaded_label is None:
            self.remove_download_buttons()
            self.button_frame.destroy()
            self.estimated_cost_frame.destroy()
            for option, frame in self.option_frames:
                frame.destroy()
            self.options_frame.destroy()
            #self.show_options_button.destroy()

            self.progress_frame = ttk.Frame(self.outer_button_frame, style="F.TFrame")
            self.progress_frame.grid(row=0, column=0, sticky=tk.W, pady=(0, 8))

            self.bytes_downloaded_label = ttk.Label(
                self.progress_frame,
                text=""
            )
            self.bytes_downloaded_label.grid(row=0, column=0)

            self.cost_frame = ttk.Frame(self.outer_button_frame, style="F.TFrame")
            self.cost_frame.grid(row=1, column=0, sticky=tk.W, pady=(0, 4))

            self.cost_label = ttk.Label(
                self.cost_frame,
                text="",
                foreground="red"
            )
            self.cost_label.grid(row=0, column=1, padx=(1, 0))
            self.outer_button_frame.grid_columnconfigure(2, weight=0, uniform="")

        if self.bytes_downloaded_label.winfo_exists():
            percent_done = 0
            if total_bytes > 0:
                percent_done = 100.0 * (total_bytes - bytes_left_to_download) / total_bytes
            percent_done_string = locale.format_string("  (%.2f%%)", percent_done)
            self.bytes_downloaded_label.config(
                text=self.get_formatted_stream_size(total_bytes - bytes_left_to_download) + percent_done_string
            )
        if self.cost_label.winfo_exists():
            total_points = points_remaining + points_paid
            self.cost_label.config(text=locale.format_string("%.2f/%.2f LBC",
                                                             (round(points_paid, 2), round(total_points, 2)),
                                                             grouping=True))

    def show_download_done(self, total_points_paid):
        if self.bytes_downloaded_label is not None and self.bytes_downloaded_label.winfo_exists():
            self.bytes_downloaded_label.destroy()
        if self.cost_label is not None and self.cost_label.winfo_exists():
            self.cost_label.config(text=locale.format_string("%.2f LBC",
                                                             (round(total_points_paid, 2),),
                                                             grouping=True))