import asyncio

from torba.testcase import IntegrationTestCase

import lbrynet.extras.wallet
from lbrynet.schema.claim import Claim
from lbrynet.wallet.transaction import Transaction, Output
from lbrynet.wallet.dewies import dewies_to_lbc as d2l, lbc_to_dewies as l2d


class BasicTransactionTest(IntegrationTestCase):

    LEDGER = lbrynet.wallet

    async def test_creating_updating_and_abandoning_claim_with_channel(self):

        await self.account.ensure_address_gap()

        address1, address2 = await self.account.receiving.get_addresses(limit=2, only_usable=True)
        sendtxid1 = await self.blockchain.send_to_address(address1, 5)
        sendtxid2 = await self.blockchain.send_to_address(address2, 5)
        await self.blockchain.generate(1)
        await asyncio.wait([
            self.on_transaction_id(sendtxid1),
            self.on_transaction_id(sendtxid2)
        ])

        self.assertEqual(d2l(await self.account.get_balance()), '10.0')

        channel = Claim()
        channel_txo = Output.pay_claim_name_pubkey_hash(
            l2d('1.0'), '@bar', channel, self.account.ledger.address_to_hash160(address1)
        )
        channel_txo.generate_channel_private_key()
        channel_tx = await Transaction.create([], [channel_txo], [self.account], self.account)

        stream = Claim()
        stream.stream.media_type = "video/mp4"
        stream_txo = Output.pay_claim_name_pubkey_hash(
            l2d('1.0'), 'foo', stream, self.account.ledger.address_to_hash160(address1)
        )
        stream_tx = await Transaction.create([], [channel_txo], [self.account], self.account)
        stream_tx._reset()
        stream_txo.sign(channel_txo, b'placeholder')
        await stream_tx.sign([self.account])

        await self.broadcast(channel_tx)
        await self.broadcast(stream_tx)
        await asyncio.wait([  # mempool
            self.ledger.wait(channel_tx),
            self.ledger.wait(stream_tx)
        ])
        await self.blockchain.generate(1)
        await asyncio.wait([  # confirmed
            self.ledger.wait(channel_tx),
            self.ledger.wait(stream_tx)
        ])

        self.assertEqual(d2l(await self.account.get_balance()), '7.983786')
        self.assertEqual(d2l(await self.account.get_balance(include_claims=True)), '9.983786')

        response = await self.ledger.resolve(0, 10, 'lbry://@bar/foo')
        self.assertIn('lbry://@bar/foo', response)
        self.assertIn('claim', response['lbry://@bar/foo'])

        abandon_tx = await Transaction.abandon([stream_tx.outputs[0]], [self.account], self.account)
        await self.broadcast(abandon_tx)
        await self.ledger.wait(abandon_tx)
        await self.blockchain.generate(1)
        await self.ledger.wait(abandon_tx)

        response = await self.ledger.resolve(0, 10, 'lbry://@bar/foo')
        self.assertNotIn('claim', response['lbry://@bar/foo'])

        # checks for expected format in inexistent URIs
        response = await self.ledger.resolve(0, 10, 'lbry://404', 'lbry://@404')
        self.assertEqual('URI lbry://404 cannot be resolved', response['lbry://404']['error'])
        self.assertEqual('URI lbry://@404 cannot be resolved', response['lbry://@404']['error'])
