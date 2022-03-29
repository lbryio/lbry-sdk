import asyncio
import logging
from lbry.testcase import IntegrationTestCase, WalletNode
from lbry.constants import CENT
from lbry.wallet import WalletManager, RegTestLedger, Transaction, Output


class SyncTests(IntegrationTestCase):

    VERBOSITY = logging.WARN

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.api_port = 5280
        self.started_nodes = []

    async def asyncTearDown(self):
        for node in self.started_nodes:
            try:
                await node.stop(cleanup=True)
            except Exception as e:
                print(e)
        await super().asyncTearDown()

    async def make_wallet_node(self, seed=None):
        self.api_port += 1
        wallet_node = WalletNode(WalletManager, RegTestLedger, port=self.api_port)
        await wallet_node.start(self.conductor.spv_node, seed)
        self.started_nodes.append(wallet_node)
        return wallet_node

    async def test_nodes_with_same_account_stay_in_sync(self):
        # destination node/account for receiving TXs
        node0 = await self.make_wallet_node()
        account0 = node0.account
        # main node/account creating TXs
        node1 = self.wallet_node
        account1 = self.wallet_node.account
        # mirror node/account, expected to reflect everything in main node as it happens
        node2 = await self.make_wallet_node(account1.seed)
        account2 = node2.account

        self.assertNotEqual(account0.id, account1.id)
        self.assertEqual(account1.id, account2.id)
        await self.assertBalance(account0, '0.0')
        await self.assertBalance(account1, '0.0')
        await self.assertBalance(account2, '0.0')
        self.assertEqual(await account0.get_address_count(chain=0), 20)
        self.assertEqual(await account1.get_address_count(chain=0), 20)
        self.assertEqual(await account2.get_address_count(chain=0), 20)
        self.assertEqual(await account1.get_address_count(chain=1), 6)
        self.assertEqual(await account2.get_address_count(chain=1), 6)

        # check that main node and mirror node generate 5 address to fill gap
        fifth_address = (await account1.receiving.get_addresses())[4]
        await self.blockchain.send_to_address(fifth_address, 1.00)
        await asyncio.wait([
            account1.ledger.on_address.first,
            account2.ledger.on_address.first
        ])
        self.assertEqual(await account1.get_address_count(chain=0), 25)
        self.assertEqual(await account2.get_address_count(chain=0), 25)
        await self.assertBalance(account1, '1.0')
        await self.assertBalance(account2, '1.0')

        await self.generate(1)

        # pay 0.01 from main node to receiving node, would have increased change addresses
        address0 = (await account0.receiving.get_addresses())[0]
        hash0 = self.ledger.address_to_hash160(address0)
        tx = await Transaction.create(
            [],
            [Output.pay_pubkey_hash(CENT, hash0)],
            [account1], account1
        )
        await self.broadcast(tx)
        await asyncio.wait([
            account0.ledger.wait(tx),
            account1.ledger.wait(tx),
            account2.ledger.wait(tx),
        ])
        await self.generate(1)
        await asyncio.wait([
            account0.ledger.wait(tx),
            account1.ledger.wait(tx),
            account2.ledger.wait(tx),
        ])
        self.assertEqual(await account0.get_address_count(chain=0), 21)
        self.assertGreater(await account1.get_address_count(chain=1), 6)
        self.assertGreater(await account2.get_address_count(chain=1), 6)
        await self.assertBalance(account0, '0.01')
        await self.assertBalance(account1, '0.989876')
        await self.assertBalance(account2, '0.989876')

        await self.generate(1)

        # create a new mirror node and see if it syncs to same balance from scratch
        node3 = await self.make_wallet_node(account1.seed)
        account3 = node3.account
        await self.assertBalance(account3, '0.989876')
