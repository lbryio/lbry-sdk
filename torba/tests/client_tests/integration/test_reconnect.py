import logging
import asyncio
import socket
from unittest.mock import Mock

from torba.client.basenetwork import BaseNetwork
from torba.rpc import RPCSession
from torba.testcase import IntegrationTestCase, AsyncioTestCase


class ReconnectTests(IntegrationTestCase):

    VERBOSITY = logging.WARN

    async def test_connection_drop_still_receives_events_after_reconnected(self):
        address1 = await self.account.receiving.get_or_create_usable_address()
        self.ledger.network.client.connection_lost(Exception())
        sendtxid = await self.blockchain.send_to_address(address1, 1.1337)
        await self.on_transaction_id(sendtxid)  # mempool
        await self.blockchain.generate(1)
        await self.on_transaction_id(sendtxid)  # confirmed

        await self.assertBalance(self.account, '1.1337')
        # is it real? are we rich!? let me see this tx...
        d = self.ledger.network.get_transaction(sendtxid)
        # what's that smoke on my ethernet cable? oh no!
        self.ledger.network.client.connection_lost(Exception())
        with self.assertRaises(asyncio.CancelledError):
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
        await self.conductor.spv_node.stop()
        self.assertFalse(self.ledger.network.is_connected)
        await self.conductor.spv_node.start(self.conductor.blockchain_node)
        await self.ledger.network.on_connected.first
        self.assertTrue(self.ledger.network.is_connected)

    async def test_socket_timeout_then_reconnect(self):
        # TODO: test reconnecting on an rpc request
        # TODO: test rolling over to a working server when an rpc request fails before raising

        self.assertTrue(self.ledger.network.is_connected)

        await self.assertBalance(self.account, '0.0')

        address1 = await self.account.receiving.get_or_create_usable_address()

        real_sock = self.ledger.network.client.transport._extra.pop('socket')
        mock_sock = Mock(spec=socket.socket)

        for attr in dir(real_sock):
            if not attr.startswith('__'):
                setattr(mock_sock, attr, getattr(real_sock, attr))

        raised = asyncio.Event(loop=self.loop)

        def recv(*a, **kw):
            raised.set()
            raise TimeoutError("[Errno 60] Operation timed out")

        mock_sock.recv = recv
        self.ledger.network.client.transport._sock = mock_sock
        self.ledger.network.client.transport._extra['socket'] = mock_sock

        await self.blockchain.send_to_address(address1, 21)
        await self.blockchain.generate(1)
        self.assertFalse(raised.is_set())

        await asyncio.wait_for(raised.wait(), 2)
        await self.assertBalance(self.account, '0.0')
        self.assertFalse(self.ledger.network.is_connected)
        self.assertIsNone(self.ledger.network.client.transport)

        await self.blockchain.send_to_address(address1, 21)
        await self.blockchain.generate(1)
        await self.ledger.network.on_connected.first
        self.assertTrue(self.ledger.network.is_connected)

        await asyncio.sleep(30, loop=self.loop)
        self.assertIsNotNone(self.ledger.network.client.transport)
        await self.assertBalance(self.account, '42.0')


class ServerPickingTestCase(AsyncioTestCase):
    async def _make_fake_server(self, latency=1.0, port=1337):
        # local fake server with artificial latency
        proto = RPCSession()
        proto.handle_request = lambda _: asyncio.sleep(latency)
        server = await self.loop.create_server(lambda: proto, host='127.0.0.1', port=port)
        self.addCleanup(server.close)
        return ('127.0.0.1', port)

    async def test_pick_fastest(self):
        ledger = Mock(config={
            'default_servers': [
                await self._make_fake_server(latency=1.5, port=1340),
                await self._make_fake_server(latency=0.1, port=1337),
                await self._make_fake_server(latency=1.0, port=1339),
                await self._make_fake_server(latency=0.5, port=1338),
            ],
            'connect_timeout': 30
        })

        network = BaseNetwork(ledger)
        self.addCleanup(network.stop)
        asyncio.ensure_future(network.start())
        await asyncio.wait_for(network.on_connected.first, timeout=1)
        self.assertTrue(network.is_connected)
        self.assertEqual(network.client.server, ('127.0.0.1', 1337))
        # ensure we are connected to all of them
        self.assertEqual(len(network.session_pool.sessions), 4)
        self.assertTrue(all([not session.is_closing() for session in network.session_pool.sessions]))
