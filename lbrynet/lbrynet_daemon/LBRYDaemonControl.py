import argparse
import logging
import logging.handlers
import subprocess
import os
import shutil
import webbrowser
import sys
import socket


from StringIO import StringIO
from zipfile import ZipFile
from urllib import urlopen
from datetime import datetime
from appdirs import user_data_dir
from twisted.web import server, static
from twisted.internet import reactor, defer
from jsonrpc.proxy import JSONRPCProxy

from lbrynet.lbrynet_daemon.LBRYDaemon import LBRYDaemon, LBRYindex, LBRYFileRender
from lbrynet.conf import API_CONNECTION_STRING, API_INTERFACE, API_ADDRESS, API_PORT, DEFAULT_WALLET, UI_ADDRESS

if sys.platform != "darwin":
    log_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
else:
    log_dir = user_data_dir("LBRY")

if not os.path.isdir(log_dir):
    os.mkdir(log_dir)

LOG_FILENAME = os.path.join(log_dir, 'lbrynet-daemon.log')

log = logging.getLogger(__name__)
handler = logging.handlers.RotatingFileHandler(LOG_FILENAME, maxBytes=262144, backupCount=5)
log.addHandler(handler)
logging.basicConfig(level=logging.INFO)

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
        log.info("Shutting down lbrynet-daemon from command line")

    def _disp_not_running():
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
                        default=DEFAULT_WALLET)
    parser.add_argument("--update",
                        help="True or false, default true",
                        type=str,
                        default="True")
    parser.add_argument("--ui",
                        help="path to custom UI folder",
                        default="")
    parser.add_argument("--branch",
                        help="Branch of lbry-web-ui repo to use, defaults on HEAD",
                        default="HEAD")

    try:
        JSONRPCProxy.from_url(API_CONNECTION_STRING).is_running()
        log.info("lbrynet-daemon is already running")
        return
    except:
        pass

    log.info("Starting lbrynet-daemon from command line")

    args = parser.parse_args()

    if args.branch == "HEAD":
        GIT_CMD_STRING = "git ls-remote https://github.com/lbryio/lbry-web-ui.git | grep %s | cut -f 1" % args.branch
        DIST_URL = "https://raw.githubusercontent.com/lbryio/lbry-web-ui/master/dist.zip"
    else:
        log.info("Using UI branch: " + args.branch)
        GIT_CMD_STRING = "git ls-remote https://github.com/lbryio/lbry-web-ui.git | grep refs/heads/%s | cut -f 1" % args.branch
        DIST_URL = "https://raw.githubusercontent.com/lbryio/lbry-web-ui/%s/dist.zip" % args.branch

    def getui(ui_dir=None):
        if ui_dir:
            if os.path.isdir(ui_dir):
                log.info("Using user specified UI directory: " + str(ui_dir))
                ui_version_info = "user-specified"
                return defer.succeed([ui_dir, ui_version_info])
            else:
                log.info("User specified UI directory doesn't exist: " + str(ui_dir))

        def download_ui(dest_dir, ui_version):
            url = urlopen(DIST_URL)
            z = ZipFile(StringIO(url.read()))
            names = [i for i in z.namelist() if '.DS_Store' not in i and '__MACOSX' not in i]
            z.extractall(dest_dir, members=names)
            return defer.succeed([dest_dir, ui_version])

        data_dir = user_data_dir("LBRY")
        version_dir = os.path.join(data_dir, "ui_version_history")

        git_version = subprocess.check_output(GIT_CMD_STRING, shell=True)
        if not git_version:
            log.info("You should have been notified to install xcode command line tools, once it's installed you can start LBRY")
            sys.exit(0)

        ui_version_info = git_version

        if not os.path.isdir(data_dir):
            os.mkdir(data_dir)

        if not os.path.isdir(os.path.join(data_dir, "ui_version_history")):
            os.mkdir(version_dir)

        if not os.path.isfile(os.path.join(version_dir, git_version)):
            f = open(os.path.join(version_dir, git_version), "w")
            version_message = "[" + str(datetime.now()) + "] Updating UI --> " + git_version
            f.write(version_message)
            f.close()
            log.info(version_message)

            if os.path.isdir(os.path.join(data_dir, "lbry-web-ui")):
                shutil.rmtree(os.path.join(data_dir, "lbry-web-ui"))
        else:
            version_message = "[" + str(datetime.now()) + "] UI version " + git_version + " up to date"
            log.info(version_message)

        if os.path.isdir(os.path.join(data_dir, "lbry-web-ui")):
            return defer.succeed([os.path.join(data_dir, "lbry-web-ui"), ui_version_info])
        else:
            return download_ui(os.path.join(data_dir, "lbry-web-ui"), ui_version_info)

    def setupserver(ui_dir, ui_version):
        root = LBRYindex(ui_dir)
        root.putChild("css", static.File(os.path.join(ui_dir, "css")))
        root.putChild("font", static.File(os.path.join(ui_dir, "font")))
        root.putChild("img", static.File(os.path.join(ui_dir, "img")))
        root.putChild("js", static.File(os.path.join(ui_dir, "js")))
        root.putChild("view", LBRYFileRender())
        return defer.succeed([root, ui_version])

    def setupapi(root, wallet, ui_version):
        daemon = LBRYDaemon(ui_version, wallet_type=wallet)
        root.putChild(API_ADDRESS, daemon)
        reactor.listenTCP(API_PORT, server.Site(root), interface=API_INTERFACE)
        return daemon.setup()

    if test_internet_connection():
        d = getui(args.ui)
        d.addCallback(lambda r: setupserver(r[0], r[1]))
        d.addCallback(lambda r: setupapi(r[0], args.wallet, r[1]))
        d.addCallback(lambda _: webbrowser.open(UI_ADDRESS))
        reactor.run()
    else:
        log.info("Not connected to internet, unable to start")
        return
