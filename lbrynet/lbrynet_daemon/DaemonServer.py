import logging
import os

from twisted.internet import defer

from lbrynet.conf import settings
from lbrynet.lbrynet_daemon.Daemon import Daemon
from lbrynet.lbrynet_daemon.Resources import LBRYindex, HostedEncryptedFile, EncryptedFileUpload
from lbrynet.conf import settings


log = logging.getLogger(__name__)


class DaemonServer(object):
    def _setup_server(self):
        ui_path = os.path.join(settings.ensure_data_dir(), "lbry-ui", "active")
        self.root = LBRYindex(ui_path)
        self._api = Daemon(self.root)
        self.root.putChild("view", HostedEncryptedFile(self._api))
        self.root.putChild("upload", EncryptedFileUpload(self._api))
        self.root.putChild(settings.API_ADDRESS, self._api)
        return defer.succeed(True)

    def start(self):
        d = self._setup_server()
        d.addCallback(lambda _: self._api.setup())
        return d
