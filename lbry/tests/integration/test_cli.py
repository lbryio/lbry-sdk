import contextlib
import asyncio
import logging
from io import StringIO
from torba.testcase import AsyncioTestCase

from lbry.conf import Config
from lbry.extras import cli
from lbry.extras.daemon.Components import (
    DATABASE_COMPONENT, BLOB_COMPONENT, HEADERS_COMPONENT, WALLET_COMPONENT, DHT_COMPONENT,
    HASH_ANNOUNCER_COMPONENT, STREAM_MANAGER_COMPONENT, PEER_PROTOCOL_SERVER_COMPONENT,
    UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT
)
from lbry.extras.daemon.Daemon import Daemon


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

    def test_setup_logging(self):
        def setup(argv):
            parser = cli.get_argument_parser()
            args, command_args = parser.parse_known_args(argv)
            loop = asyncio.get_event_loop()
            conf = Config.create_from_arguments(args)
            cli.setup_logging(args, conf, loop)

        setup(["start"])
        self.assertTrue(logging.getLogger("lbry").isEnabledFor(logging.INFO))
        self.assertFalse(logging.getLogger("lbry").isEnabledFor(logging.DEBUG))

        setup(["start", "--verbose"])
        self.assertTrue(logging.getLogger("lbry").isEnabledFor(logging.DEBUG))
        self.assertTrue(logging.getLogger("lbry").isEnabledFor(logging.INFO))
        self.assertFalse(logging.getLogger("torba").isEnabledFor(logging.DEBUG))

        setup(["start", "--verbose", "lbry.extras", "lbry.wallet", "torba.client"])
        self.assertTrue(logging.getLogger("lbry.extras").isEnabledFor(logging.DEBUG))
        self.assertTrue(logging.getLogger("lbry.wallet").isEnabledFor(logging.DEBUG))
        self.assertTrue(logging.getLogger("torba.client").isEnabledFor(logging.DEBUG))
        self.assertFalse(logging.getLogger("lbry").isEnabledFor(logging.DEBUG))
        self.assertFalse(logging.getLogger("torba").isEnabledFor(logging.DEBUG))
