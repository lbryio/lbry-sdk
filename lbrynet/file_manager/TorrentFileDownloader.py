import os
import logging
import libtorrent as lt
import time

log = logging.getLogger(__name__)

class TorrentDownloader(object):

    def __init__(self, download_directory, url):
        self.download_directory = download_directory
        self.url = 'magnet:?xt=urn:btih:' + url


    def download(self):
        ses = lt.session()
        ses.listen_on(6881, 6891)
        params = {
            "save_path": self.download_directory,
            "storage_mode": lt.storage_mode_t(2),
            "paused": False,
            "auto_managed": True,
            "duplicate_is_error": True}
        link = self.url
        handle = lt.add_magnet_uri(ses, link, params)
        ses.start_dht()

        log.info("Downloading Metadata...")
        while (not handle.has_metadata()):
            time.sleep(1)

        log.info("File Name: %s", handle.name())
        log.info("Got Metadata, Starting Torrent Download...")
        while (handle.status().state != lt.torrent_status.seeding):
            s = handle.status()
            state_str = ['queued', 'checking', 'downloading metadata', \
                        'downloading', 'finished', 'seeding', 'allocating']
            log.info('%.2f%% complete (down: %.1f kb/s up: %.1f kB/s peers: %d) %s %.3f' % \
                        (s.progress * 100, s.download_rate / 1000, s.upload_rate / 1000, \
                        s.num_peers, state_str[s.state], s.total_download/1000000))
            time.sleep(5)

        return self.download_directory + handle.name()


    def start(self):

        # Create directory to save files
        if not os.path.exists(self.download_directory):
            os.makedirs(self.download_directory)

        log.info(self.url)
        file_address = self.download()
        
        return file_address
