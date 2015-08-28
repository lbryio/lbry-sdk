import logging
import sys

from lbrynet.lbrynet_downloader_gui.DownloaderApp import DownloaderApp
from twisted.internet import reactor, task
import locale


def start_downloader():

    log_format = "(%(asctime)s)[%(filename)s:%(lineno)s] %(funcName)s(): %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=log_format, filename="downloader.log")
    sys.stdout = open("downloader.out.log", 'w')
    sys.stderr = open("downloader.err.log", 'w')

    locale.setlocale(locale.LC_ALL, '')

    app = DownloaderApp()

    d = task.deferLater(reactor, 0, app.start)

    reactor.run()

if __name__ == "__main__":
    start_downloader()