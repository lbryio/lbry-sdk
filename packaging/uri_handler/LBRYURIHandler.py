import os
import webbrowser
import subprocess
import sys
from time import sleep

from lbrynet.lbrynet_daemon.auth.client import LBRYAPIClient
from lbrynet import conf


class LBRYURIHandler(object):
    def __init__(self):
        self.started_daemon = False
        self.daemon = LBRYAPIClient.config()

    def handle_osx(self, lbry_name):
        self.check_daemon()
        if not self.started_daemon:
            os.system("open /Applications/LBRY.app")
            sleep(3)

        lbry_name = self.parse_name(lbry_name)
        self.open_address(lbry_name)

    def handle_linux(self, lbry_name):
        self.check_daemon()
        if not self.started_daemon:
            cmd = r'DIR = "$( cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd )"' \
                  r'if [-z "$(pgrep lbrynet-daemon)"]; then' \
                    r'echo "running lbrynet-daemon..."' \
                    r'$DIR / lbrynet - daemon &' \
                    r'sleep 3  # let the daemon load before connecting' \
                  r'fi'
            subprocess.Popen(cmd, shell=True)

        lbry_name = self.parse_name(lbry_name)
        self.open_address(lbry_name)

    def handle_win32(self, lbry_name):
        # Opening LBRY.exe with lbry_name as arg prevents the need to
        # make a separate call to open_address()
        self.check_daemon()
        lbry_name = self.parse_name(lbry_name)
        if self.started_daemon:
            self.open_address(lbry_name)
        else:
            lbry_path = os.path.join(os.environ["PROGRAMFILES"], "LBRY", "LBRY.exe ")
            subprocess.call(lbry_path + lbry_name)

    def check_daemon(self):
        try:
            self.started_daemon = self.daemon.is_running()
        except:
            self.started_daemon = False

    @staticmethod
    def parse_name(lbry_name):
        if lbry_name[:7].lower() == "lbry://":
            if lbry_name[-1] == "/":
                return lbry_name[7:-1]
            else:
                return lbry_name[7:]
        else:
            if lbry_name[-1] == "/":
                return lbry_name[:-1]
            else:
                return lbry_name[:]

    @staticmethod
    def open_address(lbry_name):
        if lbry_name == "lbry" or lbry_name == "" or lbry_name is None:
            webbrowser.open(conf.settings.UI_ADDRESS)
        else:
            webbrowser.open(conf.settings.UI_ADDRESS + "/?show=" + lbry_name)


def main(args):
    if len(args) != 1:
        args = ["lbry://lbry"]
    name = args[0][7:]
    if sys.platform == "darwin":
        LBRYURIHandler().handle_osx(lbry_name=name)
    elif os.name == "nt":
        LBRYURIHandler().handle_win32(lbry_name=name)
    else:
        LBRYURIHandler().handle_linux(lbry_name=name)

if __name__ == "__main__":
    main(sys.argv[1:])
