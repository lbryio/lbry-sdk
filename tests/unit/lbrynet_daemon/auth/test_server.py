import mock
import requests
from twisted.trial import unittest

from lbrynet import conf
from lbrynet.lbrynet_daemon.auth import server


class AuthJSONRPCServerTest(unittest.TestCase):
    # TODO: move to using a base class for tests
    # and add useful general utilities like this
    # onto it.
    def setUp(self):
        self.server = server.AuthJSONRPCServer(False)

    def _set_setting(self, attr, value):
        original = getattr(conf.settings, attr)
        setattr(conf.settings, attr, value)
        self.addCleanup(lambda: setattr(conf.settings, attr, original))

    def test_get_server_port(self):
        self.assertSequenceEqual(
            ('example.com', 80), self.server.get_server_port('http://example.com'))
        self.assertSequenceEqual(
            ('example.com', 1234), self.server.get_server_port('http://example.com:1234'))

    def test_foreign_origin_is_rejected(self):
        request = mock.Mock(['getHeader'])
        request.getHeader = mock.Mock(return_value='http://example.com')
        self.assertFalse(self.server._check_origin(request))

    def test_matching_origin_is_allowed(self):
        self._set_setting('API_INTERFACE', 'example.com')
        request = mock.Mock(['getHeader'])
        request.getHeader = mock.Mock(return_value='http://example.com')
        self.assertTrue(self.server._check_origin(request))

    def test_any_origin_is_allowed(self):
        self._set_setting('API_INTERFACE', '0.0.0.0')
        request = mock.Mock(['getHeader'])
        request.getHeader = mock.Mock(return_value='http://example.com')
        self.assertTrue(self.server._check_origin(request))
        request = mock.Mock(['getHeader'])
        request.getHeader = mock.Mock(return_value='http://another-example.com')
        self.assertTrue(self.server._check_origin(request))
