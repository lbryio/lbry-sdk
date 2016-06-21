import AppKit
import webbrowser
import sys
import logging
import socket
import platform

from PyObjCTools import AppHelper

from twisted.internet import reactor
from twisted.web import server

from lbrynet.lbrynet_daemon.LBRYDaemonServer import LBRYDaemonServer
from lbrynet.conf import API_PORT, API_INTERFACE, ICON_PATH, APP_NAME
from lbrynet.conf import UI_ADDRESS

if platform.mac_ver()[0] >= "10.10":
    from LBRYNotify import LBRYNotify

log = logging.getLogger(__name__)

REMOTE_SERVER = "www.google.com"


def test_internet_connection():
    try:
        host = socket.gethostbyname(REMOTE_SERVER)
        s = socket.create_connection((host, 80), 2)
        return True
    except:
        return False


class LBRYDaemonApp(AppKit.NSApplication):
    def finishLaunching(self):
        self.connection = False
        statusbar = AppKit.NSStatusBar.systemStatusBar()
        self.statusitem = statusbar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
        self.icon = AppKit.NSImage.alloc().initByReferencingFile_(ICON_PATH)
        self.icon.setScalesWhenResized_(True)
        self.icon.setSize_((20, 20))
        self.statusitem.setImage_(self.icon)
        self.menubarMenu = AppKit.NSMenu.alloc().init()
        self.open = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Open", "openui:", "")
        self.menubarMenu.addItem_(self.open)
        self.quit = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit", "replyToApplicationShouldTerminate:", "")
        self.menubarMenu.addItem_(self.quit)
        self.statusitem.setMenu_(self.menubarMenu)
        self.statusitem.setToolTip_(APP_NAME)


        if test_internet_connection():
            if platform.mac_ver()[0] >= "10.10":
                LBRYNotify("Starting LBRY")
        else:
            if platform.mac_ver()[0] >= "10.10":
                LBRYNotify("LBRY needs an internet connection to start, try again when one is available")
            sys.exit(0)

        # if not subprocess.check_output("git ls-remote https://github.com/lbryio/lbry-web-ui.git | grep HEAD | cut -f 1",
        #                                shell=True):
        #     LBRYNotify(
        #         "You should have been prompted to install xcode command line tools, please do so and then start LBRY")
        #     sys.exit(0)

        lbry = LBRYDaemonServer()
        d = lbry.start()
        d.addCallback(lambda _: webbrowser.open(UI_ADDRESS))
        reactor.listenTCP(API_PORT, server.Site(lbry.root), interface=API_INTERFACE)

    def openui_(self, sender):
        webbrowser.open(UI_ADDRESS)

    def replyToApplicationShouldTerminate_(self, shouldTerminate):
        if platform.mac_ver()[0] >= "10.10":
            LBRYNotify("Goodbye!")
        reactor.stop()
