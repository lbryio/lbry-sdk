import argparse
import logging

from twisted.web import server
from twisted.internet import reactor, defer
from jsonrpc.proxy import JSONRPCProxy

from lbrynet.lbrynet_daemon.LBRYDaemon import LBRYDaemon, LBRYindex, LBRYDaemonWeb, LBRYFilePage
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

    log.info("Starting lbrynet-daemon from command line")

    args = parser.parse_args()
    daemon = LBRYDaemon()
    daemon.setup(args.wallet, args.update)

    root = LBRYindex()
    root.putChild("", root)
    root.putChild("webapi", LBRYDaemonWeb())
    root.putChild(API_ADDRESS, daemon)
    root.putChild("myfiles", LBRYFilePage())
    reactor.listenTCP(API_PORT, server.Site(root), interface=API_INTERFACE)
    reactor.run()
