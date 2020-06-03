import unittest

from aiohttp.test_utils import make_mocked_request as request
from aiohttp.web import HTTPForbidden

from lbry.testcase import AsyncioTestCase
from lbry.conf import Config
from lbry.extras.daemon.security import is_request_allowed as allowed, ensure_request_allowed as ensure


class TestAllowedOrigin(unittest.TestCase):

    def test_allowed_origin_default(self):
        conf = Config()
        # lack of Origin is always allowed
        self.assertTrue(allowed(request('GET', '/'), conf))
        # deny all other Origins
        self.assertFalse(allowed(request('GET', '/', headers={'Origin': 'null'}), conf))
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
        self.assertTrue(allowed(request('GET', '/', headers={'Origin': 'localhost'}), conf))
        self.assertFalse(allowed(request('GET', '/', headers={'Origin': 'null'}), conf))
        self.assertFalse(allowed(request('GET', '/', headers={'Origin': 'hackers.com'}), conf))

    def test_ensure_default(self):
        conf = Config()
        ensure(request('GET', '/'), conf)
        with self.assertLogs() as log:
            with self.assertRaises(HTTPForbidden):
                ensure(request('GET', '/', headers={'Origin': 'localhost'}), conf)
            self.assertIn("'localhost' are not allowed", log.output[0])

    def test_ensure_specific(self):
        conf = Config(allowed_origin='localhost')
        ensure(request('GET', '/', headers={'Origin': 'localhost'}), conf)
        with self.assertLogs() as log:
            with self.assertRaises(HTTPForbidden):
                ensure(request('GET', '/', headers={'Origin': 'hackers.com'}), conf)
            self.assertIn("'hackers.com' are not allowed", log.output[0])
            self.assertIn("'allowed_origin' limits requests to: 'localhost'", log.output[0])
