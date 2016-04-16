import os
import json
import webbrowser
import subprocess
import sys

from time import sleep
from jsonrpc.proxy import JSONRPCProxy

API_CONNECTION_STRING = "http://localhost:5279/lbryapi"
UI_ADDRESS = "http://localhost:5279"


class Timeout(Exception):
    def __init__(self, value):
        self.parameter = value

    def __str__(self):
        return repr(self.parameter)


class LBRYURIHandler(object):
    def __init__(self):
        self.started_daemon = False
        self.start_timeout = 0
        self.daemon = JSONRPCProxy.from_url(API_CONNECTION_STRING)

    def check_status(self):
        status = None
        try:
            status = self.daemon.is_running()
            if self.start_timeout < 30 and not status:
                sleep(1)
                self.start_timeout += 1
                self.check_status()
            elif status:
                return True
            else:
                raise Timeout("LBRY daemon is running, but connection timed out")
        except:
            if self.start_timeout < 30:
                sleep(1)
                self.start_timeout += 1
                self.check_status()
            else:
                raise Timeout("Timed out trying to start LBRY daemon")

    def handle_osx(self, lbry_name):
        lbry_process = [d for d in subprocess.Popen(['ps','aux'], stdout=subprocess.PIPE).stdout.readlines()
                            if 'LBRY.app' in d and 'LBRYURIHandler' not in d]
        try:
            status = self.daemon.is_running()
        except:
            status = None

        if lbry_process or status:
            self.check_status()
            started = False
        else:
            os.system("open /Applications/LBRY.app")
            self.check_status()
            started = True

        if lbry_name == "lbry" or lbry_name == "" and not started:
            webbrowser.open(UI_ADDRESS)
        else:
            webbrowser.open(UI_ADDRESS + "/view?name=" + lbry_name)

    def handle_linux(self, lbry_name):
        try:
            is_running = self.daemon.is_running()
            if not is_running:
                sys.exit(0)
        except:
            sys.exit(0)

        if lbry_name == "lbry":
            webbrowser.open(UI_ADDRESS)
        else:
            webbrowser.open(UI_ADDRESS + "/view?name=" + lbry_name)


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
