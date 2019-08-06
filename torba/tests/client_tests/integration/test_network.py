import logging
import asyncio
from unittest.mock import Mock

from torba.client.basenetwork import BaseNetwork
from torba.rpc import RPCSession
from torba.testcase import IntegrationTestCase, AsyncioTestCase


class NetworkTests(IntegrationTestCase):

    async def test_remote_height_updated_automagically(self):
        initial_height = self.ledger.network.remote_height
        await self.blockchain.generate(1)
        await self.ledger.network.on_header.first
        self.assertEqual(self.ledger.network.remote_height, initial_height + 1)


class ReconnectTests(IntegrationTestCase):

    VERBOSITY = logging.WARN

    async def test_connection_drop_still_receives_events_after_reconnected(self):
        address1 = await self.account.receiving.get_or_create_usable_address()
        # disconnect and send a new tx, should reconnect and get it
        self.ledger.network.client.connection_lost(Exception())
        self.assertFalse(self.ledger.network.is_connected)
        sendtxid = await self.blockchain.send_to_address(address1, 1.1337)
        await asyncio.wait_for(self.on_transaction_id(sendtxid), 1.0)  # mempool
        await self.blockchain.generate(1)
        await self.on_transaction_id(sendtxid)  # confirmed

        await self.assertBalance(self.account, '1.1337')
        # is it real? are we rich!? let me see this tx...
        d = self.ledger.network.get_transaction(sendtxid)
        # what's that smoke on my ethernet cable? oh no!
        self.ledger.network.client.connection_lost(Exception())
        with self.assertRaises((asyncio.TimeoutError, asyncio.CancelledError)):
           await d
        # rich but offline? no way, no water, let's retry
        with self.assertRaisesRegex(ConnectionError, 'connection is not available'):
            await self.ledger.network.get_transaction(sendtxid)
        # * goes to pick some water outside... * time passes by and another donation comes in
        sendtxid = await self.blockchain.send_to_address(address1, 42)
        await self.blockchain.generate(1)
        # omg, the burned cable still works! torba is fire proof!
        await self.ledger.network.get_transaction(sendtxid)

    async def test_timeout_then_reconnect(self):
        # tests that it connects back after some failed attempts
        await self.conductor.spv_node.stop()
        self.assertFalse(self.ledger.network.is_connected)
        await asyncio.sleep(0.2)  # let it retry and fail once
        await self.conductor.spv_node.start(self.conductor.blockchain_node)
        await self.ledger.network.on_connected.first
        self.assertTrue(self.ledger.network.is_connected)


class ServerPickingTestCase(AsyncioTestCase):

    async def _make_fake_server(self, latency=1.0, port=1):
        # local fake server with artificial latency
        class FakeSession(RPCSession):
            async def handle_request(self, request):
                await asyncio.sleep(latency)
                return {"height": 1}
        server = await self.loop.create_server(lambda: FakeSession(), host='127.0.0.1', port=port)
        self.addCleanup(server.close)
        return '127.0.0.1', port

    async def _make_bad_server(self, port=42420):
        async def echo(reader, writer):
            while True:
                writer.write(await reader.read())
        server = await asyncio.start_server(echo, host='127.0.0.1', port=port)
        self.addCleanup(server.close)
        return '127.0.0.1', port

    async def test_pick_fastest(self):
        ledger = Mock(config={
            'default_servers': [
                # fast but unhealthy, should be discarded
                await self._make_bad_server(),
                ('localhost', 1),
                ('example.that.doesnt.resolve', 9000),
                await self._make_fake_server(latency=1.0, port=1340),
                await self._make_fake_server(latency=0.1, port=1337),
                await self._make_fake_server(latency=0.4, port=1339),
            ],
            'connect_timeout': 3
        })

        network = BaseNetwork(ledger)
        self.addCleanup(network.stop)
        asyncio.ensure_future(network.start())
        await asyncio.wait_for(network.on_connected.first, timeout=1)
        self.assertTrue(network.is_connected)
        self.assertEqual(network.client.server, ('127.0.0.1', 1337))
        self.assertTrue(all([not session.is_closing() for session in network.session_pool.available_sessions]))
        # ensure we are connected to all of them after a while
        await asyncio.sleep(1)
        self.assertEqual(len(network.session_pool.available_sessions), 3)
