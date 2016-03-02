import rumps
import xmlrpclib
import os
import webbrowser
import subprocess
import argparse


class DaemonStatusBarApp(rumps.App):
    def __init__(self):
        icon_path = 'app.icns'
        if os.path.isfile(icon_path):
            rumps.App.__init__(self, name="LBRY", icon=icon_path, quit_button=None,
                                menu=["Open", "Preferences", "View balance", "Quit"])
        else:
            rumps.App.__init__(self, name="LBRY", title="LBRY", quit_button=None,
                                menu=["Open", "Preferences", "View balance", "Quit"])

    @rumps.timer(1)
    def alert_daemon_start(self):
        daemon = xmlrpclib.ServerProxy("http://localhost:7080/")
        try:
            start_msg = daemon.is_running()
            if isinstance(start_msg, str):
                rumps.notification(title='LBRY', subtitle='', message=str(start_msg), sound=True)
                update_info = daemon.check_for_new_version()
                update_msg = ""
                for p in update_info:
                    if not p[0]:
                        update_msg += p[1] + "\n"
                if update_msg:
                    update_msg += "\n Try running the installer again to fix this"
                    rumps.notification(title='LBRY', subtitle='', message=update_msg, sound=True)
        except:
            pass

    @rumps.clicked('Open')
    def get_ui(self):
        daemon = xmlrpclib.ServerProxy("http://localhost:7080/")
        try:
            daemon.is_running()
            webbrowser.open("lbry://lbry")
        except:
            try:
                rumps.notification(title='LBRY', subtitle='', message="Couldn't connect to lbrynet daemon", sound=True)
            except:
                rumps.alert(title='LBRY', message="Couldn't connect to lbrynet daemon")

    @rumps.clicked("Preferences")
    def prefs(self):
        daemon = xmlrpclib.ServerProxy("http://localhost:7080/")
        try:
            daemon.is_running()
            webbrowser.open("lbry://settings")
        except:
            rumps.notification(title='LBRY', subtitle='', message="Couldn't connect to lbrynet daemon", sound=True)

    @rumps.clicked("View balance")
    def disp_balance(self):
        daemon = xmlrpclib.ServerProxy("http://localhost:7080/")
        try:
            balance = daemon.get_balance()
            r = round(float(balance), 2)
            try:
                rumps.notification(title='LBRY', subtitle='', message=str("Your balance is %.2f LBC" % r), sound=False)
            except:
                rumps.alert(title='LBRY',  message=str("Your balance is %.2f LBC" % r))

        except:
            try:
                rumps.notification(title='LBRY', subtitle='', message="Couldn't connect to lbrynet daemon", sound=True)
            except:
                rumps.alert(title='LBRY', message="Couldn't connect to lbrynet daemon")

    @rumps.clicked('Quit')
    def clean_quit(self):
        daemon = xmlrpclib.ServerProxy("http://localhost:7080/")
        try:
            daemon.stop()
        except:
            pass
        rumps.quit_application()


def main():
    parser = argparse.ArgumentParser(description="Launch lbrynet status bar application")
    parser.add_argument("--startdaemon",
                        help="true or false, default true",
                        type=str,
                        default="true")
    args = parser.parse_args()

    if str(args.startdaemon).lower() == "true":
        daemon = xmlrpclib.ServerProxy('http://localhost:7080')
        try:
            daemon.is_running()
        except:
            subprocess.Popen("screen -dmS lbrynet bash -c "
                             "'PYTHONPATH=$PYTHONPATH:`cat /Users/${USER}/Library/Application\ Support/lbrynet/.python_path`; "
                             "PATH=$PATH:`cat /Users/${USER}/Library/Application\ Support/lbrynet/.lbry_bin_path`; "
                             "lbrynet-daemon --update=False'", shell=True)

    status_app = DaemonStatusBarApp()
    status_app.run()


if __name__ == '__main__':
    main()