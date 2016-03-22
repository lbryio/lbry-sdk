import os
import json
import webbrowser
import sys
from time import sleep

from jsonrpc.proxy import JSONRPCProxy
from lbrynet.conf import API_CONNECTION_STRING, UI_ADDRESS


class LBRYURIHandler(object):
    def __init__(self):
        self.started_daemon = False
        self.start_timeout = 0
        self.daemon = JSONRPCProxy.from_url(API_CONNECTION_STRING)

    def check_status(self):
        try:
            self.daemon.is_running()

        except:
            if self.started_daemon:
                if self.start_timeout < 30:
                    sleep(1)
                    self.start_timeout += 1
                    self.check_status()
                else:
                    exit(1)
            else:
                os.system("open /Applications/LBRY.app")
                self.started_daemon = True
                self.start_timeout += 1
                self.check_status()

    def handle(self, lbry_name):
        self.check_status()

        if lbry_name == "lbry":
            webbrowser.get('safari').open(UI_ADDRESS)
        else:
            r = json.loads(self.daemon.get({'name': lbry_name}))
            if r['code'] == 200:
                path = r['result']['path'].encode('utf-8')
                extension = os.path.splitext(path)[1]
                if extension in ['mp4', 'flv', 'mov', 'ogv']:
                    webbrowser.get('safari').open(UI_ADDRESS + "/view?name=" + lbry_name)
                else:
                    webbrowser.get('safari').open('file://' + path)
            else:
                webbrowser.get('safari').open('http://lbry.io/get')


def main(args):
    if len(args) != 1:
        args = ['lbry://lbry']

    name = args[0][7:]
    LBRYURIHandler().handle(lbry_name=name)


if __name__ == "__main__":
   main(sys.argv[1:])
