import rumps
import xmlrpclib
import os
import webbrowser

class DaemonStatusBarApp(rumps.App):
    def __init__(self):
        super(DaemonStatusBarApp, self).__init__("LBRYnet", icon=os.path.join(os.path.expanduser("~"), "Downloads/lbryio//web/img/fav/apple-touch-icon.png"), quit_button=None)
        self.menu = ["Open UI", "Quit"]

    @rumps.clicked('Open UI')
    def get_ui(self):
        webbrowser.open("lbry://lbry")

    @rumps.clicked('Quit')
    def clean_quit(self):
        daemon = xmlrpclib.ServerProxy('http://localhost:7080')
        daemon.stop()
        rumps.quit_application()

def main():
    DaemonStatusBarApp().run()

if __name__ == '__main__':
    main()