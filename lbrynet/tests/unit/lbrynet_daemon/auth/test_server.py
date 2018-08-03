import mock
from twisted.trial import unittest
from lbrynet import conf
from lbrynet.tests.mocks import mock_conf_settings
from lbrynet.daemon.auth import server


class AuthJSONRPCServerTest(unittest.TestCase):
    # TODO: move to using a base class for tests
    # and add useful general utilities like this
    # onto it.
    def setUp(self):
        conf.initialize_settings(False)
        self.server = server.AuthJSONRPCServer(True, use_authentication=False)

    def test_get_server_port(self):
        self.assertSequenceEqual(
            ('example.com', 80), self.server.get_server_port('http://example.com'))
        self.assertSequenceEqual(
            ('example.com', 1234), self.server.get_server_port('http://example.com:1234'))

    def test_foreign_origin_is_rejected(self):
        mock_conf_settings(self)  # have to call this to generate Config mock
        request = mock.Mock(['getHeader'])
        request.getHeader = mock.Mock(return_value='http://example.com')
        self.assertFalse(self.server._check_header_source(request, 'Origin'))

    def test_wrong_port_is_rejected(self):
        mock_conf_settings(self, {'api_port': 1234})
        request = mock.Mock(['getHeader'])
        request.getHeader = mock.Mock(return_value='http://localhost:9999')
        self.assertFalse(self.server._check_header_source(request, 'Origin'))

    def test_matching_origin_is_allowed(self):
        mock_conf_settings(self, {'api_host': 'example.com', 'api_port': 1234})
        request = mock.Mock(['getHeader'])
        request.getHeader = mock.Mock(return_value='http://example.com:1234')
        self.assertTrue(self.server._check_header_source(request, 'Origin'))

    def test_any_origin_is_allowed(self):
        mock_conf_settings(self, {'api_host': '0.0.0.0', 'api_port': 80})
        request = mock.Mock(['getHeader'])
        request.getHeader = mock.Mock(return_value='http://example.com')
        self.assertTrue(self.server._check_header_source(request, 'Origin'))
        request = mock.Mock(['getHeader'])
        request.getHeader = mock.Mock(return_value='http://another-example.com')
        self.assertTrue(self.server._check_header_source(request, 'Origin'))

    def test_matching_referer_is_allowed(self):
        mock_conf_settings(self, {'api_host': 'the_api', 'api_port': 1111})
        request = mock.Mock(['getHeader'])
        request.getHeader = mock.Mock(return_value='http://the_api:1111?settings')
        self.assertTrue(self.server._check_header_source(request, 'Referer'))
        request.getHeader.assert_called_with('Referer')

    def test_request_is_allowed_when_matching_allowed_origin_setting(self):
        mock_conf_settings(self, {'allowed_origin': 'http://example.com:1234'})
        request = mock.Mock(['getHeader'])
        request.getHeader = mock.Mock(return_value='http://example.com:1234')
        self.assertTrue(self.server._check_header_source(request, 'Origin'))

    def test_request_is_rejected_when_not_matching_allowed_origin_setting(self):
        mock_conf_settings(self, {'allowed_origin': 'http://example.com:1234'})
        request = mock.Mock(['getHeader'])
        # note the ports don't match
        request.getHeader = mock.Mock(return_value='http://example.com:1235')
        self.assertFalse(self.server._check_header_source(request, 'Origin'))
