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
        self.assertFalse(self.server._check_header_source(request, 'Origin'))

    def test_wrong_port_is_rejected(self):
        self._set_setting('api_port', 1234)
        request = mock.Mock(['getHeader'])
        request.getHeader = mock.Mock(return_value='http://localhost:9999')
        self.assertFalse(self.server._check_header_source(request, 'Origin'))

    def test_matching_origin_is_allowed(self):
        self._set_setting('API_INTERFACE', 'example.com')
        self._set_setting('api_port', 1234)
        request = mock.Mock(['getHeader'])
        request.getHeader = mock.Mock(return_value='http://example.com:1234')
        self.assertTrue(self.server._check_header_source(request, 'Origin'))

    def test_any_origin_is_allowed(self):
        self._set_setting('API_INTERFACE', '0.0.0.0')
        self._set_setting('api_port', 80)
        request = mock.Mock(['getHeader'])
        request.getHeader = mock.Mock(return_value='http://example.com')
        self.assertTrue(self.server._check_header_source(request, 'Origin'))
        request = mock.Mock(['getHeader'])
        request.getHeader = mock.Mock(return_value='http://another-example.com')
        self.assertTrue(self.server._check_header_source(request, 'Origin'))

    def test_matching_referer_is_allowed(self):
        self._set_setting('API_INTERFACE', 'the_api')
        self._set_setting('api_port', 1111)
        request = mock.Mock(['getHeader'])
        request.getHeader = mock.Mock(return_value='http://the_api:1111?settings')
        self.assertTrue(self.server._check_header_source(request, 'Referer'))
        request.getHeader.assert_called_with('Referer')
