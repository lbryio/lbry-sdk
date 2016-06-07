import argparse
import logging
import logging.handlers
import os
import webbrowser
import sys
import socket
import platform
from appdirs import user_data_dir

from twisted.web import server
from twisted.internet import reactor, defer
from jsonrpc.proxy import JSONRPCProxy

from lbrynet.lbrynet_daemon.LBRYDaemonServer import LBRYDaemonServer
from lbrynet.conf import API_CONNECTION_STRING, API_INTERFACE, API_ADDRESS, API_PORT, \
                            DEFAULT_WALLET, UI_ADDRESS, DEFAULT_UI_BRANCH, LOG_FILE_NAME

if sys.platform != "darwin":
    log_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
else:
    log_dir = user_data_dir("LBRY")

if not os.path.isdir(log_dir):
    os.mkdir(log_dir)

lbrynet_log = os.path.join(log_dir, LOG_FILE_NAME)
log = logging.getLogger(__name__)
handler = logging.handlers.RotatingFileHandler(lbrynet_log, maxBytes=2097152, backupCount=5)
log.addHandler(handler)
log.setLevel(logging.INFO)

REMOTE_SERVER = "www.google.com"


def test_internet_connection():
    try:
        host = socket.gethostbyname(REMOTE_SERVER)
        s = socket.create_connection((host, 80), 2)
        return True
    except:
        return False


def stop():
    def _disp_shutdown():
        print "Shutting down lbrynet-daemon from command line"
        log.info("Shutting down lbrynet-daemon from command line")

    def _disp_not_running():
        print "Attempt to shut down lbrynet-daemon from command line when daemon isn't running"
        log.info("Attempt to shut down lbrynet-daemon from command line when daemon isn't running")

    d = defer.Deferred(None)
    d.addCallback(lambda _: JSONRPCProxy.from_url(API_CONNECTION_STRING).stop())
    d.addCallbacks(lambda _: _disp_shutdown(), lambda _: _disp_not_running())
    d.callback(None)


def start():
    parser = argparse.ArgumentParser(description="Launch lbrynet-daemon")
    parser.add_argument("--wallet",
                        help="lbrycrd or lbryum, default lbryum",
                        type=str,
                        default='')
    parser.add_argument("--ui",
                        help="path to custom UI folder",
                        default=None)
    parser.add_argument("--branch",
                        help="Branch of lbry-web-ui repo to use, defaults on master")
    parser.add_argument('--no-launch', dest='launchui', action="store_false")
    parser.add_argument('--log-to-console', dest='logtoconsole', action="store_true")
    parser.add_argument('--quiet', dest='quiet', action="store_true")
    parser.set_defaults(branch=False, launchui=True, logtoconsole=False, quiet=False)
    args = parser.parse_args()

    if args.logtoconsole:
        logging.basicConfig(level=logging.INFO)

    args = parser.parse_args()

    try:
        JSONRPCProxy.from_url(API_CONNECTION_STRING).is_running()
        log.info("lbrynet-daemon is already running")
        if not args.logtoconsole:
            print "lbrynet-daemon is already running"
        if args.launchui:
            webbrowser.open(UI_ADDRESS)
        return
    except:
        pass

    log.info("Starting lbrynet-daemon from command line")

    if not args.logtoconsole and not args.quiet:
        print "Starting lbrynet-daemon from command line"
        print "To view activity, view the log file here: " + lbrynet_log
        print "Web UI is available at http://%s:%i" % (API_INTERFACE, API_PORT)
        print "JSONRPC API is available at " + API_CONNECTION_STRING
        print "To quit press ctrl-c or call 'stop' via the API"

    if test_internet_connection():
        lbry = LBRYDaemonServer()

        d = lbry.start(branch=args.branch if args.branch else DEFAULT_UI_BRANCH,
                       user_specified=args.ui,
                       wallet=args.wallet,
                       branch_specified=True if args.branch else False)
        if args.launchui:
            d.addCallback(lambda _: webbrowser.open(UI_ADDRESS))

        reactor.listenTCP(API_PORT, server.Site(lbry.root), interface=API_INTERFACE)
        reactor.run()

        if not args.logtoconsole and not args.quiet:
            print "\nClosing lbrynet-daemon"
    else:
        log.info("Not connected to internet, unable to start")
        if not args.logtoconsole:
            print "Not connected to internet, unable to start"
        return

if __name__ == "__main__":
    start()