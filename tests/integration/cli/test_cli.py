import contextlib
from io import StringIO
from unittest import skip
from torba.testcase import AsyncioTestCase

from lbrynet import conf
from lbrynet.extras import cli
from lbrynet.extras.daemon.Components import DATABASE_COMPONENT, BLOB_COMPONENT, HEADERS_COMPONENT, WALLET_COMPONENT, \
    DHT_COMPONENT, HASH_ANNOUNCER_COMPONENT, FILE_MANAGER_COMPONENT, \
    PEER_PROTOCOL_SERVER_COMPONENT, REFLECTOR_COMPONENT, UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT, \
    RATE_LIMITER_COMPONENT, PAYMENT_RATE_COMPONENT
from lbrynet.extras.daemon.Daemon import Daemon


class FakeAnalytics:

    @property
    def is_started(self):
        return True

    async def send_server_startup_success(self):
        pass

    async def send_server_startup(self):
        pass

    def shutdown(self):
        pass


class CLIIntegrationTest(AsyncioTestCase):
    USE_AUTH = False

    async def asyncSetUp(self):
        skip = [
            DATABASE_COMPONENT, BLOB_COMPONENT, HEADERS_COMPONENT, WALLET_COMPONENT,
            DHT_COMPONENT, HASH_ANNOUNCER_COMPONENT, FILE_MANAGER_COMPONENT,
            PEER_PROTOCOL_SERVER_COMPONENT, REFLECTOR_COMPONENT, UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT,
            RATE_LIMITER_COMPONENT, PAYMENT_RATE_COMPONENT
        ]
        conf.initialize_settings(load_conf_file=False)
        conf.settings['api_port'] = 5299
        conf.settings['use_auth_http'] = self.USE_AUTH
        conf.settings['components_to_skip'] = skip
        conf.settings.initialize_post_conf_load()
        Daemon.component_attributes = {}
        self.daemon = Daemon(analytics_manager=FakeAnalytics())
        await self.daemon.start_listening()

    async def asyncTearDown(self):
        await self.daemon.shutdown()


@skip
class AuthenticatedCLITest(CLIIntegrationTest):
    USE_AUTH = True

    def test_cli_status_command_with_auth(self):
        self.assertTrue(self.daemon._use_authentication)
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            cli.main(["status"])
        actual_output = actual_output.getvalue()
        self.assertIn("connection_status", actual_output)


class UnauthenticatedCLITest(CLIIntegrationTest):
    USE_AUTH = False

    def test_cli_status_command_with_auth(self):
        self.assertFalse(self.daemon._use_authentication)
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            cli.main(["status"])
        actual_output = actual_output.getvalue()
        self.assertIn("connection_status", actual_output)
