import asyncio

import lbry
import lbry.wallet
from lbry.error import ServerPaymentFeeAboveMaxAllowedError
from lbry.wallet.network import ClientSession
from lbry.wallet.rpc import RPCError
from lbry.wallet.server.db.elasticsearch.sync import make_es_index_and_run_sync
from lbry.wallet.server.session import LBRYElectrumX
from lbry.testcase import IntegrationTestCase, CommandTestCase
from lbry.wallet.orchstr8.node import SPVNode


class TestSessions(IntegrationTestCase):
    """
    Tests that server cleans up stale connections after session timeout and client times out too.
    """
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


class TestUsagePayment(CommandTestCase):
    async def _test_single_server_payment(self):
        wallet_pay_service = self.daemon.component_manager.get_component('wallet_server_payments')
        wallet_pay_service.payment_period = 1
        # only starts with a positive max key fee
        wallet_pay_service.max_fee = "0.0"
        await wallet_pay_service.start(ledger=self.ledger, wallet=self.wallet)
        self.assertFalse(wallet_pay_service.running)
        wallet_pay_service.max_fee = "1.0"
        await wallet_pay_service.start(ledger=self.ledger, wallet=self.wallet)
        self.assertTrue(wallet_pay_service.running)
        await wallet_pay_service.stop()
        await wallet_pay_service.start(ledger=self.ledger, wallet=self.wallet)

        address = await self.blockchain.get_raw_change_address()
        _, history = await self.ledger.get_local_status_and_history(address)
        self.assertEqual(history, [])

        node = SPVNode(self.conductor.spv_module, node_number=2)
        await node.start(self.blockchain, extraconf={"PAYMENT_ADDRESS": address, "DAILY_FEE": "1.1"})
        self.addCleanup(node.stop)
        self.daemon.jsonrpc_settings_set('lbryum_servers', [f"{node.hostname}:{node.port}"])
        await self.daemon.jsonrpc_wallet_reconnect()
        LBRYElectrumX.set_server_features(node.server.env)
        features = await self.ledger.network.get_server_features()
        self.assertEqual(features["payment_address"], address)
        self.assertEqual(features["daily_fee"], "1.1")
        with self.assertRaises(ServerPaymentFeeAboveMaxAllowedError):
            await asyncio.wait_for(wallet_pay_service.on_payment.first, timeout=30)
        node.server.env.daily_fee = "1.0"
        node.server.env.payment_address = address
        LBRYElectrumX.set_server_features(node.server.env)
        # self.daemon.jsonrpc_settings_set('lbryum_servers', [f"{node.hostname}:{node.port}"])
        await self.daemon.jsonrpc_wallet_reconnect()
        features = await self.ledger.network.get_server_features()
        self.assertEqual(features["payment_address"], address)
        self.assertEqual(features["daily_fee"], "1.0")
        tx = await asyncio.wait_for(wallet_pay_service.on_payment.first, timeout=30)
        self.assertIsNotNone(await self.blockchain.get_raw_transaction(tx.id))  # verify its broadcasted
        self.assertEqual(tx.outputs[0].amount, 100000000)
        self.assertEqual(tx.outputs[0].get_address(self.ledger), address)


class TestESSync(CommandTestCase):
    async def test_es_sync_utility(self):
        for i in range(10):
            await self.stream_create(f"stream{i}", bid='0.001')
        await self.generate(1)
        self.assertEqual(10, len(await self.claim_search(order_by=['height'])))
        db = self.conductor.spv_node.server.db
        env = self.conductor.spv_node.server.env

        await db.search_index.delete_index()
        db.search_index.clear_caches()
        self.assertEqual(0, len(await self.claim_search(order_by=['height'])))
        await db.search_index.stop()

        async def resync():
            await db.search_index.start()
            db.search_index.clear_caches()
            await make_es_index_and_run_sync(env, db=db, index_name=db.search_index.index, force=True)
            self.assertEqual(10, len(await self.claim_search(order_by=['height'])))

        self.assertEqual(0, len(await self.claim_search(order_by=['height'])))

        await resync()

        # this time we will test a migration from unversioned to v1
        await db.search_index.sync_client.indices.delete_template(db.search_index.index)
        await db.search_index.stop()

        await make_es_index_and_run_sync(env, db=db, index_name=db.search_index.index, force=True)
        await db.search_index.start()

        await resync()
        self.assertEqual(10, len(await self.claim_search(order_by=['height'])))


