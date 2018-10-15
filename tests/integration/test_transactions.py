import asyncio
from orchstr8.testcase import IntegrationTestCase
from torba.constants import COIN


class BasicTransactionTests(IntegrationTestCase):

    VERBOSE = False

    async def test_sending_and_receiving(self):
        account1, account2 = self.account, self.wallet.generate_account(self.ledger)
        await self.ledger.update_account(account2)

        self.assertEqual(await self.get_balance(account1), 0)
        self.assertEqual(await self.get_balance(account2), 0)

        sendtxids = []
        for i in range(5):
            address1 = await account1.receiving.get_or_create_usable_address()
            sendtxid = await self.blockchain.send_to_address(address1, 1.1)
            sendtxids.append(sendtxid)
            await self.on_transaction_id(sendtxid)  # mempool
        await self.blockchain.generate(1)
        await asyncio.wait([  # confirmed
            self.on_transaction_id(txid) for txid in sendtxids
        ])

        self.assertEqual(round(await self.get_balance(account1)/COIN, 1), 5.5)
        self.assertEqual(round(await self.get_balance(account2)/COIN, 1), 0)

        address2 = await account2.receiving.get_or_create_usable_address()
        hash2 = self.ledger.address_to_hash160(address2)
        tx = await self.ledger.transaction_class.create(
            [],
            [self.ledger.transaction_class.output_class.pay_pubkey_hash(2*COIN, hash2)],
            [account1], account1
        )
        await self.broadcast(tx)
        await self.on_transaction(tx)  # mempool
        await self.blockchain.generate(1)
        await self.on_transaction(tx)  # confirmed

        self.assertEqual(round(await self.get_balance(account1)/COIN, 1), 3.5)
        self.assertEqual(round(await self.get_balance(account2)/COIN, 1), 2.0)

        utxos = await self.account.get_utxos()
        tx = await self.ledger.transaction_class.create(
            [self.ledger.transaction_class.input_class.spend(utxos[0])],
            [],
            [account1], account1
        )
        await self.broadcast(tx)
        await self.on_transaction(tx)  # mempool
        await self.blockchain.generate(1)
        await self.on_transaction(tx)  # confirmed

        txs = await account1.get_transactions()
        tx = txs[1]
        self.assertEqual(round(tx.inputs[0].txo_ref.txo.amount/COIN, 1), 1.1)
        self.assertEqual(round(tx.inputs[1].txo_ref.txo.amount/COIN, 1), 1.1)
        self.assertEqual(round(tx.outputs[0].amount/COIN, 1), 2.0)
        self.assertEqual(tx.outputs[0].get_address(self.ledger), address2)
        self.assertEqual(tx.outputs[0].is_change, False)
        self.assertEqual(tx.outputs[1].is_change, True)
