import rumps
import xmlrpclib
import os
import webbrowser
import subprocess


class DaemonStatusBarApp(rumps.App):
    def __init__(self):
        icon_path = os.path.join(os.path.expanduser("~"), "Downloads/lbryio/web/img/fav/apple-touch-icon.png")
        if os.path.isfile(icon_path):
            rumps.App.__init__(self, name="LBRY", icon=icon_path, quit_button=None,
                                menu=["Open", "Preferences", "View balance", "Quit"])
        else:
            rumps.App.__init__(self, name="LBRY", title="LBRY", quit_button=None,
                                menu=["Open", "Preferences", "View balance", "Quit"])

    @rumps.clicked('Open')
    def get_ui(self):
        try:
            daemon = xmlrpclib.ServerProxy('http://localhost:7080')
            daemon.is_running()
            webbrowser.open("lbry://lbry")
        except:
            try:
                rumps.notification(title='LBRY', subtitle='status', message="Couldn't connect to lbrynet daemon", sound=True)
            except:
                rumps.alert(title='LBRY', message="Couldn't connect to lbrynet daemon")

    @rumps.clicked("Preferences")
    def prefs(self, _):
        try:
            daemon = xmlrpclib.ServerProxy('http://localhost:7080')
            daemon.is_running()
            webbrowser.open("lbry://settings")
        except:
            rumps.notification(title='LBRY', subtitle='status', message="Couldn't connect to lbrynet daemon", sound=True)

    @rumps.clicked("View balance")
    def disp_balance(self):
        daemon = xmlrpclib.ServerProxy('http://localhost:7080')
        try:
            balance = daemon.get_balance()
            try:
                rumps.notification(title='LBRY', subtitle='status', message="Your balance is " + str(balance), sound=False)
            except:
                rumps.alert(title='LBRY', message="Your balance is " + str(balance))

        except:
            try:
                rumps.notification(title='LBRY', subtitle='status', message="Couldn't connect to lbrynet daemon", sound=True)
            except:
                rumps.alert(title='LBRY', message="Couldn't connect to lbrynet daemon")

    @rumps.clicked('Quit')
    def clean_quit(self):
        daemon = xmlrpclib.ServerProxy('http://localhost:7080')
        try:
            daemon.stop()
        except:
            pass

        rumps.quit_application()


def main():
    subprocess.Popen("screen -dmS lbry bash -c 'lbrynet-daemon --update=False'", shell=True)
    status_app = DaemonStatusBarApp()
    status_app.run()


if __name__ == '__main__':
    main()