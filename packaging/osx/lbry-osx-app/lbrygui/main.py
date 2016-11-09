from PyObjCTools import AppHelper
from twisted.internet.cfreactor import install
install(runner=AppHelper.runEventLoop)
from twisted.internet import reactor

import logging

from lbrynet import conf
from lbrynet.core import log_support
from LBRYApp import LBRYDaemonApp


log = logging.getLogger()


def main():
    conf.update_settings_from_file()
    log_file = conf.settings.get_log_filename()
    log_support.configure_logging(log_file, console=True)
    app = LBRYDaemonApp.sharedApplication()
    reactor.addSystemEventTrigger("after", "shutdown", shutdown)
    reactor.run()


def shutdown():
    log.info('Stopping event loop')
    AppHelper.stopEventLoop()


if __name__ == "__main__":
    main()
