import asyncio
from binascii import hexlify
from orchstr8.testcase import IntegrationTestCase
from torba.constants import COIN
from lbrynet.wallet.transaction import Transaction, Input, Output


class BasicTransactionTests(IntegrationTestCase):

    VERBOSE = True

    async def test_sending_and_recieving(self):

        self.assertEqual(await self.lbrycrd.get_balance(), 10.0)
        self.assertEqual(self.manager.get_balance(), 0.0)

        address = self.account.get_least_used_receiving_address()
        sendtxid = await self.lbrycrd.send_to_address(address.decode(), 5.5)
        await self.lbrycrd.generate(1)
        await self.on_transaction(sendtxid)

        self.assertAlmostEqual(await self.lbrycrd.get_balance(), 5.5, places=2)
        self.assertEqual(self.manager.get_balance(), 5.5)

        lbrycrd_address = await self.lbrycrd.get_raw_change_address()
        tx = self.manager.send_amount_to_address(5, lbrycrd_address)
        await self.broadcast(tx)
        await self.on_transaction(tx.id.decode())
        await self.lbrycrd.generate(1)

        self.assertAlmostEqual(await self.lbrycrd.get_balance(), 11.5, places=2)
        #self.assertEqual(self.manager.get_balance(), 0.5)


class AbandonClaimLookup(IntegrationTestCase):

    async def skip_test_abandon_claim(self):
        address = yield self.lbry.wallet.get_least_used_address()
        yield self.lbrycrd.sendtoaddress(address, 0.0003 - 0.0000355)
        yield self.lbrycrd.generate(1)
        yield self.lbry.wallet.update_balance()
        yield threads.deferToThread(time.sleep, 5)
        print(self.lbry.wallet.get_balance())
        claim = yield self.lbry.wallet.claim_new_channel('@test', 0.000096)
        yield self.lbrycrd.generate(1)
        print('='*10 + 'CLAIM' + '='*10)
        print(claim)
        yield self.lbrycrd.decoderawtransaction(claim['tx'])
        abandon = yield self.lbry.wallet.abandon_claim(claim['claim_id'], claim['txid'], claim['nout'])
        print('='*10 + 'ABANDON' + '='*10)
        print(abandon)
        yield self.lbrycrd.decoderawtransaction(abandon['tx'])
        yield self.lbrycrd.generate(1)
        yield self.lbrycrd.getrawtransaction(abandon['txid'])

        yield self.lbry.wallet.update_balance()
        yield threads.deferToThread(time.sleep, 5)
        print('='*10 + 'FINAL BALANCE' + '='*10)
        print(self.lbry.wallet.get_balance())
