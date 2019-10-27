from lbry.testcase import CommandTestCase
from lbry.schema.purchase import Purchase


class PurchaseCommand(CommandTestCase):

    async def test_purchase_via_get(self):
        starting_balance = await self.blockchain.get_balance()
        target_address = await self.blockchain.get_raw_change_address()
        stream = await self.stream_create(
            'stream', '0.01', data=b'high value content',
            fee_currency='LBC', fee_amount='1.0', fee_address=target_address
        )
        await self.daemon.jsonrpc_file_delete(claim_name='stream')

        await self.assertBalance(self.account, '9.977893')
        response = await self.daemon.jsonrpc_get('lbry://stream')
        tx = response.content_fee
        await self.ledger.wait(tx)
        await self.assertBalance(self.account, '8.977752')

        self.assertEqual(len(tx.outputs), 3)
        txo = tx.outputs[1]
        self.assertTrue(txo.is_purchase_data)
        self.assertTrue(txo.can_decode_purchase_data)
        self.assertIsInstance(txo.purchase_data, Purchase)
        self.assertEqual(txo.purchase_data.claim_id, self.get_claim_id(stream))

        await self.generate(1)
        self.assertEqual(
            await self.blockchain.get_balance(),
            starting_balance +
            2.0 +  # block rewards
            1.0    # content payment
        )
