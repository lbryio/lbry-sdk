import subprocess
import binascii

from zope.interface import implements

from lbrynet.core.DownloadOption import DownloadOption
from lbrynet.lbryfile.StreamDescriptor import save_sd_info
from lbrynet.cryptstream.client.CryptStreamDownloader import CryptStreamDownloader
from lbrynet.core.client.StreamProgressManager import FullStreamProgressManager
from lbrynet.interfaces import IStreamDownloaderFactory
from lbrynet.lbryfile.client.LBRYFileMetadataHandler import LBRYFileMetadataHandler
import os
from twisted.internet import defer, threads, reactor


class LBRYFileDownloader(CryptStreamDownloader):
    """Classes which inherit from this class download LBRY files"""

    def __init__(self, stream_hash, peer_finder, rate_limiter, blob_manager,
                 stream_info_manager, payment_rate_manager, wallet, upload_allowed):
        CryptStreamDownloader.__init__(self, peer_finder, rate_limiter, blob_manager,
                                       payment_rate_manager, wallet, upload_allowed)
        self.stream_hash = stream_hash
        self.stream_info_manager = stream_info_manager
        self.suggested_file_name = None
        self._calculated_total_bytes = None

    def set_stream_info(self):
        if self.key is None:
            d = self.stream_info_manager.get_stream_info(self.stream_hash)

            def set_stream_info(stream_info):
                key, stream_name, suggested_file_name = stream_info
                self.key = binascii.unhexlify(key)
                self.stream_name = binascii.unhexlify(stream_name)
                self.suggested_file_name = binascii.unhexlify(suggested_file_name)

            d.addCallback(set_stream_info)
            return d
        else:
            return defer.succeed(True)

    def stop(self):
        d = self._close_output()
        d.addCallback(lambda _: CryptStreamDownloader.stop(self))
        return d

    def _get_progress_manager(self, download_manager):
        return FullStreamProgressManager(self._finished_downloading, self.blob_manager, download_manager)

    def _start(self):
        d = self._setup_output()
        d.addCallback(lambda _: CryptStreamDownloader._start(self))
        return d

    def _setup_output(self):
        pass

    def _close_output(self):
        pass

    def get_total_bytes(self):
        if self._calculated_total_bytes is None or self._calculated_total_bytes == 0:
            if self.download_manager is None:
                return 0
            else:
                self._calculated_total_bytes = self.download_manager.calculate_total_bytes()
        return self._calculated_total_bytes

    def get_bytes_left_to_output(self):
        if self.download_manager is not None:
            return self.download_manager.calculate_bytes_left_to_output()
        else:
            return 0

    def get_bytes_left_to_download(self):
        if self.download_manager is not None:
            return self.download_manager.calculate_bytes_left_to_download()
        else:
            return 0

    def _get_metadata_handler(self, download_manager):
        return LBRYFileMetadataHandler(self.stream_hash, self.stream_info_manager, download_manager)


class LBRYFileDownloaderFactory(object):
    implements(IStreamDownloaderFactory)

    def __init__(self, peer_finder, rate_limiter, blob_manager, stream_info_manager,
                 wallet):
        self.peer_finder = peer_finder
        self.rate_limiter = rate_limiter
        self.blob_manager = blob_manager
        self.stream_info_manager = stream_info_manager
        self.wallet = wallet

    def get_downloader_options(self, sd_validator, payment_rate_manager):
        options = [
            DownloadOption(
                [float, None],
                "rate which will be paid for data (None means use application default)",
                "data payment rate",
                None
            ),
            DownloadOption(
                [bool],
                "allow reuploading data downloaded for this file",
                "allow upload",
                True
            ),
        ]
        return options

    def make_downloader(self, sd_validator, options, payment_rate_manager, **kwargs):
        if options[0] is not None:
            payment_rate_manager.float(options[0])
        upload_allowed = options[1]

        def create_downloader(stream_hash):
            downloader = self._make_downloader(stream_hash, payment_rate_manager, sd_validator.raw_info,
                                               upload_allowed)
            d = downloader.set_stream_info()
            d.addCallback(lambda _: downloader)
            return d

        d = save_sd_info(self.stream_info_manager, sd_validator.raw_info)

        d.addCallback(create_downloader)
        return d

    def _make_downloader(self, stream_hash, payment_rate_manager, stream_info, upload_allowed):
        pass


