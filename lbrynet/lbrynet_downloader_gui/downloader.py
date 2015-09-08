import logging
import sys

from lbrynet.lbrynet_downloader_gui.DownloaderApp import DownloaderApp
from twisted.internet import reactor, task
import locale


def start_downloader():

    log_format = "(%(asctime)s)[%(filename)s:%(lineno)s] %(funcName)s(): %(message)s"
    formatter = logging.Formatter(log_format)

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    file_handler = logging.FileHandler("downloader.log")
    file_handler.setFormatter(formatter)
    file_handler.addFilter(logging.Filter("lbrynet"))
    logger.addHandler(file_handler)

    sys.stdout = open("downloader.out.log", 'w')
    sys.stderr = open("downloader.err.log", 'w')

    locale.setlocale(locale.LC_ALL, '')

    app = DownloaderApp()

    d = task.deferLater(reactor, 0, app.start)

    reactor.run()

if __name__ == "__main__":
    start_downloader()