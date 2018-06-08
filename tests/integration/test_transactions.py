import asyncio
from orchstr8.testcase import IntegrationTestCase
from torba.constants import COIN


class BasicTransactionTests(IntegrationTestCase):

    VERBOSE = True

    async def test_sending_and_recieving(self):
        account1, account2 = self.account, self.wallet.generate_account(self.ledger)

        self.assertEqual(await self.get_balance(account1), 0)
        self.assertEqual(await self.get_balance(account2), 0)

        address = await account1.get_least_used_receiving_address().asFuture(asyncio.get_event_loop())
        sendtxid = await self.blockchain.send_to_address(address.decode(), 5.5)
        await self.blockchain.generate(1)
        await self.on_transaction(sendtxid)

        self.assertEqual(await self.get_balance(account1), int(5.5*COIN))
        self.assertEqual(await self.get_balance(account2), 0)

        address = await account2.get_least_used_receiving_address().asFuture(asyncio.get_event_loop())
        sendtxid = await self.blockchain.send_to_address(address.decode(), 5.5)
        await self.broadcast(tx)
        await self.on_transaction(tx.id.decode())
        await self.lbrycrd.generate(1)

        self.assertEqual(await self.get_balance(account1), int(3.0*COIN))
        self.assertEqual(await self.get_balance(account2), int(2.5*COIN))

