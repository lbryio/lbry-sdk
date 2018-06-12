import asyncio
from binascii import hexlify, unhexlify
from orchstr8.testcase import IntegrationTestCase
from lbryschema.claim import ClaimDict


class BasicTransactionTests(IntegrationTestCase):

    VERBOSE = True

    async def test_sending_and_recieving(self):

        self.assertEqual(await self.get_balance(), 0.0)

        address = self.account.get_least_used_receiving_address()
        sendtxid = await self.blockchain.send_to_address(address.decode(), 5.5)
        await self.blockchain.generate(1)
        await self.on_transaction(sendtxid)

        self.assertAlmostEqual(await self.get_balance(), 5.5, places=2)

        lbrycrd_address = await self.blockchain.get_raw_change_address()
        tx = self.manager.send_amount_to_address(5, lbrycrd_address)
        await self.broadcast(tx)
        await self.on_transaction(tx.id.decode())
        await self.blockchain.generate(1)

        self.assertAlmostEqual(await self.get_balance(), 0.5, places=2)


example_claim_dict = {
    "version": "_0_0_1",
    "claimType": "streamType",
    "stream": {
        "source": {
            "source": "d5169241150022f996fa7cd6a9a1c421937276a3275eb912790bd07ba7aec1fac5fd45431d226b8fb402691e79aeb24b",
            "version": "_0_0_1",
            "contentType": "video/mp4",
            "sourceType": "lbry_sd_hash"
        },
        "version": "_0_0_1",
        "metadata": {
            "license": "LBRY Inc",
            "description": "What is LBRY? An introduction with Alex Tabarrok",
            "language": "en",
            "title": "What is LBRY?",
            "author": "Samuel Bryan",
            "version": "_0_1_0",
            "nsfw": False,
            "licenseUrl": "",
            "preview": "",
            "thumbnail": "https://s3.amazonaws.com/files.lbry.io/logo.png"
        }
    }
}


class ClaimTransactionTests(IntegrationTestCase):

    VERBOSE = True

    async def test_creating_updating_and_abandoning_claim(self):

        address = self.account.get_least_used_receiving_address()
        sendtxid = await self.lbrycrd.send_to_address(address.decode(), 9.0)
        await self.lbrycrd.generate(1)
        await self.on_transaction(sendtxid)

        self.assertAlmostEqual(self.manager.get_balance(), 9, places=2)

        claim = ClaimDict.load_dict(example_claim_dict)
        tx = self.manager.claim_name(b'foo', 5, hexlify(claim.serialized))
        await self.broadcast(tx)
        await self.on_transaction(tx.id.decode())
        await self.lbrycrd.generate(1)

        await asyncio.sleep(2)

        self.assertAlmostEqual(self.manager.get_balance(), 9, places=2)

        await asyncio.sleep(2)

        response = await self.resolve('lbry://foo')
        print(response)


#class AbandonClaimLookup(IntegrationTestCase):
#
#    async def skip_test_abandon_claim(self):
#        address = yield self.lbry.wallet.get_least_used_address()
#        yield self.lbrycrd.sendtoaddress(address, 0.0003 - 0.0000355)
#        yield self.lbrycrd.generate(1)
#        yield self.lbry.wallet.update_balance()
#        yield threads.deferToThread(time.sleep, 5)
#        print(self.lbry.wallet.get_balance())
#        claim = yield self.lbry.wallet.claim_new_channel('@test', 0.000096)
#        yield self.lbrycrd.generate(1)
#        print('='*10 + 'CLAIM' + '='*10)
#        print(claim)
#        yield self.lbrycrd.decoderawtransaction(claim['tx'])
#        abandon = yield self.lbry.wallet.abandon_claim(claim['claim_id'], claim['txid'], claim['nout'])
#        print('='*10 + 'ABANDON' + '='*10)
#        print(abandon)
#        yield self.lbrycrd.decoderawtransaction(abandon['tx'])
#        yield self.lbrycrd.generate(1)
#        yield self.lbrycrd.getrawtransaction(abandon['txid'])
#
#        yield self.lbry.wallet.update_balance()
#        yield threads.deferToThread(time.sleep, 5)
#        print('='*10 + 'FINAL BALANCE' + '='*10)
#        print(self.lbry.wallet.get_balance())
