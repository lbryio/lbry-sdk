import AppKit
import webbrowser
import sys
import os
import logging
import platform
import shutil
from appdirs import user_data_dir
from twisted.internet import reactor
from twisted.web import server
import Foundation
bundle = Foundation.NSBundle.mainBundle()
lbrycrdd_path = bundle.pathForResource_ofType_('lbrycrdd', None)
lbrycrdd_path_conf = os.path.join(os.path.expanduser("~"), ".lbrycrddpath.conf")
wallet_dir = user_data_dir("lbrycrd")

if not os.path.isdir(wallet_dir):
    shutil.os.mkdir(wallet_dir)

if not os.path.isfile(lbrycrdd_path_conf):
    f = open(lbrycrdd_path_conf, "w")
    f.write(lbrycrdd_path)
    f.close()

from lbrynet.lbrynet_daemon.DaemonServer import DaemonServer
from lbrynet.lbrynet_daemon.DaemonRequest import DaemonRequest
from lbrynet.conf import settings
from lbrynet.core import utils


if platform.mac_ver()[0] >= "10.10":
    from LBRYNotify import LBRYNotify

log = logging.getLogger(__name__)


def test_internet_connection():
    return utils.check_connection()


class LBRYDaemonApp(AppKit.NSApplication):
    def finishLaunching(self):
        self.connection = False
        statusbar = AppKit.NSStatusBar.systemStatusBar()
        self.statusitem = statusbar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
        self.icon = AppKit.NSImage.alloc().initByReferencingFile_(settings.ICON_PATH)
        self.icon.setScalesWhenResized_(True)
        self.icon.setSize_((20, 20))
        self.statusitem.setImage_(self.icon)
        self.menubarMenu = AppKit.NSMenu.alloc().init()
        self.open = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Open", "openui:", "")
        self.menubarMenu.addItem_(self.open)
        self.quit = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit", "replyToApplicationShouldTerminate:", "")
        self.menubarMenu.addItem_(self.quit)
        self.statusitem.setMenu_(self.menubarMenu)
        self.statusitem.setToolTip_(settings.APP_NAME)


        if test_internet_connection():
            if platform.mac_ver()[0] >= "10.10":
                LBRYNotify("Starting LBRY")
        else:
            if platform.mac_ver()[0] >= "10.10":
                LBRYNotify("LBRY needs an internet connection to start, try again when one is available")
            sys.exit(0)

        lbry = DaemonServer()
        d = lbry.start(use_authentication=False)
        d.addCallback(lambda _: webbrowser.open(settings.UI_ADDRESS))
        lbrynet_server = server.Site(lbry.root)
        lbrynet_server.requestFactory = DaemonRequest
        reactor.listenTCP(settings.api_port, lbrynet_server, interface=settings.API_INTERFACE)

    def openui_(self, sender):
        webbrowser.open(settings.UI_ADDRESS)

    def replyToApplicationShouldTerminate_(self, shouldTerminate):
        if platform.mac_ver()[0] >= "10.10":
            LBRYNotify("Goodbye!")
        reactor.stop()
