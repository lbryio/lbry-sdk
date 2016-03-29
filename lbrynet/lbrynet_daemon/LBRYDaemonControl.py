import argparse
import logging
import tempfile
import os
import shutil

from StringIO import StringIO
from zipfile import ZipFile
from urllib import urlopen

from twisted.web import server, static
from twisted.internet import reactor, defer
from jsonrpc.proxy import JSONRPCProxy

from lbrynet.lbrynet_daemon.LBRYDaemon import LBRYDaemon, LBRYindex, LBRYFileRender
from lbrynet.conf import API_CONNECTION_STRING, API_INTERFACE, API_ADDRESS, API_PORT, DEFAULT_WALLET

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


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
                        help="temp or path, default temp, path is the path of the dist folder",
                        default="temp")

    try:
        JSONRPCProxy.from_url(API_CONNECTION_STRING).is_running()
        log.info("lbrynet-daemon is already running")
        return
    except:
        pass

    log.info("Starting lbrynet-daemon from command line")

    args = parser.parse_args()
    download_ui = True

    if args.ui != "temp" and os.path.isdir(args.ui):
        download_ui = False
        ui_dir = args.ui
        log.info("Using user specified UI directory: " + str(ui_dir))

    if args.ui == "temp" or download_ui:
        log.info("Downloading current web ui to temp directory")
        ui_dir = tempfile.mkdtemp()
        url = urlopen("https://rawgit.com/lbryio/lbry-web-ui/master/dist.zip")
        z = ZipFile(StringIO(url.read()))
        z.extractall(ui_dir)

    daemon = LBRYDaemon()
    daemon.setup(args.wallet, args.update)

    root = LBRYindex(ui_dir)
    root.putChild("css", static.File(os.path.join(ui_dir, "css")))
    root.putChild("font", static.File(os.path.join(ui_dir, "font")))
    root.putChild("img", static.File(os.path.join(ui_dir, "img")))
    root.putChild("js", static.File(os.path.join(ui_dir, "js")))
    root.putChild(API_ADDRESS, daemon)
    root.putChild("view", LBRYFileRender())

    reactor.listenTCP(API_PORT, server.Site(root), interface=API_INTERFACE)
    reactor.run()

    if download_ui:
        shutil.rmtree(ui_dir)