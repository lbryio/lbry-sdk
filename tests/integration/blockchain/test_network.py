import asyncio

import lbry
from unittest.mock import Mock

from lbry.wallet.network import Network
from lbry.wallet.orchstr8 import Conductor
from lbry.wallet.orchstr8.node import SPVNode
from lbry.wallet.rpc import RPCSession
from lbry.wallet.server.udp import StatusServer
from lbry.testcase import IntegrationTestCase, AsyncioTestCase
from lbry.conf import Config


class NetworkTests(IntegrationTestCase):

    async def test_remote_height_updated_automagically(self):
        initial_height = self.ledger.network.remote_height
        await self.blockchain.generate(1)
        await self.ledger.network.on_header.first
        self.assertEqual(self.ledger.network.remote_height, initial_height + 1)

    async def test_server_features(self):
        self.assertDictEqual({
            'genesis_hash': self.conductor.spv_node.coin_class.GENESIS_HASH,
            'hash_function': 'sha256',
            'hosts': {},
            'protocol_max': '0.99.0',
            'protocol_min': '0.54.0',
            'pruning': None,
            'description': '',
            'payment_address': '',
            'donation_address': '',
            'daily_fee': '0',
            'server_version': lbry.__version__,
            'trending_algorithm': 'zscore',
            }, await self.ledger.network.get_server_features())
        # await self.conductor.spv_node.stop()
        payment_address, donation_address = await self.account.get_addresses(limit=2)
        self.conductor.spv_node.server.env.payment_address = payment_address
        self.conductor.spv_node.server.env.donation_address = donation_address
        self.conductor.spv_node.server.env.description = 'Fastest server in the west.'
        self.conductor.spv_node.server.env.daily_fee = '42'

        from lbry.wallet.server.session import LBRYElectrumX
        LBRYElectrumX.set_server_features(self.conductor.spv_node.server.env)

        # await self.ledger.network.on_connected.first
        self.assertDictEqual({
            'genesis_hash': self.conductor.spv_node.coin_class.GENESIS_HASH,
            'hash_function': 'sha256',
            'hosts': {},
            'protocol_max': '0.99.0',
            'protocol_min': '0.54.0',
            'pruning': None,
            'description': 'Fastest server in the west.',
            'payment_address': payment_address,
            'donation_address': donation_address,
            'daily_fee': '42',
            'server_version': lbry.__version__,
            'trending_algorithm': 'zscore',
            }, await self.ledger.network.get_server_features())


