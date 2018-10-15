import asyncio

from orchstr8.testcase import IntegrationTestCase
from lbryschema.claim import ClaimDict
from lbrynet.wallet.transaction import Transaction
from lbrynet.wallet.account import generate_certificate
from lbrynet.wallet.dewies import dewies_to_lbc as d2l, lbc_to_dewies as l2d

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


class BasicTransactionTest(IntegrationTestCase):

    VERBOSE = False

    async def test_creating_updating_and_abandoning_claim_with_channel(self):

        await self.account.ensure_address_gap()

        address1, address2 = await self.account.receiving.get_addresses(limit=2, only_usable=True)
        sendtxid1 = await self.blockchain.send_to_address(address1, 5)
        sendtxid2 = await self.blockchain.send_to_address(address2, 5)
        await self.blockchain.generate(1)
        await asyncio.wait([
            self.on_transaction_id(sendtxid1),
            self.on_transaction_id(sendtxid2),
        ])

        self.assertEqual(d2l(await self.account.get_balance()), '10.0')

        cert, key = generate_certificate()
        cert_tx = await Transaction.claim('@bar', cert, l2d('1.0'), address1, [self.account], self.account)
        claim = ClaimDict.load_dict(example_claim_dict)
        claim = claim.sign(key, address1, cert_tx.outputs[0].claim_id)
        claim_tx = await Transaction.claim('foo', claim, l2d('1.0'), address1, [self.account], self.account)

        await self.broadcast(cert_tx)
        await self.broadcast(claim_tx)
        await asyncio.wait([  # mempool
            self.on_transaction(claim_tx),
            self.on_transaction(cert_tx),
        ])
        await self.blockchain.generate(1)
        await asyncio.wait([  # confirmed
            self.on_transaction(claim_tx),
            self.on_transaction(cert_tx),
        ])

        self.assertEqual(d2l(await self.account.get_balance(confirmations=1)), '7.985786')
        self.assertEqual(d2l(await self.account.get_balance(include_claims=True)), '9.985786')

        response = await self.ledger.resolve(0, 10, 'lbry://@bar/foo')
        self.assertIn('lbry://@bar/foo', response)
        self.assertIn('claim', response['lbry://@bar/foo'])

        abandon_tx = await Transaction.abandon([claim_tx.outputs[0]], [self.account], self.account)
        await self.broadcast(abandon_tx)
        await self.on_transaction(abandon_tx)
        await self.blockchain.generate(1)
        await self.on_transaction(abandon_tx)

        response = await self.ledger.resolve(0, 10, 'lbry://@bar/foo')
        self.assertNotIn('claim', response['lbry://@bar/foo'])

        # checks for expected format in inexistent URIs
        response = await self.ledger.resolve(0, 10, 'lbry://404', 'lbry://@404')
        self.assertEqual('URI lbry://404 cannot be resolved', response['lbry://404']['error'])
        self.assertEqual('URI lbry://@404 cannot be resolved', response['lbry://@404']['error'])
