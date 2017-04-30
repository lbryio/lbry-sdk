from lbrynet.core import log_support

import argparse
import logging.handlers

from twisted.internet import defer, reactor
from jsonrpc.proxy import JSONRPCProxy

from lbrynet import analytics
from lbrynet import conf
from lbrynet.core import utils, system_info
from lbrynet.lbrynet_daemon.auth.client import LBRYAPIClient
from lbrynet.lbrynet_daemon.DaemonServer import DaemonServer

log = logging.getLogger(__name__)


def test_internet_connection():
    return utils.check_connection()


def stop():
    conf.initialize_settings()
    log_support.configure_console()
    try:
        LBRYAPIClient.get_client().call('stop')
    except Exception:
        log.exception('Failed to stop deamon')
    else:
        log.info("Shutting down lbrynet-daemon from command line")


def start():
    conf.initialize_settings()

    parser = argparse.ArgumentParser(description="Launch lbrynet-daemon")
    parser.add_argument(
        "--wallet",
        help="lbryum or ptc for testing, default lbryum",
        type=str,
        default=conf.settings['wallet']
    )
    parser.add_argument(
        "--ui", help="path to custom UI folder", default=None
    )
    parser.add_argument(
        "--branch",
        help='Branch of lbry-web-ui repo to use, defaults to {}'.format(conf.settings['ui_branch']),
        default=conf.settings['ui_branch']
    )
    parser.add_argument(
        '--launch-ui', dest='launchui', action="store_true"
    )
    parser.add_argument(
        "--http-auth", dest="useauth", action="store_true", default=conf.settings['use_auth_http']
    )
    parser.add_argument(
        '--quiet', dest='quiet', action="store_true",
        help='Disable all console output.'
    )
    parser.add_argument(
        '--verbose', nargs="*",
        help=('Enable debug output. Optionally specify loggers for which debug output '
              'should selectively be applied.')
    )
    parser.add_argument(
        '--version', action="store_true",
        help='Show daemon version and quit'
    )

    args = parser.parse_args()
    update_settings_from_args(args)

    if args.version:
        version = system_info.get_platform(get_ip=False)
        version['installation_id'] = conf.settings.installation_id
        print utils.json_dumps_pretty(version)
        return

    lbrynet_log = conf.settings.get_log_filename()
    log_support.configure_logging(lbrynet_log, not args.quiet, args.verbose)
    log.debug('Final Settings: %s', conf.settings.get_current_settings_dict())

    try:
        log.debug('Checking for an existing lbrynet daemon instance')
        JSONRPCProxy.from_url(conf.settings.get_api_connection_string()).is_running()
        log.info("lbrynet-daemon is already running")
        return
    except Exception:
        log.debug('No lbrynet instance found, continuing to start')

    log.info("Starting lbrynet-daemon from command line")

    if test_internet_connection():
        analytics_manager = analytics.Manager.new_instance()
        start_server_and_listen(args.launchui, args.useauth, analytics_manager)
        reactor.run()
    else:
        log.info("Not connected to internet, unable to start")


def update_settings_from_args(args):
    cli_settings = {}
    if args.ui:
        cli_settings['local_ui_path'] = args.ui
    if args.branch:
        cli_settings['ui_branch'] = args.branch
    cli_settings['use_auth_http'] = args.useauth
    cli_settings['wallet'] = args.wallet
    conf.settings.update(cli_settings, data_types=(conf.TYPE_CLI,))


@defer.inlineCallbacks
def start_server_and_listen(launchui, use_auth, analytics_manager, max_tries=5):
    """The primary entry point for launching the daemon.

    Args:
        launchui: set to true to open a browser window
        use_auth: set to true to enable http authentication
        analytics_manager: to send analytics
    """
    analytics_manager.send_server_startup()
    daemon_server = DaemonServer(analytics_manager)
    try:
        yield daemon_server.start(use_auth, launchui)
        analytics_manager.send_server_startup_success()
    except Exception as e:
        log.exception('Failed to startup')
        yield daemon_server.stop()
        analytics_manager.send_server_startup_error(str(e))
        reactor.fireSystemEvent("shutdown")


if __name__ == "__main__":
    start()
