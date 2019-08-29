import asyncio
import os

import lbry.wallet
from lbry.testcase import CommandTestCase
from lbry.extras.daemon.Components import HeadersComponent
from torba.client.basenetwork import ClientSession
from torba.testcase import IntegrationTestCase


class TestSessionBloat(IntegrationTestCase):
    """
    Tests that server cleans up stale connections after session timeout and client times out too.
    """

    LEDGER = lbry.wallet

    async def test_session_bloat_from_socket_timeout(self):
        client = self.ledger.network.client
        await self.conductor.stop_spv()
        await self.ledger.stop()
        self.conductor.spv_node.session_timeout = 1
        await self.conductor.start_spv()
        session = ClientSession(network=None, server=client.server, timeout=0.2)
        await session.create_connection()
        await session.send_request('server.banner', ())
        self.assertEqual(len(self.conductor.spv_node.server.session_mgr.sessions), 1)
        self.assertFalse(session.is_closing())
        await asyncio.sleep(1.1)
        with self.assertRaises(asyncio.TimeoutError):
            await session.send_request('server.banner', ())
        self.assertTrue(session.is_closing())
        self.assertEqual(len(self.conductor.spv_node.server.session_mgr.sessions), 0)


class TestSegwitServer(IntegrationTestCase):
    LEDGER = lbry.wallet
    ENABLE_SEGWIT = True

    async def test_at_least_it_starts(self):
        await asyncio.wait_for(self.ledger.network.get_headers(0, 1), 1.0)


class TestHeadersComponent(CommandTestCase):

    LEDGER = lbry.wallet

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.component_manager = self.daemon.component_manager
        self.component_manager.conf.blockchain_name = 'lbrycrd_main'
        self.headers_component = HeadersComponent(self.component_manager)

    async def test_cant_reach_host(self):
        HeadersComponent.HEADERS_URL = 'notthere/'
        os.unlink(self.headers_component.headers.path)
        # test is that this doesnt raise
        await self.headers_component.start()
        self.assertTrue(self.component_manager.get_components_status()['blockchain_headers'])
        self.assertEqual(await self.headers_component.get_status(), {})