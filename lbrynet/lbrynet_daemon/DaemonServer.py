import logging
import os

from twisted.web import server, guard
from twisted.internet import defer, reactor, error
from twisted.cred import portal

from lbrynet import conf
from lbrynet.lbrynet_daemon.Daemon import Daemon
from lbrynet.lbrynet_daemon.Resources import LBRYindex, HostedEncryptedFile, EncryptedFileUpload
from lbrynet.lbrynet_daemon.auth.auth import PasswordChecker, HttpPasswordRealm
from lbrynet.lbrynet_daemon.auth.util import initialize_api_key_file
from lbrynet.lbrynet_daemon.DaemonRequest import DaemonRequest


log = logging.getLogger(__name__)


class DaemonServer(object):
    def __init__(self, analytics_manager=None):
        self._api = None
        self.root = None
        self.server_port = None
        self.analytics_manager = analytics_manager

    def _setup_server(self, use_auth):
        ui_path = os.path.join(conf.settings.ensure_data_dir(), "lbry-ui", "active")
        self.root = LBRYindex(ui_path)
        self._api = Daemon(self.root, self.analytics_manager)
        self.root.putChild("view", HostedEncryptedFile(self._api))
        self.root.putChild("upload", EncryptedFileUpload(self._api))
        self.root.putChild(conf.settings['API_ADDRESS'], self._api)

        lbrynet_server = server.Site(get_site_base(use_auth, self.root))
        lbrynet_server.requestFactory = DaemonRequest

        try:
            self.server_port = reactor.listenTCP(
                conf.settings['api_port'], lbrynet_server, interface=conf.settings['api_host'])
        except error.CannotListenError:
            log.info('Daemon already running, exiting app')
            raise

        return defer.succeed(True)

    @defer.inlineCallbacks
    def start(self, use_auth, launch_ui=False):
        yield self._setup_server(use_auth)
        yield self._api.setup(launch_ui)

    @defer.inlineCallbacks
    def stop(self):
        if self._api is not None:
            yield self._api._shutdown()
        if self.server_port is not None:
            yield self.server_port.stopListening()

def get_site_base(use_auth, root):
    if use_auth:
        log.info("Using authenticated API")
        return create_auth_session(root)
    else:
        log.info("Using non-authenticated API")
        return server.Site(root)


def create_auth_session(root):
    pw_path = os.path.join(conf.settings['data_dir'], ".api_keys")
    initialize_api_key_file(pw_path)
    checker = PasswordChecker.load_file(pw_path)
    realm = HttpPasswordRealm(root)
    portal_to_realm = portal.Portal(realm, [checker, ])
    factory = guard.BasicCredentialFactory('Login to lbrynet api')
    _lbrynet_server = guard.HTTPAuthSessionWrapper(portal_to_realm, [factory, ])
    return _lbrynet_server
