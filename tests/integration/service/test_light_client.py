import asyncio
from binascii import unhexlify

from lbry.testcase import IntegrationTestCase
from lbry.service.full_node import FullNode
from lbry.service.light_client import LightClient
from lbry.blockchain.block import get_address_filter


class LightClientTests(IntegrationTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.chain.generate(200)
        self.full_node_daemon = await self.make_full_node_daemon()
        self.full_node: FullNode = self.full_node_daemon.service
        self.light_client_daemon = await self.make_light_client_daemon(self.full_node_daemon, start=False)
        self.light_client: LightClient = self.light_client_daemon.service
        self.light_client.conf.wallet_storage = "database"
        self.addCleanup(self.light_client.client.disconnect)
        await self.light_client.client.connect()
        self.addCleanup(self.light_client.db.close)
        await self.light_client.db.open()
        self.addCleanup(self.light_client.wallets.close)
        await self.light_client.wallets.open()
        await self.light_client.client.start_event_streams()
        self.db = self.light_client.db
        self.sync = self.light_client.sync
        self.client = self.light_client.client
        self.account = self.light_client.wallets.default.accounts.default

    async def test_sync(self):
        self.assertEqual(await self.client.first.block_tip(), 200)

        self.assertEqual(await self.db.get_best_block_height(), -1)
        self.assertEqual(await self.db.get_missing_required_filters(200), {(2, 0, 100)})
        await self.sync.start()
        self.assertEqual(await self.db.get_best_block_height(), 200)
        self.assertEqual(await self.db.get_missing_required_filters(200), set())

        address = await self.account.receiving.get_or_create_usable_address()
        await self.chain.send_to_address(address, '5.0')
        await self.chain.generate(1)
        await self.assertBalance(self.account, '0.0')
        await self.sync.on_synced.first
        await self.assertBalance(self.account, '5.0')
