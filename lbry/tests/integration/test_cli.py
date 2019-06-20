import contextlib
from io import StringIO
from torba.testcase import AsyncioTestCase

from lbrynet.conf import Config
from lbrynet.extras import cli
from lbrynet.extras.daemon.Components import (
    DATABASE_COMPONENT, BLOB_COMPONENT, HEADERS_COMPONENT, WALLET_COMPONENT, DHT_COMPONENT,
    HASH_ANNOUNCER_COMPONENT, STREAM_MANAGER_COMPONENT, PEER_PROTOCOL_SERVER_COMPONENT,
    UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT
)
from lbrynet.extras.daemon.Daemon import Daemon


class CLIIntegrationTest(AsyncioTestCase):

    async def asyncSetUp(self):
        conf = Config()
        conf.data_dir = '/tmp'
        conf.share_usage_data = False
        conf.api = 'localhost:5299'
        conf.components_to_skip = (
            DATABASE_COMPONENT, BLOB_COMPONENT, HEADERS_COMPONENT, WALLET_COMPONENT, DHT_COMPONENT,
            HASH_ANNOUNCER_COMPONENT, STREAM_MANAGER_COMPONENT, PEER_PROTOCOL_SERVER_COMPONENT,
            UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT
        )
        Daemon.component_attributes = {}
        self.daemon = Daemon(conf)
        await self.daemon.start()

    async def asyncTearDown(self):
        await self.daemon.stop(shutdown_runner=False)

    def test_cli_status_command_with_auth(self):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            cli.main(["--api", "localhost:5299", "status"])
        actual_output = actual_output.getvalue()
        self.assertIn("connection_status", actual_output)