class TestHubDiscovery(CommandTestCase):

    async def test_hub_discovery(self):
        us_final_node = SPVNode(self.conductor.spv_module, node_number=2)
        await us_final_node.start(self.blockchain, extraconf={"COUNTRY": "US"})
        self.addCleanup(us_final_node.stop)
        final_node_host = f"{us_final_node.hostname}:{us_final_node.port}"

        kp_final_node = SPVNode(self.conductor.spv_module, node_number=3)
        await kp_final_node.start(self.blockchain, extraconf={"COUNTRY": "KP"})
        self.addCleanup(kp_final_node.stop)
        kp_final_node_host = f"{kp_final_node.hostname}:{kp_final_node.port}"

        relay_node = SPVNode(self.conductor.spv_module, node_number=4)
        await relay_node.start(self.blockchain, extraconf={
            "COUNTRY": "FR",
            "PEER_HUBS": ",".join([kp_final_node_host, final_node_host])
        })
        relay_node_host = f"{relay_node.hostname}:{relay_node.port}"
        self.addCleanup(relay_node.stop)

        self.assertEqual(list(self.daemon.conf.known_hubs), [])
        self.assertEqual(
            self.daemon.ledger.network.client.server_address_and_port,
            ('127.0.0.1', 50002)
        )

        # connect to relay hub which will tell us about the final hubs
        self.daemon.jsonrpc_settings_set('lbryum_servers', [relay_node_host])
        await self.daemon.jsonrpc_wallet_reconnect()
        self.assertEqual(
            self.daemon.conf.known_hubs.filter(), {
                (relay_node.hostname, relay_node.port): {"country": "FR"},
                (us_final_node.hostname, us_final_node.port): {},  # discovered from relay but not contacted yet
                (kp_final_node.hostname, kp_final_node.port): {},  # discovered from relay but not contacted yet
            }
        )
        self.assertEqual(
            self.daemon.ledger.network.client.server_address_and_port, ('127.0.0.1', relay_node.port)
        )

        # use known_hubs to connect to final US hub
        self.daemon.jsonrpc_settings_clear('lbryum_servers')
        self.daemon.conf.jurisdiction = "US"
        await self.daemon.jsonrpc_wallet_reconnect()
        self.assertEqual(
            self.daemon.conf.known_hubs.filter(), {
                (relay_node.hostname, relay_node.port): {"country": "FR"},
                (us_final_node.hostname, us_final_node.port): {"country": "US"},
                (kp_final_node.hostname, kp_final_node.port): {"country": "KP"},
            }
        )
        self.assertEqual(
            self.daemon.ledger.network.client.server_address_and_port, ('127.0.0.1', us_final_node.port)
        )

        # connection to KP jurisdiction
        self.daemon.conf.jurisdiction = "KP"
        await self.daemon.jsonrpc_wallet_reconnect()
        self.assertEqual(
            self.daemon.ledger.network.client.server_address_and_port, ('127.0.0.1', kp_final_node.port)
        )

        kp_final_node.server.session_mgr._notify_peer('127.0.0.1:9988')
        await self.daemon.ledger.network.on_hub.first
        await asyncio.sleep(0.5)  # wait for above event to be processed by other listeners
        self.assertEqual(
            self.daemon.conf.known_hubs.filter(), {
                (relay_node.hostname, relay_node.port): {"country": "FR"},
                (us_final_node.hostname, us_final_node.port): {"country": "US"},
                (kp_final_node.hostname, kp_final_node.port): {"country": "KP"},
                ('127.0.0.1', 9988): {}
            }
        )


class TestStressFlush(CommandTestCase):
    # async def test_flush_over_66_thousand(self):
    #     history = self.conductor.spv_node.server.db.history
    #     history.flush_count = 66_000
    #     history.flush()
    #     self.assertEqual(history.flush_count, 66_001)
    #     await self.generate(1)
    #     self.assertEqual(history.flush_count, 66_002)

    async def test_thousands_claim_ids_on_search(self):
        await self.stream_create()
        with self.assertRaises(RPCError) as err:
            await self.claim_search(not_channel_ids=[("%040x" % i) for i in range(8196)])
        # in the go hub this doesnt have a `.` at the end, in python it does
        self.assertTrue(err.exception.message.startswith('not_channel_ids cant have more than 2048 items'))
