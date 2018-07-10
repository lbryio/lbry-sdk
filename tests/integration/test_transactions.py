import asyncio
from orchstr8.testcase import IntegrationTestCase, d2f
from torba.constants import COIN


class BasicTransactionTests(IntegrationTestCase):

    VERBOSE = True

    async def test_sending_and_receiving(self):
        account1, account2 = self.account, self.wallet.generate_account(self.ledger)

        self.assertEqual(await self.get_balance(account1), 0)
        self.assertEqual(await self.get_balance(account2), 0)

        sendtxids = []
        for i in range(9):
            address1 = await d2f(account1.receiving.get_or_create_usable_address())
            sendtxid = await self.blockchain.send_to_address(address1.decode(), 1.1)
            sendtxids.append(sendtxid)
            await self.on_transaction_id(sendtxid)  # mempool
        await self.blockchain.generate(1)
        await asyncio.wait([  # confirmed
            self.on_transaction_id(txid) for txid in sendtxids
        ])

        self.assertEqual(round(await self.get_balance(account1)/COIN, 1), 9.9)
        self.assertEqual(round(await self.get_balance(account2)/COIN, 1), 0)

        address2 = await d2f(account2.receiving.get_or_create_usable_address())
        hash2 = self.ledger.address_to_hash160(address2)
        tx = await d2f(self.ledger.transaction_class.pay(
            [self.ledger.transaction_class.output_class.pay_pubkey_hash(2*COIN, hash2)],
            [account1], account1
        ))
        await self.broadcast(tx)
        await self.on_transaction(tx)  # mempool
        await self.blockchain.generate(1)
        await self.on_transaction(tx)  # confirmed

        self.assertEqual(round(await self.get_balance(account1)/COIN, 1), 7.9)
        self.assertEqual(round(await self.get_balance(account2)/COIN, 1), 2.0)

        all_balances = await d2f(self.manager.get_balance())
        self.assertIn(self.ledger.get_id(), all_balances)
        self.assertEqual(round(all_balances[self.ledger.get_id()]/COIN, 1), 9.9)

        utxos = await d2f(self.account.get_unspent_outputs())
        tx = await d2f(self.ledger.transaction_class.liquidate(
            [utxos[0]], [account1], account1
        ))
        await self.broadcast(tx)
        await self.on_transaction(tx)  # mempool
        await self.blockchain.generate(1)
        await self.on_transaction(tx)  # confirmed
