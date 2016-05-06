import os
import json
import webbrowser
import subprocess
import sys

from time import sleep
from jsonrpc.proxy import JSONRPCProxy

API_CONNECTION_STRING = "http://localhost:5279/lbryapi"
UI_ADDRESS = "http://localhost:5279"


class LBRYURIHandler(object):
    def __init__(self):
        self.started_daemon = False
        self.daemon = JSONRPCProxy.from_url(API_CONNECTION_STRING)

    def handle_osx(self, lbry_name):
        try:
            status = self.daemon.is_running()
        except:
            os.system("open /Applications/LBRY.app")
            sleep(3)

        if lbry_name == "lbry" or lbry_name == "":
            webbrowser.open(UI_ADDRESS)
        else:
            webbrowser.open(UI_ADDRESS + "/?watch=" + lbry_name)

    def handle_linux(self, lbry_name):
        try:
            status = self.daemon.is_running()
        except:
            cmd = r'DIR = "$( cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd )"' \
                  r'if [-z "$(pgrep lbrynet-daemon)"]; then' \
                    r'echo "running lbrynet-daemon..."' \
                    r'$DIR / lbrynet - daemon &' \
                    r'sleep 3  # let the daemon load before connecting' \
                  r'fi'
            subprocess.Popen(cmd, shell=True)

        if lbry_name == "lbry" or lbry_name == "":
            webbrowser.open(UI_ADDRESS)
        else:
            webbrowser.open(UI_ADDRESS + "/?watch=" + lbry_name)


def main(args):
    if len(args) != 1:
        args = ['lbry://lbry']

    name = args[0][7:]
    if sys.platform == "darwin":
        LBRYURIHandler().handle_osx(lbry_name=name)
    else:
        LBRYURIHandler().handle_linux(lbry_name=name)

if __name__ == "__main__":
   main(sys.argv[1:])
