import os
import sys

# Set SSL_CERT_FILE env variable for Twisted SSL verification on Windows
# This needs to happen before anything else
if 'win' in sys.platform:
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()

from lbrynet.core import log_support

import argparse
import logging.handlers

from twisted.internet import reactor

from lbrynet import conf
from lbrynet.core import utils, system_info
from lbrynet.daemon.Daemon import Daemon

log = logging.getLogger(__name__)


def test_internet_connection():
    return utils.check_connection()


def start(argv=None, conf_path=None):
    if conf_path is not None:
        conf.conf_file = conf_path

    conf.initialize_settings()

    parser = argparse.ArgumentParser()
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

    args = parser.parse_args(argv)
    if args.useauth:
        conf.settings.update({'use_auth_http': args.useauth}, data_types=(conf.TYPE_CLI,))

    if args.version:
        version = system_info.get_platform(get_ip=False)
        version['installation_id'] = conf.settings.installation_id
        print(utils.json_dumps_pretty(version))
        return

    lbrynet_log = conf.settings.get_log_filename()
    log_support.configure_logging(lbrynet_log, not args.quiet, args.verbose)
    log_support.configure_loggly_handler()
    log.debug('Final Settings: %s', conf.settings.get_current_settings_dict())

    log.info("Starting lbrynet-daemon from command line")

    if test_internet_connection():
        daemon = Daemon()
        daemon.start_listening()
        reactor.run()
    else:
        log.info("Not connected to internet, unable to start")
