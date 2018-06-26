import asyncio
from orchstr8.testcase import IntegrationTestCase
from torba.constants import COIN


class BasicTransactionTests(IntegrationTestCase):

    VERBOSE = True

    async def test_sending_and_receiving(self):
        account1, account2 = self.account, self.wallet.generate_account(self.ledger)

        await account1.ensure_address_gap().asFuture(asyncio.get_event_loop())

        self.assertEqual(await self.get_balance(account1), 0)
        self.assertEqual(await self.get_balance(account2), 0)

        address = await account1.receiving.get_or_create_usable_address().asFuture(asyncio.get_event_loop())
        sendtxid = await self.blockchain.send_to_address(address.decode(), 5.5)
        await self.on_transaction_id(sendtxid)  #mempool
        await self.blockchain.generate(1)
        await self.on_transaction_id(sendtxid)  #confirmed

        self.assertEqual(await self.get_balance(account1), int(5.5*COIN))
        self.assertEqual(await self.get_balance(account2), 0)

        address = await account2.receiving.get_or_create_usable_address().asFuture(asyncio.get_event_loop())
        hash1 = self.ledger.address_to_hash160(address)
        tx = await self.ledger.transaction_class.pay(
            [self.ledger.transaction_class.output_class.pay_pubkey_hash(2*COIN, hash1)],
            [account1], account1
        ).asFuture(asyncio.get_event_loop())
        await self.broadcast(tx)
        await self.on_transaction(tx)  #mempool

        tx2 = await self.ledger.transaction_class.pay(
            [self.ledger.transaction_class.output_class.pay_pubkey_hash(1*COIN, hash1)],
            [account1], account1
        ).asFuture(asyncio.get_event_loop())
        await self.broadcast(tx2)
        await self.on_transaction(tx2)  #mempool

        await self.blockchain.generate(1)
        await asyncio.wait([
            self.on_header(202),
            self.on_transaction(tx),
            self.on_transaction(tx2),
        ])

        #self.assertEqual(round(await self.get_balance(account1)/COIN, 1), 3.5)
        #self.assertEqual(round(await self.get_balance(account2)/COIN, 1), 2.0)

        self.assertTrue(await self.ledger.is_valid_transaction(tx, 202).asFuture(asyncio.get_event_loop()))
        self.assertTrue(await self.ledger.is_valid_transaction(tx2, 202).asFuture(asyncio.get_event_loop()))
