from lbry.testcase import CommandTestCase


class TransactionCommandsTestCase(CommandTestCase):

    async def test_transaction_show(self):
        # local tx
        result = await self.out(self.daemon.jsonrpc_account_send(
            '5.0', await self.daemon.jsonrpc_address_unused(self.account.id)
        ))
        await self.confirm_tx(result['txid'])
        tx = await self.daemon.jsonrpc_transaction_show(result['txid'])
        self.assertEqual(tx.id, result['txid'])

        # someone's tx
        change_address = await self.blockchain.get_raw_change_address()
        sendtxid = await self.blockchain.send_to_address(change_address, 10)
        tx = await self.daemon.jsonrpc_transaction_show(sendtxid)
        self.assertEqual(tx.id, sendtxid)
        self.assertEqual(tx.height, -1)
        await self.generate(1)
        tx = await self.daemon.jsonrpc_transaction_show(sendtxid)
        self.assertEqual(tx.height, self.ledger.headers.height)

        # inexistent
        result = await self.daemon.jsonrpc_transaction_show('0'*64)
        self.assertFalse(result['success'])

    async def test_utxo_release(self):
        sendtxid = await self.blockchain.send_to_address(
            await self.account.receiving.get_or_create_usable_address(), 1
        )
        await self.confirm_tx(sendtxid)
        await self.assertBalance(self.account, '11.0')
        await self.ledger.reserve_outputs(await self.account.get_utxos())
        await self.assertBalance(self.account, '0.0')
        await self.daemon.jsonrpc_utxo_release()
        await self.assertBalance(self.account, '11.0')

    async def test_granular_balances(self):
        initial_balance = await self.daemon.jsonrpc_account_balance()
        self.assertEqual({
            'tips_received': '0.0',
            'tips_sent': '0.0',
            'total': '10.0',
            'available': '10.0',
            'reserved': {'total': '0.0', 'claims': '0.0', 'supports': '0.0'}
        }, initial_balance)
        first_claim_id = self.get_claim_id(await self.stream_create('granularity', bid='3.0'))
        await self.stream_update(first_claim_id, data=b'news', bid='1.0')
        await self.support_create(first_claim_id, bid='2.0')
        second_account_id = (await self.out(self.daemon.jsonrpc_account_create("Tip-er")))['id']
        second_accound_address = await self.daemon.jsonrpc_address_unused(second_account_id)
        await self.confirm_tx((await self.daemon.jsonrpc_account_send('1.0', second_accound_address)).id)
        second_claim_id = self.get_claim_id(await self.stream_create(
            name='granularity-is-cool', account_id=second_account_id, bid='0.1'))
        await self.daemon.jsonrpc_support_create(second_claim_id, '0.5', tip=True)
        await self.confirm_tx((await self.daemon.jsonrpc_support_create(
            first_claim_id, '0.3', tip=True, account_id=second_account_id)).id)
        final_balance = await self.daemon.jsonrpc_account_balance()
        self.assertEqual({
            'tips_received': '0.0',
            'tips_sent': '0.0',
            'total': '8.777264',
            'available': '5.477264',
            'reserved': {'claims': '1.0', 'supports': '2.3', 'total': '3.3'}
        }, final_balance)
