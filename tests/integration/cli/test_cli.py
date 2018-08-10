import contextlib
import unittest
from io import StringIO
from twisted.internet import defer

from lbrynet import conf
from lbrynet import cli
from lbrynet.daemon.Components import DATABASE_COMPONENT, BLOB_COMPONENT, HEADERS_COMPONENT, WALLET_COMPONENT, \
    DHT_COMPONENT, HASH_ANNOUNCER_COMPONENT, STREAM_IDENTIFIER_COMPONENT, FILE_MANAGER_COMPONENT, \
    PEER_PROTOCOL_SERVER_COMPONENT, REFLECTOR_COMPONENT, UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT, \
    RATE_LIMITER_COMPONENT, PAYMENT_RATE_COMPONENT
from lbrynet.daemon.Daemon import Daemon


class AuthCLIIntegrationTest(unittest.TestCase):
    @defer.inlineCallbacks
    def setUp(self):
        skip = [
            DATABASE_COMPONENT, BLOB_COMPONENT, HEADERS_COMPONENT, WALLET_COMPONENT,
            DHT_COMPONENT, HASH_ANNOUNCER_COMPONENT, STREAM_IDENTIFIER_COMPONENT, FILE_MANAGER_COMPONENT,
            PEER_PROTOCOL_SERVER_COMPONENT, REFLECTOR_COMPONENT, UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT,
            RATE_LIMITER_COMPONENT, PAYMENT_RATE_COMPONENT
        ]
        conf.initialize_settings(load_conf_file=False)
        conf.settings['use_auth_http'] = True
        conf.settings["components_to_skip"] = skip
        conf.settings.initialize_post_conf_load()
        Daemon.component_attributes = {}
        self.daemon = Daemon()
        yield self.daemon.start_listening()

    def test_cli_status_command_with_auth(self):
        actual_output = StringIO()
        with contextlib.redirect_stdout(actual_output):
            cli.main(["status"])
        actual_output = actual_output.getvalue()
        self.assertIn("connection_status", actual_output)

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.daemon._shutdown()
