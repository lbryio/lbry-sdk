import logging
import asyncio

from torba.rpc import RPCSession
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

    async def test_pick_fastest(self):
        # local server that is listening but wont reply
        proto = RPCSession()
        proto.handle_request = lambda _: asyncio.sleep(10)
        server = await self.loop.create_server(lambda: proto, host='127.0.0.1', port=1337)
        await self.ledger.stop()
        conf = self.ledger.config
        self.ledger.config['default_servers'] = [('127.0.0.1', 1337)] + list(conf['default_servers'])
        self.ledger.config['connect_timeout'] = 30
        await asyncio.wait_for(self.ledger.start(), timeout=1)
        self.assertTrue(self.ledger.network.is_connected)
        self.assertEqual(self.ledger.network.client.server, conf['default_servers'][-1])
