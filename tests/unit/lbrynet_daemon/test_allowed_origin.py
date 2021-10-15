import unittest

from aiohttp import ClientSession
from aiohttp.test_utils import make_mocked_request as request
from aiohttp.web import HTTPForbidden

from lbry.testcase import AsyncioTestCase
from lbry.conf import Config
from lbry.extras.daemon.security import is_request_allowed as allowed, ensure_request_allowed as ensure
from lbry.extras.daemon.components import (
    DATABASE_COMPONENT, DISK_SPACE_COMPONENT, BLOB_COMPONENT, WALLET_COMPONENT, DHT_COMPONENT,
    HASH_ANNOUNCER_COMPONENT, FILE_MANAGER_COMPONENT, PEER_PROTOCOL_SERVER_COMPONENT,
    UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT, WALLET_SERVER_PAYMENTS_COMPONENT,
    LIBTORRENT_COMPONENT, BACKGROUND_DOWNLOADER_COMPONENT
)
from lbry.extras.daemon.daemon import Daemon


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


class TestAccessHeaders(AsyncioTestCase):

    async def asyncSetUp(self):
        conf = Config(allowed_origin='localhost')
        conf.data_dir = '/tmp'
        conf.share_usage_data = False
        conf.api = 'localhost:5299'
        conf.components_to_skip = (
            DATABASE_COMPONENT, DISK_SPACE_COMPONENT, BLOB_COMPONENT, WALLET_COMPONENT, DHT_COMPONENT,
            HASH_ANNOUNCER_COMPONENT, FILE_MANAGER_COMPONENT, PEER_PROTOCOL_SERVER_COMPONENT,
            UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT, WALLET_SERVER_PAYMENTS_COMPONENT,
            LIBTORRENT_COMPONENT, BACKGROUND_DOWNLOADER_COMPONENT
        )
        Daemon.component_attributes = {}
        self.daemon = Daemon(conf)
        await self.daemon.start()
        self.addCleanup(self.daemon.stop)

    async def test_headers(self):
        async with ClientSession() as session:

            # OPTIONS
            async with session.options('http://localhost:5299') as resp:
                self.assertEqual(resp.headers['Access-Control-Allow-Origin'], 'localhost')
                self.assertEqual(resp.headers['Access-Control-Allow-Methods'], 'localhost')
                self.assertEqual(resp.headers['Access-Control-Allow-Headers'], 'localhost')

            # GET
            status = {'method': 'status', 'params': []}
            async with session.get('http://localhost:5299/lbryapi', json=status) as resp:
                self.assertEqual(resp.headers['Access-Control-Allow-Origin'], 'localhost')
                self.assertEqual(resp.headers['Access-Control-Allow-Methods'], 'localhost')
                self.assertEqual(resp.headers['Access-Control-Allow-Headers'], 'localhost')
