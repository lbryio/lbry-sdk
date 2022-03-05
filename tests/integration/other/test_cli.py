import contextlib
import os
import tempfile
from io import StringIO
from lbry.testcase import AsyncioTestCase

from lbry.conf import Config
from lbry.extras import cli
from lbry.extras.daemon.components import (
    DATABASE_COMPONENT, DISK_SPACE_COMPONENT, BLOB_COMPONENT, WALLET_COMPONENT, DHT_COMPONENT,
    HASH_ANNOUNCER_COMPONENT, FILE_MANAGER_COMPONENT, PEER_PROTOCOL_SERVER_COMPONENT,
    UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT, WALLET_SERVER_PAYMENTS_COMPONENT,
    LIBTORRENT_COMPONENT, BACKGROUND_DOWNLOADER_COMPONENT, TRACKER_ANNOUNCER_COMPONENT
)
from lbry.extras.daemon.daemon import Daemon


class CLIIntegrationTest(AsyncioTestCase):

    async def asyncSetUp(self):
        conf = Config()
        conf.data_dir = '/tmp'
        conf.share_usage_data = False
        conf.api = 'localhost:5299'
        conf.components_to_skip = (
            DATABASE_COMPONENT, DISK_SPACE_COMPONENT, BLOB_COMPONENT, WALLET_COMPONENT, DHT_COMPONENT,
            HASH_ANNOUNCER_COMPONENT, FILE_MANAGER_COMPONENT, PEER_PROTOCOL_SERVER_COMPONENT,
            UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT, WALLET_SERVER_PAYMENTS_COMPONENT,
            LIBTORRENT_COMPONENT, BACKGROUND_DOWNLOADER_COMPONENT, TRACKER_ANNOUNCER_COMPONENT
        )
        Daemon.component_attributes = {}
        self.daemon = Daemon(conf)
        await self.daemon.start()
        self.addCleanup(self.daemon.stop)

    def test_cli_status_command_with_auth(self):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            cli.main(["--api", "localhost:5299", "status"])
        actual_output = actual_output.getvalue()
        self.assertIn("is_running", actual_output)

    def test_when_download_dir_non_writable_on_start_then_daemon_dies_with_helpful_msg(self):
        with tempfile.TemporaryDirectory() as download_dir:
            os.chmod(download_dir, mode=0o555)  # makes download dir non-writable, readable and executable
            with self.assertRaisesRegex(PermissionError, f"The following directory is not writable: {download_dir}"):
                cli.main(["start", "--download-dir", download_dir])
