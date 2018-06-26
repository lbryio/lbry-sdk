import asyncio
from binascii import hexlify

from orchstr8.testcase import IntegrationTestCase, d2f
from lbryschema.claim import ClaimDict
from torba.constants import COIN
from lbrynet.wallet.transaction import Transaction
from lbrynet.wallet.account import generate_certificate

import lbryschema
lbryschema.BLOCKCHAIN_NAME = 'lbrycrd_regtest'


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


class BasicTransactionTests(IntegrationTestCase):

    VERBOSE = True

    async def test_creating_updating_and_abandoning_claim_with_channel(self):

        await d2f(self.account.ensure_address_gap())

        address1, address2 = await d2f(self.account.receiving.get_usable_addresses(2))
        sendtxid1 = await self.blockchain.send_to_address(address1.decode(), 5)
        sendtxid2 = await self.blockchain.send_to_address(address2.decode(), 5)
        await self.blockchain.generate(1)
        await asyncio.wait([
            self.on_transaction_id(sendtxid1),
            self.on_transaction_id(sendtxid2),
        ])

        self.assertEqual(round(await self.get_balance(self.account)/COIN, 1), 10.0)

        cert, key = generate_certificate()
        cert_tx = await d2f(Transaction.claim(b'@bar', cert, 1*COIN, address1, [self.account], self.account))
        claim = ClaimDict.load_dict(example_claim_dict)
        claim = claim.sign(key, address1, hexlify(cert_tx.get_claim_id(0)))
        tx = await d2f(Transaction.claim(b'foo', claim, 1*COIN, address1, [self.account], self.account))

        await self.broadcast(cert_tx)
        await self.broadcast(tx)
        await asyncio.wait([  # mempool
            self.on_transaction(tx),
            self.on_transaction(cert_tx),
        ])
        await self.blockchain.generate(1)
        await asyncio.wait([  # confirmed
            self.on_transaction(tx),
            self.on_transaction(cert_tx),
        ])

        self.assertEqual(round(await self.get_balance(self.account)/COIN, 1), 10.0)

        header = self.ledger.headers[len(self.ledger.headers)-1]
        response = await d2f(self.ledger.resolve(self.ledger.headers._hash_header(header), 'lbry://@bar/foo'))
        self.assertIn('lbry://@bar/foo', response)


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
