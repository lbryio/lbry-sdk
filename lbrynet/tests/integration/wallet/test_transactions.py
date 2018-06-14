import asyncio
from binascii import hexlify, unhexlify
from orchstr8.testcase import IntegrationTestCase
from lbryschema.claim import ClaimDict
from torba.constants import COIN
from lbrynet.wallet.manager import LbryWalletManager


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
    WALLET_MANAGER = LbryWalletManager

    async def test_creating_updating_and_abandoning_claim(self):

        await self.account.ensure_address_gap().asFuture(asyncio.get_event_loop())

        address = await self.account.receiving.get_or_create_usable_address().asFuture(asyncio.get_event_loop())
        sendtxid = await self.blockchain.send_to_address(address.decode(), 10)
        await self.on_transaction(sendtxid)  #mempool
        await self.blockchain.generate(1)
        await self.on_transaction(sendtxid)  #confirmed

        self.assertEqual(round(await self.get_balance(self.account)/COIN, 1), 10.0)

        claim = ClaimDict.load_dict(example_claim_dict)
        tx = self.manager.claim_name(b'foo', 1*COIN, hexlify(claim.serialized))
        await self.broadcast(tx)
        await self.on_transaction(tx.hex_id.decode())  #mempool
        await self.blockchain.generate(1)
        await self.on_transaction(tx.hex_id.decode())  #confirmed

        self.assertAlmostEqual(self.manager.get_balance(), 9, places=2)

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