class ReconnectTests(IntegrationTestCase):

    async def test_multiple_servers(self):
        # we have a secondary node that connects later, so
        node2 = SPVNode(self.conductor.spv_module, node_number=2)
        await node2.start(self.blockchain)

        self.ledger.network.config['default_servers'].append((node2.hostname, node2.port))
        self.ledger.network.config['default_servers'].reverse()
        self.assertEqual(50002, self.ledger.network.client.server[1])
        await self.ledger.stop()
        await self.ledger.start()

        self.assertTrue(self.ledger.network.is_connected)
        self.assertEqual(50003, self.ledger.network.client.server[1])
        await node2.stop(True)
        self.assertFalse(self.ledger.network.is_connected)
        await self.ledger.resolve([], ['derp'])
        self.assertEqual(50002, self.ledger.network.client.server[1])

    async def test_direct_sync(self):
        await self.ledger.stop()
        initial_height = self.ledger.local_height_including_downloaded_height
        await self.blockchain.generate(100)
        while self.conductor.spv_node.server.session_mgr.notified_height < initial_height + 99:  # off by 1
            await asyncio.sleep(0.1)
        self.assertEqual(initial_height, self.ledger.local_height_including_downloaded_height)
        await self.ledger.headers.open()
        await self.ledger.network.start()
        await self.ledger.network.on_connected.first
        await self.ledger.initial_headers_sync()
        self.assertEqual(initial_height + 100, self.ledger.local_height_including_downloaded_height)

    async def test_connection_drop_still_receives_events_after_reconnected(self):
        address1 = await self.account.receiving.get_or_create_usable_address()
        # disconnect and send a new tx, should reconnect and get it
        self.ledger.network.client.transport.close()
        self.assertFalse(self.ledger.network.is_connected)
        await self.ledger.resolve([], 'derp')
        sendtxid = await self.blockchain.send_to_address(address1, 1.1337)
        # await self.ledger.resolve([], 'derp')
        # self.assertTrue(self.ledger.network.is_connected)
        await asyncio.wait_for(self.on_transaction_id(sendtxid), 10.0)  # mempool
        await self.blockchain.generate(1)
        await self.on_transaction_id(sendtxid)  # confirmed
        self.assertLess(self.ledger.network.client.response_time, 1)  # response time properly set lower, we are fine

        await self.assertBalance(self.account, '1.1337')
        # is it real? are we rich!? let me see this tx...
        d = self.ledger.network.get_transaction(sendtxid)
        # what's that smoke on my ethernet cable? oh no!
        master_client = self.ledger.network.client
        self.ledger.network.client.connection_lost(Exception())
        with self.assertRaises(asyncio.TimeoutError):
            await d
        self.assertIsNone(master_client.response_time)  # response time unknown as it failed
        # rich but offline? no way, no water, let's retry
        with self.assertRaisesRegex(ConnectionError, 'connection is not available'):
            await self.ledger.network.get_transaction(sendtxid)
        # * goes to pick some water outside... * time passes by and another donation comes in
        sendtxid = await self.blockchain.send_to_address(address1, 42)
        await self.blockchain.generate(1)
        # (this is just so the test doesn't hang forever if it doesn't reconnect)
        if not self.ledger.network.is_connected:
            await asyncio.wait_for(self.ledger.network.on_connected.first, timeout=10.0)
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

    async def test_timeout_propagated_from_config(self):
        conf = Config()
        self.assertEqual(self.ledger.network.client.timeout, 30)
        conf.hub_timeout = 123.0
        conf.lbryum_servers = self.ledger.config['default_servers']
        self.manager.config = conf
        await self.manager.reset()
        self.assertEqual(self.ledger.network.client.timeout, 123)

    # async def test_online_but_still_unavailable(self):
    #     # Edge case. See issue #2445 for context
    #     self.assertIsNotNone(self.ledger.network.session_pool.fastest_session)
    #     for session in self.ledger.network.session_pool.sessions:
    #         session.response_time = None
    #     self.assertIsNone(self.ledger.network.session_pool.fastest_session)


class UDPServerFailDiscoveryTest(AsyncioTestCase):

    async def test_wallet_connects_despite_lack_of_udp(self):
        conductor = Conductor()
        conductor.spv_node.udp_port = '0'
        await conductor.start_blockchain()
        self.addCleanup(conductor.stop_blockchain)
        await conductor.start_spv()
        self.addCleanup(conductor.stop_spv)
        self.assertFalse(conductor.spv_node.server.bp.status_server.is_running)
        await asyncio.wait_for(conductor.start_wallet(), timeout=5)
        self.addCleanup(conductor.stop_wallet)
        self.assertTrue(conductor.wallet_node.ledger.network.is_connected)


class ServerPickingTestCase(AsyncioTestCase):
    async def _make_udp_server(self, port):
        s = StatusServer()
        await s.start(0, b'\x00' * 32, '127.0.0.1', port)
        self.addCleanup(s.stop)

    async def _make_fake_server(self, latency=1.0, port=1):
        # local fake server with artificial latency
        class FakeSession(RPCSession):
            async def handle_request(self, request):
                await asyncio.sleep(latency)
                if request.method == 'server.version':
                    return tuple(request.args)
                return {'height': 1}
        server = await self.loop.create_server(lambda: FakeSession(), host='127.0.0.1', port=port)
        self.addCleanup(server.close)
        await self._make_udp_server(port)
        return '127.0.0.1', port

    async def _make_bad_server(self, port=42420):
        async def echo(reader, writer):
            while True:
                writer.write(await reader.read())
        server = await asyncio.start_server(echo, host='127.0.0.1', port=port)
        self.addCleanup(server.close)
        await self._make_udp_server(port)
        return '127.0.0.1', port

    async def _test_pick_fastest(self):
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

        network = Network(ledger)
        self.addCleanup(network.stop)
        await network.start()
        await asyncio.wait_for(network.on_connected.first, timeout=10)
        self.assertTrue(network.is_connected)
        self.assertTupleEqual(network.client.server, ('127.0.0.1', 1337))
        self.assertTrue(all([not session.is_closing() for session in network.session_pool.available_sessions]))
        # ensure we are connected to all of them after a while
        await asyncio.sleep(1)
        self.assertEqual(len(list(network.session_pool.available_sessions)), 3)
