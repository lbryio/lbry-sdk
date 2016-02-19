import rumps
import xmlrpclib
import os

class DaemonStatusBarApp(rumps.App):
    def __init__(self):
        super(DaemonStatusBarApp, self).__init__("LBRYnet", icon=os.path.join(os.path.expanduser("~"), "Downloads/lbryio//web/img/fav/apple-touch-icon.png"), quit_button=None)
        self.menu = ["Quit"]

    @rumps.clicked('Quit')
    def clean_quit(self):
        d = xmlrpclib.ServerProxy('http://localhost:7080')
        d.stop()
        rumps.quit_application()

