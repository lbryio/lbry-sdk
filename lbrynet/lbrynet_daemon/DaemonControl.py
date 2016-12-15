import argparse
import logging.handlers
import webbrowser

from twisted.internet import defer, reactor
from jsonrpc.proxy import JSONRPCProxy

from lbrynet import analytics
from lbrynet import conf
from lbrynet.core import log_support
from lbrynet.core import utils
from lbrynet.lbrynet_daemon.DaemonServer import DaemonServer
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
                        help="lbryum or ptc for testing, default lbryum",
                        type=str,
                        default=conf.LBRYUM_WALLET)
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

    conf.update_settings_from_file()
    update_settings_from_args(args)

    lbrynet_log = settings.get_log_filename()
    log_support.configure_logging(lbrynet_log, args.logtoconsole, args.verbose)
    log.debug('Final Settings: %s', settings.get_dict())

    try:
        log.debug('Checking for an existing lbrynet daemon instance')
        JSONRPCProxy.from_url(settings.API_CONNECTION_STRING).is_running()
        log.info("lbrynet-daemon is already running")
        if not args.logtoconsole:
            print "lbrynet-daemon is already running"
        return
    except Exception:
        log.debug('No lbrynet instance found, continuing to start')
        pass

    log.info("Starting lbrynet-daemon from command line")

    if not args.logtoconsole and not args.quiet:
        print "Starting lbrynet-daemon from command line"
        print "To view activity, view the log file here: " + lbrynet_log
        print "Web UI is available at http://%s:%i" % (settings.API_INTERFACE, settings.api_port)
        print "JSONRPC API is available at " + settings.API_CONNECTION_STRING
        print "To quit press ctrl-c or call 'stop' via the API"

    if test_internet_connection():
        analytics_manager = analytics.Manager.new_instance()
        analytics_manager.send_server_startup()
        start_server_and_listen(args.launchui, args.useauth, analytics_manager)
        reactor.run()

        if not args.logtoconsole and not args.quiet:
            print "\nClosing lbrynet-daemon"
    else:
        log.info("Not connected to internet, unable to start")
        if not args.logtoconsole:
            print "Not connected to internet, unable to start"
        return


def update_settings_from_args(args):
    to_pass = {}
    if args.ui:
        to_pass['local_ui_path'] = args.ui
    if args.branch:
        to_pass['ui_branch'] = args.branch
    to_pass['use_auth_http'] = args.useauth
    to_pass['wallet'] = args.wallet
    settings.update(to_pass)


def kill(failure, analytics_manager):
    analytics_manager.send_server_startup_error(failure.getErrorMessage() + " " + str(failure))
    reactor.callFromThread(reactor.stop)


def start_server_and_listen(launchui, use_auth, analytics_manager):
    """The primary entry point for launching the daemon.

    Args:
        launchui: set to true to open a browser window
        use_auth: set to true to enable http authentication
        analytics_manager: to send analytics
    """
    daemon_server = DaemonServer(analytics_manager)
    d = daemon_server.start(use_auth)
    if launchui:
        d.addCallback(lambda _: webbrowser.open(settings.UI_ADDRESS))
    d.addCallback(lambda _: analytics_manager.send_server_startup_success())
    d.addErrback(log.fail(kill, analytics_manager), 'Failed to startup')


if __name__ == "__main__":
    start()
