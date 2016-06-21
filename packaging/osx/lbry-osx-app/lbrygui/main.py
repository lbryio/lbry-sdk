from PyObjCTools import AppHelper
from twisted.internet.cfreactor import install
install(runner=AppHelper.runEventLoop)
from twisted.internet import reactor

import logging
import sys
import os
from appdirs import user_data_dir

from LBRYApp import LBRYDaemonApp

if sys.platform != "darwin":
    log_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
else:
    log_dir = user_data_dir("LBRY")

if not os.path.isdir(log_dir):
    os.mkdir(log_dir)

LOG_FILENAME = os.path.join(log_dir, 'lbrynet-daemon.log')

log = logging.getLogger(__name__)
handler = logging.handlers.RotatingFileHandler(LOG_FILENAME, maxBytes=2097152, backupCount=5)
log.addHandler(handler)
logging.basicConfig(level=logging.INFO)


def main():
    app = LBRYDaemonApp.sharedApplication()
    reactor.addSystemEventTrigger("after", "shutdown", AppHelper.stopEventLoop)
    reactor.run()

if __name__ == "__main__":
    main()
