import logging
import os
import sys

from appdirs import user_data_dir
from twisted.internet import defer
from lbrynet.lbrynet_daemon.Daemon import Daemon
from lbrynet.lbrynet_daemon.Resources import LBRYindex, HostedEncryptedFile, EncryptedFileUpload
from lbrynet.conf import API_ADDRESS, DEFAULT_UI_BRANCH, LOG_FILE_NAME


# TODO: omg, this code is essentially duplicated in Daemon
if sys.platform != "darwin":
    data_dir = os.path.join(os.path.expanduser("~"), ".lbrynet")
else:
    data_dir = user_data_dir("LBRY")
if not os.path.isdir(data_dir):
    os.mkdir(data_dir)

lbrynet_log = os.path.join(data_dir, LOG_FILE_NAME)
log = logging.getLogger(__name__)


class DaemonServer(object):
    def _setup_server(self, wallet):
        self.root = LBRYindex(os.path.join(os.path.join(data_dir, "lbry-ui"), "active"))
        self._api = Daemon(self.root, wallet_type=wallet)
        self.root.putChild("view", HostedEncryptedFile(self._api))
        self.root.putChild("upload", EncryptedFileUpload(self._api))
        self.root.putChild(API_ADDRESS, self._api)
        return defer.succeed(True)

    def start(self, branch=DEFAULT_UI_BRANCH, user_specified=False, branch_specified=False, wallet=None):
        d = self._setup_server(wallet)
        d.addCallback(lambda _: self._api.setup(branch, user_specified, branch_specified))
        return d
