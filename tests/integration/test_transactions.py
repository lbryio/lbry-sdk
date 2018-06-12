import asyncio
from orchstr8.testcase import IntegrationTestCase
from torba.constants import COIN


class BasicTransactionTests(IntegrationTestCase):

    VERBOSE = True

    async def test_sending_and_recieving(self):
        account1, account2 = self.account, self.wallet.generate_account(self.ledger)

        await account1.ensure_address_gap().asFuture(asyncio.get_event_loop())

        self.assertEqual(await self.get_balance(account1), 0)
        self.assertEqual(await self.get_balance(account2), 0)

        address = await account1.receiving.get_or_create_usable_address().asFuture(asyncio.get_event_loop())
        sendtxid = await self.blockchain.send_to_address(address.decode(), 5.5)
        await self.on_transaction(sendtxid)
        await self.blockchain.generate(1)
        await asyncio.sleep(5)

        self.assertEqual(await self.get_balance(account1), int(5.5*COIN))
        self.assertEqual(await self.get_balance(account2), 0)

        address = await account2.receiving.get_or_create_usable_address().asFuture(asyncio.get_event_loop())
        tx = await self.ledger.transaction_class.pay(
            [self.ledger.transaction_class.output_class.pay_pubkey_hash(2, self.ledger.address_to_hash160(address))],
            [account1], account1
        ).asFuture(asyncio.get_event_loop())
        await self.broadcast(tx)
        await self.on_transaction(tx.id.decode())
        await self.lbrycrd.generate(1)

        self.assertEqual(await self.get_balance(account1), int(3.5*COIN))
        self.assertEqual(await self.get_balance(account2), int(2.0*COIN))

