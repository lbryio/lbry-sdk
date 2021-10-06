import asyncio

from lbry.testcase import IntegrationTestCase

import lbry.wallet
from lbry.schema.claim import Claim
from lbry.wallet.transaction import Transaction, Output, Input
from lbry.wallet.dewies import dewies_to_lbc as d2l, lbc_to_dewies as l2d


class BasicTransactionTest(IntegrationTestCase):

    LEDGER = lbry.wallet

    async def test_creating_updating_and_abandoning_claim_with_channel(self):

        await self.account.ensure_address_gap()

        address1, address2 = await self.account.receiving.get_addresses(limit=2, only_usable=True)
        notifications = asyncio.create_task(asyncio.wait(
            [asyncio.ensure_future(self.on_address_update(address1)),
             asyncio.ensure_future(self.on_address_update(address2))]
        ))
        sendtxid1 = await self.blockchain.send_to_address(address1, 5)
        sendtxid2 = await self.blockchain.send_to_address(address2, 5)
        await self.blockchain.generate(1)
        await notifications

        self.assertEqual(d2l(await self.account.get_balance()), '10.0')

        channel = Claim()
        channel_txo = Output.pay_claim_name_pubkey_hash(
            l2d('1.0'), '@bar', channel, self.account.ledger.address_to_hash160(address1)
        )
        await channel_txo.generate_channel_private_key()
        channel_txo.script.generate()
        channel_tx = await Transaction.create([], [channel_txo], [self.account], self.account)

        stream = Claim()
        stream.stream.source.media_type = "video/mp4"
        stream_txo = Output.pay_claim_name_pubkey_hash(
            l2d('1.0'), 'foo', stream, self.account.ledger.address_to_hash160(address1)
        )
        stream_tx = await Transaction.create([], [stream_txo], [self.account], self.account)
        stream_txo.sign(channel_txo)
        await stream_tx.sign([self.account])

        notifications = asyncio.create_task(asyncio.wait(
            [asyncio.ensure_future(self.ledger.wait(channel_tx)), asyncio.ensure_future(self.ledger.wait(stream_tx))]
        ))

        await self.broadcast(channel_tx)
        await self.broadcast(stream_tx)
        await notifications
        notifications = asyncio.create_task(asyncio.wait(
            [asyncio.ensure_future(self.ledger.wait(channel_tx)), asyncio.ensure_future(self.ledger.wait(stream_tx))]
        ))
        await self.blockchain.generate(1)
        await notifications
        self.assertEqual(d2l(await self.account.get_balance()), '7.985786')
        self.assertEqual(d2l(await self.account.get_balance(include_claims=True)), '9.985786')

        response = await self.ledger.resolve([], ['lbry://@bar/foo'])
        self.assertEqual(response['lbry://@bar/foo'].claim.claim_type, 'stream')

        abandon_tx = await Transaction.create([Input.spend(stream_tx.outputs[0])], [], [self.account], self.account)
        notify = asyncio.create_task(self.ledger.wait(abandon_tx))
        await self.broadcast(abandon_tx)
        await notify
        notify = asyncio.create_task(self.ledger.wait(abandon_tx))
        await self.blockchain.generate(1)
        await notify

        response = await self.ledger.resolve([], ['lbry://@bar/foo'])
        self.assertIn('error', response['lbry://@bar/foo'])

        # checks for expected format in inexistent URIs
        response = await self.ledger.resolve([], ['lbry://404', 'lbry://@404', 'lbry://@404/404'])
        self.assertEqual('Could not find claim at "lbry://404".', response['lbry://404']['error']['text'])
        self.assertEqual('Could not find channel in "lbry://@404".', response['lbry://@404']['error']['text'])
        self.assertEqual('Could not find channel in "lbry://@404/404".', response['lbry://@404/404']['error']['text'])
