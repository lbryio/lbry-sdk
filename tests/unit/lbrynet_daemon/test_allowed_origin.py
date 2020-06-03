import unittest

from aiohttp.test_utils import make_mocked_request as request

from lbry.testcase import AsyncioTestCase
from lbry.conf import Config
from lbry.extras.daemon.security import is_request_allowed as allowed


class TestAllowedOrigin(unittest.TestCase):

    def test_allowed_origin_default(self):
        conf = Config()
        # no Origin is always allowed
        self.assertTrue(allowed(request('GET', '/'), conf))
        # some clients send Origin: null (eg, https://github.com/electron/electron/issues/7931)
        self.assertTrue(allowed(request('GET', '/', headers={'Origin': 'null'}), conf))
        # deny all other Origins
        self.assertFalse(allowed(request('GET', '/', headers={'Origin': 'localhost'}), conf))
        self.assertFalse(allowed(request('GET', '/', headers={'Origin': 'hackers.com'}), conf))

    def test_allowed_origin_star(self):
        conf = Config(allowed_origin='*')
        # everything is allowed
        self.assertTrue(allowed(request('GET', '/'), conf))
        self.assertTrue(allowed(request('GET', '/', headers={'Origin': 'null'}), conf))
        self.assertTrue(allowed(request('GET', '/', headers={'Origin': 'localhost'}), conf))
        self.assertTrue(allowed(request('GET', '/', headers={'Origin': 'hackers.com'}), conf))

    def test_allowed_origin_specified(self):
        conf = Config(allowed_origin='localhost')
        # no origin and only localhost are allowed
        self.assertTrue(allowed(request('GET', '/'), conf))
        self.assertTrue(allowed(request('GET', '/', headers={'Origin': 'null'}), conf))
        self.assertTrue(allowed(request('GET', '/', headers={'Origin': 'localhost'}), conf))
        self.assertFalse(allowed(request('GET', '/', headers={'Origin': 'hackers.com'}), conf))