class LBRYFileSaver(LBRYFileDownloader):
    def __init__(self, stream_hash, peer_finder, rate_limiter, blob_manager, stream_info_manager,
                 payment_rate_manager, wallet, download_directory, upload_allowed, file_name=None):
        LBRYFileDownloader.__init__(self, stream_hash, peer_finder, rate_limiter, blob_manager,
                                    stream_info_manager, payment_rate_manager, wallet, upload_allowed)
        self.download_directory = download_directory
        self.file_name = file_name
        self.file_handle = None

    def set_stream_info(self):
        d = LBRYFileDownloader.set_stream_info(self)

        def set_file_name():
            if self.file_name is None:
                if self.suggested_file_name:
                    self.file_name = os.path.basename(self.suggested_file_name)
                else:
                    self.file_name = os.path.basename(self.stream_name)

        d.addCallback(lambda _: set_file_name())
        return d

    def stop(self):
        d = LBRYFileDownloader.stop(self)
        d.addCallback(lambda _: self._delete_from_info_manager())
        return d

    def _get_progress_manager(self, download_manager):
        return FullStreamProgressManager(self._finished_downloading, self.blob_manager, download_manager,
                                         delete_blob_after_finished=True)

    def _setup_output(self):
        def open_file():
            if self.file_handle is None:
                file_name = self.file_name
                if not file_name:
                    file_name = "_"
                if os.path.exists(os.path.join(self.download_directory, file_name)):
                    ext_num = 1
                    while os.path.exists(os.path.join(self.download_directory,
                                                      file_name + "_" + str(ext_num))):
                        ext_num += 1
                    file_name = file_name + "_" + str(ext_num)
                self.file_handle = open(os.path.join(self.download_directory, file_name), 'wb')
        return threads.deferToThread(open_file)

    def _close_output(self):
        self.file_handle, file_handle = None, self.file_handle

        def close_file():
            if file_handle is not None:
                name = file_handle.name
                file_handle.close()
                if self.completed is False:
                    os.remove(name)

        return threads.deferToThread(close_file)

    def _get_write_func(self):
        def write_func(data):
            if self.stopped is False and self.file_handle is not None:
                self.file_handle.write(data)
        return write_func

    def _delete_from_info_manager(self):
        return self.stream_info_manager.delete_stream(self.stream_hash)


class LBRYFileSaverFactory(LBRYFileDownloaderFactory):
    def __init__(self, peer_finder, rate_limiter, blob_manager, stream_info_manager,
                 wallet, download_directory):
        LBRYFileDownloaderFactory.__init__(self, peer_finder, rate_limiter, blob_manager,
                                           stream_info_manager, wallet)
        self.download_directory = download_directory

    def _make_downloader(self, stream_hash, payment_rate_manager, stream_info, upload_allowed):
        return LBRYFileSaver(stream_hash, self.peer_finder, self.rate_limiter, self.blob_manager,
                             self.stream_info_manager, payment_rate_manager, self.wallet,
                             self.download_directory, upload_allowed)

    def get_description(self):
        return "Save"


class LBRYFileOpener(LBRYFileDownloader):
    def __init__(self, stream_hash, peer_finder, rate_limiter, blob_manager, stream_info_manager,
                 payment_rate_manager, wallet, upload_allowed):
        LBRYFileDownloader.__init__(self, stream_hash, peer_finder, rate_limiter, blob_manager,
                                    stream_info_manager, payment_rate_manager, wallet, upload_allowed)
        self.process = None
        self.process_log = None

    def stop(self):
        d = LBRYFileDownloader.stop(self)
        d.addCallback(lambda _: self._delete_from_info_manager())
        return d

    def _get_progress_manager(self, download_manager):
        return FullStreamProgressManager(self._finished_downloading, self.blob_manager, download_manager,
                                         delete_blob_after_finished=True)

    def _setup_output(self):
        def start_process():
            if os.name == "nt":
                paths = [r'C:\Program Files\VideoLAN\VLC\vlc.exe',
                         r'C:\Program Files (x86)\VideoLAN\VLC\vlc.exe']
                for p in paths:
                    if os.path.exists(p):
                        vlc_path = p
                        break
                else:
                    raise ValueError("You must install VLC media player to stream files")
            else:
                vlc_path = 'vlc'
            self.process_log = open("vlc.out", 'a')
            try:
                self.process = subprocess.Popen([vlc_path, '-'], stdin=subprocess.PIPE,
                                                stdout=self.process_log, stderr=self.process_log)
            except OSError:
                raise ValueError("VLC media player could not be opened")

        d = threads.deferToThread(start_process)
        return d

    def _close_output(self):
        if self.process is not None:
            self.process.stdin.close()
        self.process = None
        return defer.succeed(True)

    def _get_write_func(self):
        def write_func(data):
            if self.stopped is False and self.process is not None:
                try:
                    self.process.stdin.write(data)
                except IOError:
                    reactor.callLater(0, self.stop)
        return write_func

    def _delete_from_info_manager(self):
        return self.stream_info_manager.delete_stream(self.stream_hash)


class LBRYFileOpenerFactory(LBRYFileDownloaderFactory):
    def _make_downloader(self, stream_hash, payment_rate_manager, stream_info, upload_allowed):
        return LBRYFileOpener(stream_hash, self.peer_finder, self.rate_limiter, self.blob_manager,
                              self.stream_info_manager, payment_rate_manager, self.wallet, upload_allowed)

    def get_description(self):
        return "Stream"