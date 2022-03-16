from typing import Optional
from lbry.testcase import CommandTestCase
from scribe.schema.purchase import Purchase
from lbry.wallet.transaction import Transaction
from lbry.wallet.dewies import lbc_to_dewies, dewies_to_lbc


class PurchaseCommandTests(CommandTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.merchant_address = await self.blockchain.get_raw_change_address()

    async def priced_stream(
        self, name='stream', price: Optional[str] = '0.2', currency='LBC', mine=False
    ) -> Transaction:
        kwargs = {}
        if price and currency:
            kwargs = {
                'fee_amount': price,
                'fee_currency': currency,
                'fee_address': self.merchant_address
            }
        if not mine:
            kwargs['claim_address'] = self.merchant_address
        file_path = self.create_upload_file(data=b'high value content')
        tx = await self.daemon.jsonrpc_stream_create(
            name, '0.01', file_path=file_path, **kwargs
        )
        await self.ledger.wait(tx)
        await self.generate(1)
        await self.ledger.wait(tx)
        await self.daemon.jsonrpc_file_delete(claim_name=name)
        return tx

    async def create_purchase(self, name, price):
        stream = await self.priced_stream(name, price)
        claim_id = stream.outputs[0].claim_id
        purchase = await self.daemon.jsonrpc_purchase_create(claim_id)
        await self.ledger.wait(purchase)
        return claim_id

    async def assertStreamPurchased(self, stream: Transaction, operation):

        await self.account.release_all_outputs()
        buyer_balance = await self.account.get_balance()
        merchant_balance = lbc_to_dewies(await self.blockchain.get_balance())
        pre_purchase_count = (await self.daemon.jsonrpc_purchase_list())['total_items']
        purchase = await operation()
        stream_txo, purchase_txo = stream.outputs[0], purchase.outputs[0]
        stream_fee = stream_txo.claim.stream.fee
        self.assertEqual(stream_fee.dewies, purchase_txo.amount)
        self.assertEqual(stream_fee.address, purchase_txo.get_address(self.ledger))

        await self.ledger.wait(purchase)
        await self.generate(1)
        merchant_balance += lbc_to_dewies('1.0')  # block reward
        await self.ledger.wait(purchase)

        self.assertEqual(
            await self.account.get_balance(), buyer_balance - (purchase.input_sum-purchase.outputs[2].amount))
        self.assertEqual(
            str(float(await self.blockchain.get_balance())),
            dewies_to_lbc(merchant_balance + purchase_txo.amount)
        )

        purchases = await self.daemon.jsonrpc_purchase_list()
        self.assertEqual(purchases['total_items'], pre_purchase_count+1)

        tx = purchases['items'][0].tx_ref.tx
        self.assertEqual(len(tx.outputs), 3)  # purchase txo, purchase data, change

        txo0 = tx.outputs[0]
        txo1 = tx.outputs[1]
        self.assertEqual(txo0.purchase, txo1)  # purchase txo has reference to purchase data
        self.assertTrue(txo1.is_purchase_data)
        self.assertTrue(txo1.can_decode_purchase_data)
        self.assertIsInstance(txo1.purchase_data, Purchase)
        self.assertEqual(txo1.purchase_data.claim_id, stream_txo.claim_id)

    async def test_purchasing(self):
        stream = await self.priced_stream()
        claim_id = stream.outputs[0].claim_id

        # explicit purchase of claim
        await self.assertStreamPurchased(stream, lambda: self.daemon.jsonrpc_purchase_create(claim_id))

        # check that `get` doesn't purchase it again
        balance = await self.account.get_balance()
        response = await self.daemon.jsonrpc_get('lbry://stream')
        self.assertIsNone(response.content_fee)
        self.assertEqual(await self.account.get_balance(), balance)
        self.assertItemCount(await self.daemon.jsonrpc_purchase_list(), 1)

        # `get` does purchase a stream we don't have yet
        another_stream = await self.priced_stream('another')

        async def imagine_its_a_lambda():
            response = await self.daemon.jsonrpc_get('lbry://another')
            return response.content_fee

        await self.assertStreamPurchased(another_stream, imagine_its_a_lambda)

        # purchase non-existent claim fails
        with self.assertRaisesRegex(Exception, "Could not find claim with claim_id"):
            await self.daemon.jsonrpc_purchase_create('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')

        # purchase stream with no price fails
        no_price_stream = await self.priced_stream('no_price_stream', price=None)
        with self.assertRaisesRegex(Exception, "does not have a purchase price"):
            await self.daemon.jsonrpc_purchase_create(no_price_stream.outputs[0].claim_id)

        # purchase claim you already own fails
        with self.assertRaisesRegex(Exception, "You already have a purchase for claim_id"):
            await self.daemon.jsonrpc_purchase_create(claim_id)

        # force purchasing claim you already own
        await self.assertStreamPurchased(
            stream, lambda: self.daemon.jsonrpc_purchase_create(claim_id, allow_duplicate_purchase=True)
        )

        # purchase by uri
        abc_stream = await self.priced_stream('abc')
        await self.assertStreamPurchased(abc_stream, lambda: self.daemon.jsonrpc_purchase_create(url='lbry://abc'))

        # purchase without valid exchange rate fails
        erm = self.daemon.component_manager.get_component('exchange_rate_manager')
        for feed in erm.market_feeds:
            feed.last_check -= 10_000
        with self.assertRaisesRegex(Exception, "Unable to convert 50 from USD to LBC"):
            await self.daemon.jsonrpc_purchase_create(claim_id, allow_duplicate_purchase=True)

    async def test_purchase_and_transaction_list(self):
        self.assertItemCount(await self.daemon.jsonrpc_purchase_list(), 0)
        self.assertItemCount(await self.daemon.jsonrpc_transaction_list(), 1)

        claim_id1 = await self.create_purchase('a', '1.0')
        claim_id2 = await self.create_purchase('b', '1.0')

        result = await self.out(self.daemon.jsonrpc_purchase_list())
        self.assertItemCount(await self.daemon.jsonrpc_transaction_list(), 5)
        self.assertItemCount(result, 2)
        self.assertEqual(result['items'][0]['type'], 'purchase')
        self.assertEqual(result['items'][0]['claim_id'], claim_id2)
        self.assertNotIn('claim', result['items'][0])
        self.assertEqual(result['items'][1]['type'], 'purchase')
        self.assertEqual(result['items'][1]['claim_id'], claim_id1)
        self.assertNotIn('claim', result['items'][1])

        result = await self.out(self.daemon.jsonrpc_purchase_list(resolve=True))
        self.assertEqual(result['items'][0]['claim']['name'], 'b')
        self.assertEqual(result['items'][1]['claim']['name'], 'a')

        result = await self.daemon.jsonrpc_transaction_list()
        self.assertEqual(result['items'][0]['purchase_info'][0]['claim_id'], claim_id2)
        self.assertEqual(result['items'][2]['purchase_info'][0]['claim_id'], claim_id1)

        result = await self.claim_search(include_purchase_receipt=True)
        self.assertEqual(result[0]['claim_id'], result[0]['purchase_receipt']['claim_id'])
        self.assertEqual(result[1]['claim_id'], result[1]['purchase_receipt']['claim_id'])

        url = result[0]['canonical_url']
        resolve = await self.resolve(url, include_purchase_receipt=True)
        self.assertEqual(result[0]['claim_id'], resolve['purchase_receipt']['claim_id'])

        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 0)
        await self.daemon.jsonrpc_get('lbry://a')
        await self.daemon.jsonrpc_get('lbry://b')
        files = await self.file_list()
        self.assertEqual(files[0]['claim_id'], files[0]['purchase_receipt']['claim_id'])
        self.assertEqual(files[1]['claim_id'], files[1]['purchase_receipt']['claim_id'])

    async def test_seller_can_spend_received_purchase_funds(self):
        self.merchant_address = await self.account.receiving.get_or_create_usable_address()
        daemon2 = await self.add_daemon()
        address2 = await daemon2.wallet_manager.default_account.receiving.get_or_create_usable_address()
        await self.send_to_address_and_wait(address2, 2, 1, ledger=daemon2.ledger)

        stream = await self.priced_stream('a', '1.0')
        await self.assertBalance(self.account, '9.987893')
        self.assertItemCount(await self.daemon.jsonrpc_utxo_list(), 1)

        purchase = await daemon2.jsonrpc_purchase_create(stream.outputs[0].claim_id)
        await self.ledger.wait(purchase)
        await self.generate(1)
        await self.ledger.wait(purchase)

        # confirm that available and reserved take into account purchase received
        self.assertEqual(await self.account.get_detailed_balance(), {
            'total': 1099789300,
            'available': 1098789300,
            'reserved': 1000000,
            'reserved_subtotals': {'claims': 1000000, 'supports': 0, 'tips': 0}
        })
        self.assertItemCount(await self.daemon.jsonrpc_utxo_list(), 2)

        spend = await self.daemon.jsonrpc_wallet_send('10.5', address2)
        await self.ledger.wait(spend)
        await self.generate(1)
        await self.ledger.wait(spend)
        await self.assertBalance(self.account, '0.487695')
        self.assertItemCount(await self.daemon.jsonrpc_utxo_list(), 1)

    async def test_owner_not_required_purchase_own_content(self):
        await self.priced_stream(mine=True)
        # check that `get` doesn't purchase own claim
        balance = await self.account.get_balance()
        response = await self.daemon.jsonrpc_get('lbry://stream')
        self.assertIsNone(response.content_fee)
        self.assertEqual(await self.account.get_balance(), balance)
        self.assertItemCount(await self.daemon.jsonrpc_purchase_list(), 0)
