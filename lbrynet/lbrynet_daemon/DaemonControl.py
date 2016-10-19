import argparse
import logging.handlers
import os
import webbrowser
import sys
import socket

from twisted.web import server, guard
from twisted.internet import defer, reactor
from twisted.cred import portal

from jsonrpc.proxy import JSONRPCProxy

from lbrynet.core import log_support, utils
from lbrynet.lbrynet_daemon.auth.auth import PasswordChecker, HttpPasswordRealm
from lbrynet.lbrynet_daemon.auth.util import initialize_api_key_file
from lbrynet.lbrynet_daemon.DaemonServer import DaemonServer
from lbrynet.lbrynet_daemon.DaemonRequest import DaemonRequest
from lbrynet import settings

log_dir = settings.DATA_DIR

if not os.path.isdir(log_dir):
    os.mkdir(log_dir)

lbrynet_log = os.path.join(log_dir, settings.LOG_FILE_NAME)
log = logging.getLogger(__name__)


REMOTE_SERVER = "www.google.com"

if getattr(sys, 'frozen', False) and os.name == "nt":
    os.environ["REQUESTS_CA_BUNDLE"] = os.path.join(os.path.dirname(sys.executable), "cacert.pem")


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
    d.addCallback(lambda _: JSONRPCProxy.from_url(settings.API_CONNECTION_STRING).stop())
    d.addCallbacks(lambda _: _disp_shutdown(), lambda _: _disp_not_running())
    d.callback(None)


def start():
    parser = argparse.ArgumentParser(description="Launch lbrynet-daemon")
    parser.add_argument("--wallet",
                        help="lbrycrd or lbryum, default lbryum",
                        type=str,
                        default='lbryum')

    parser.add_argument("--ui",
                        help="path to custom UI folder",
                        default=None)

    parser.add_argument("--branch",
                        help="Branch of lbry-web-ui repo to use, defaults on master",
                        default=settings.UI_BRANCH)

    parser.add_argument("--http-auth",
                        dest="useauth",
                        action="store_true")

    parser.add_argument('--no-launch',
                        dest='launchui',
                        action="store_false")

    parser.add_argument('--log-to-console',
                        dest='logtoconsole',
                        action="store_true")

    parser.add_argument('--quiet',
                        dest='quiet',
                        action="store_true")

    parser.add_argument('--verbose',
                        action='store_true',
                        help='enable more debug output for the console')

    parser.set_defaults(branch=False, launchui=True, logtoconsole=False, quiet=False, useauth=settings.USE_AUTH_HTTP)
    args = parser.parse_args()

    log_support.configure_file_handler(lbrynet_log)
    log_support.configure_loggly_handler()
    if args.logtoconsole:
        log_support.configure_console(level='DEBUG')
    log_support.disable_third_party_loggers()
    if not args.verbose:
        log_support.disable_noisy_loggers()

    to_pass = {}
    settings_path = os.path.join(settings.DATA_DIR, "daemon_settings.yml")
    if os.path.isfile(settings_path):
        to_pass.update(utils.load_settings(settings_path))
        log.info("Loaded settings file")
    if args.ui:
        to_pass.update({'local_ui_path': args.ui})
    if args.branch:
        to_pass.update({'UI_BRANCH': args.branch})
    to_pass.update({'USE_AUTH_HTTP': args.useauth})
    to_pass.update({'WALLET': args.wallet})
    settings.update(to_pass)

    try:
        JSONRPCProxy.from_url(settings.API_CONNECTION_STRING).is_running()
        log.info("lbrynet-daemon is already running")
        if not args.logtoconsole:
            print "lbrynet-daemon is already running"
        if args.launchui:
            webbrowser.open(settings.UI_ADDRESS)
        return
    except:
        pass

    log.info("Starting lbrynet-daemon from command line")

    if not args.logtoconsole and not args.quiet:
        print "Starting lbrynet-daemon from command line"
        print "To view activity, view the log file here: " + lbrynet_log
        print "Web UI is available at http://%s:%i" % (settings.API_INTERFACE, settings.API_PORT)
        print "JSONRPC API is available at " + settings.API_CONNECTION_STRING
        print "To quit press ctrl-c or call 'stop' via the API"

    if test_internet_connection():
        lbry = DaemonServer()

        d = lbry.start(args.useauth)
        if args.launchui:
            d.addCallback(lambda _: webbrowser.open(settings.UI_ADDRESS))

        if settings.USE_AUTH_HTTP:
            log.info("Using authenticated API")
            pw_path = os.path.join(settings.DATA_DIR, ".api_keys")
            initialize_api_key_file(pw_path)
            checker = PasswordChecker.load_file(pw_path)
            realm = HttpPasswordRealm(lbry.root)
            portal_to_realm = portal.Portal(realm, [checker, ])
            factory = guard.BasicCredentialFactory('Login to lbrynet api')
            _lbrynet_server = guard.HTTPAuthSessionWrapper(portal_to_realm, [factory, ])
        else:
            log.info("Using non-authenticated API")
            _lbrynet_server = server.Site(lbry.root)

        lbrynet_server = server.Site(_lbrynet_server)
        lbrynet_server.requestFactory = DaemonRequest
        reactor.listenTCP(settings.API_PORT, lbrynet_server, interface=settings.API_INTERFACE)
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