import argparse
import logging.handlers
import webbrowser

from twisted.web import server, guard
from twisted.internet import defer, reactor
from twisted.cred import portal

from jsonrpc.proxy import JSONRPCProxy

from lbrynet.lbrynet_daemon.auth.auth import PasswordChecker, HttpPasswordRealm
from lbrynet.lbrynet_daemon.auth.util import initialize_api_key_file
from lbrynet.core import log_support
from lbrynet.core import utils
from lbrynet.lbrynet_daemon.DaemonServer import DaemonServer
from lbrynet.lbrynet_daemon.DaemonRequest import DaemonRequest
from lbrynet.conf import settings


log = logging.getLogger(__name__)


def test_internet_connection():
    return utils.check_connection()


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
    parser.add_argument("--ui", help="path to custom UI folder", default=None)
    parser.add_argument(
        "--branch",
        help='Branch of lbry-web-ui repo to use, defaults to {}'.format(settings.ui_branch),
        default=settings.ui_branch)
    parser.add_argument('--no-launch', dest='launchui', action="store_false")
    parser.add_argument("--http-auth", dest="useauth", action="store_true")
    parser.add_argument(
        '--log-to-console', dest='logtoconsole', action='store_true',
        help=('Set to enable console logging. Set the --verbose flag '
              ' to enable more detailed console logging'))
    parser.add_argument(
        '--quiet', dest='quiet', action="store_true",
        help=('If log-to-console is not set, setting this disables all console output. '
              'If log-to-console is set, this argument is ignored'))
    parser.add_argument(
        '--verbose', nargs="*",
        help=('Enable debug output. Optionally specify loggers for which debug output '
              'should selectively be applied.'))
    args = parser.parse_args()

    utils.setup_certs_for_windows()
    lbrynet_log = log_support.get_log_file()
    log_support.configure_logging(lbrynet_log, args.logtoconsole, args.verbose)

    to_pass = {}
    settings_path = os.path.join(settings.data_dir, "daemon_settings.yml")
    if os.path.isfile(settings_path):
        to_pass.update(utils.load_settings(settings_path))
        log.info("Loaded settings file")
    if args.ui:
        to_pass.update({'local_ui_path': args.ui})
    if args.branch:
        to_pass.update({'ui_branch': args.branch})
    to_pass.update({'use_auth_http': args.useauth})
    to_pass.update({'wallet': args.wallet})
    print to_pass
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
        print "Web UI is available at http://%s:%i" % (settings.API_INTERFACE, settings.api_port)
        print "JSONRPC API is available at " + settings.API_CONNECTION_STRING
        print "To quit press ctrl-c or call 'stop' via the API"

    if test_internet_connection():
        lbry = DaemonServer()

        d = lbry.start()
        if args.launchui:
            d.addCallback(lambda _: webbrowser.open(settings.UI_ADDRESS))
        d.addErrback(log_and_kill)

        if settings.use_auth_http:
            log.info("Using authenticated API")
            pw_path = os.path.join(settings.data_dir, ".api_keys")
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
        reactor.listenTCP(settings.api_port, lbrynet_server, interface=settings.API_INTERFACE)
        reactor.run()

        if not args.logtoconsole and not args.quiet:
            print "\nClosing lbrynet-daemon"
    else:
        log.info("Not connected to internet, unable to start")
        if not args.logtoconsole:
            print "Not connected to internet, unable to start"
        return


def log_and_kill(failure):
    log_support.failure(failure, log, 'Failed to startup: %s')
    reactor.stop()


if __name__ == "__main__":
    start()
