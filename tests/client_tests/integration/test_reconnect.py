import logging
import asyncio

from torba.client.basenetwork import BaseNetwork
from torba.rpc import RPCSession
from torba.stream import StreamController
from torba.testcase import IntegrationTestCase


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
        await self.ledger.stop()
        conf = self.ledger.config
        self.ledger.config['connect_timeout'] = 1
        self.ledger.config['default_servers'] = [('10.0.0.1', 12)] + list(conf['default_servers'])
        await self.ledger.start()
        self.assertTrue(self.ledger.network.is_connected)

    async def _make_fake_server(self, latency=1.0, port=1337):
        # local fake server with artificial latency
        proto = RPCSession()
        proto.handle_request = lambda _: asyncio.sleep(latency)
        server = await self.loop.create_server(lambda: proto, host='127.0.0.1', port=port)
        self.addCleanup(server.close)

    async def test_pick_fastest(self):
        original_servers = self.ledger.config['default_servers']
        original_servers.clear()
        for index in reversed(range(4)):  # reversed so the slowest is the first
            port = 1337 + index
            await self._make_fake_server(latency=index, port=port)
            original_servers.append(('127.0.0.1', port))

        fastest = ('127.0.0.1', 1337)
        self.ledger.config['default_servers'] = original_servers
        self.ledger.config['connect_timeout'] = 30

        network = BaseNetwork(self.ledger)
        self.addCleanup(network.stop)
        asyncio.ensure_future(network.start())
        await asyncio.wait_for(network.on_connected.first, timeout=1)
        self.assertTrue(network.is_connected)
        self.assertEqual(network.client.server, fastest)
