import asyncio

import lbry
import lbry.wallet
from lbry.wallet.network import ClientSession
from lbry.testcase import IntegrationTestCase, CommandTestCase
from lbry.wallet.orchstr8.node import SPVNode


class TestSessions(IntegrationTestCase):
    """
    Tests that server cleans up stale connections after session timeout and client times out too.
    """

    LEDGER = lbry.wallet

    async def test_session_bloat_from_socket_timeout(self):
        await self.conductor.stop_spv()
        await self.ledger.stop()
        self.conductor.spv_node.session_timeout = 1
        await self.conductor.start_spv()
        session = ClientSession(
            network=None, server=(self.conductor.spv_node.hostname, self.conductor.spv_node.port), timeout=0.2
        )
        await session.create_connection()
        await session.send_request('server.banner', ())
        self.assertEqual(len(self.conductor.spv_node.server.session_mgr.sessions), 1)
        self.assertFalse(session.is_closing())
        await asyncio.sleep(1.1)
        with self.assertRaises(asyncio.TimeoutError):
            await session.send_request('server.banner', ())
        self.assertTrue(session.is_closing())
        self.assertEqual(len(self.conductor.spv_node.server.session_mgr.sessions), 0)

    async def test_proper_version(self):
        info = await self.ledger.network.get_server_features()
        self.assertEqual(lbry.__version__, info['server_version'])

    async def test_client_errors(self):
        # Goal is ensuring thsoe are raised and not trapped accidentally
        with self.assertRaisesRegex(Exception, 'not a valid address'):
            await self.ledger.network.get_history('of the world')
        with self.assertRaisesRegex(Exception, 'rejected by network rules.*TX decode failed'):
            await self.ledger.network.broadcast('13370042004200')


class TestSegwitServer(IntegrationTestCase):
    LEDGER = lbry.wallet
    ENABLE_SEGWIT = True

    async def test_at_least_it_starts(self):
        await asyncio.wait_for(self.ledger.network.get_headers(0, 1), 1.0)


class TestUsagePayment(CommandTestCase):

    async def test_single_server_payment(self):
        # create wallet server
        # set payment address and fee rate on server
        # connect to server
        # fast forward 24 hours
        # check that payment was sent to server

        address = (await self.account.receiving.get_addresses(limit=1, only_usable=True))[0]

        node = SPVNode(self.conductor.spv_module, node_number=2)
        await node.start(self.blockchain, extraconf={"PAYMENT_ADDRESS": address, "DAILY_FEE": "1"})

        self.ledger.network.config['default_servers'] = [(node.hostname, node.port)]
        await self.ledger.stop()
        await self.ledger.start()

        features = await self.ledger.network.get_server_features()



        pass

    # async def test_daily_payment(self):
    #     node2 = SPVNode(self.conductor.spv_module, node_number=2)
    #     self.ledger.network.config['default_servers'].append((node2.hostname, node2.port))
    #     await asyncio.wait_for(self.ledger.stop(), timeout=1)
    #     await asyncio.wait_for(self.ledger.start(), timeout=1)
    #     self.ledger.network.session_pool.new_connection_event.clear()
    #     await node2.start(self.blockchain)
    #     # this is only to speed up the test as retrying would take 4+ seconds
    #     for session in self.ledger.network.session_pool.sessions:
    #         session.trigger_urgent_reconnect.set()
    #     await asyncio.wait_for(self.ledger.network.session_pool.new_connection_event.wait(), timeout=1)