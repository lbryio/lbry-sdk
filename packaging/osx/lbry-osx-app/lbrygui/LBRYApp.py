import AppKit
import webbrowser
import sys
import logging
import platform
from twisted.internet import reactor

from lbrynet.lbrynet_daemon import DaemonControl
from lbrynet import analytics
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
        self.open = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Open", "openui:", "")
        self.menubarMenu.addItem_(self.open)
        self.quit = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Quit", "applicationShouldTerminate:", "")
        self.menubarMenu.addItem_(self.quit)
        self.statusitem.setMenu_(self.menubarMenu)
        self.statusitem.setToolTip_(settings.APP_NAME)

        if test_internet_connection():
            notify("Starting LBRY")
        else:
            notify("LBRY needs an internet connection to start, try again when one is available")
            sys.exit(0)

        DaemonControl.start_server_and_listen(
            launchui=True, use_auth=False,
            analytics_manager=analytics.Manager.new_instance()
        )

    def openui_(self, sender):
        webbrowser.open(settings.UI_ADDRESS)

    # this code is from the example
    # https://pythonhosted.org/pyobjc/examples/Cocoa/Twisted/WebServicesTool/index.html
    def applicationShouldTerminate_(self, sender):
        if reactor.running:
            log.info('Stopping twisted event loop')
            notify("Goodbye!")
            reactor.stop()
            return False
        return True


def notify(msg):
    if platform.mac_ver()[0] >= "10.10":
        LBRYNotify(msg)
