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
        account_balance = self.daemon.jsonrpc_account_balance

        self.assertEqual(await account_balance(reserved_subtotals=False), {
            'total': '10.0',
            'available': '10.0',
            'reserved': '0.0',
            'reserved_subtotals': None
        })

        self.assertEqual(await account_balance(reserved_subtotals=True), {
            'total': '10.0',
            'available': '10.0',
            'reserved': '0.0',
            'reserved_subtotals': {'claims': '0.0', 'supports': '0.0', 'tips': '0.0'}
        })

        # claim with update + supporting our own claim
        stream1 = await self.stream_create('granularity', '3.0')
        await self.stream_update(self.get_claim_id(stream1), data=b'news', bid='1.0')
        await self.support_create(self.get_claim_id(stream1), '2.0')
        self.assertEqual(await account_balance(reserved_subtotals=True), {
            'total': '9.977534',
            'available': '6.977534',
            'reserved': '3.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.0'}
        })

        account2 = await self.daemon.jsonrpc_account_create("Tip-er")
        address2 = await self.daemon.jsonrpc_address_unused(account2.id)

        # send lbc to someone else
        tx = await self.daemon.jsonrpc_account_send('1.0', address2)
        await self.confirm_tx(tx.id)
        self.assertEqual(await account_balance(reserved_subtotals=True), {
            'total': '8.97741',
            'available': '5.97741',
            'reserved': '3.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.0'}
        })

        # tip received
        support1 = await self.support_create(
            self.get_claim_id(stream1), '0.3', tip=True, funding_account_ids=[account2.id]
        )
        self.assertEqual(await account_balance(reserved_subtotals=True), {
            'total': '9.27741',
            'available': '5.97741',
            'reserved': '3.3',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.3'}
        })

        # tip claimed
        tx = await self.daemon.jsonrpc_support_abandon(txid=support1['txid'], nout=0)
        await self.confirm_tx(tx.id)
        self.assertEqual(await account_balance(reserved_subtotals=True), {
            'total': '9.277303',
            'available': '6.277303',
            'reserved': '3.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.0'}
        })

        stream2 = await self.stream_create(
            'granularity-is-cool', '0.1', account_id=account2.id, funding_account_ids=[account2.id]
        )

        # tip another claim
        await self.support_create(
            self.get_claim_id(stream2), '0.2', tip=True, funding_account_ids=[self.account.id])
        self.assertEqual(await account_balance(reserved_subtotals=True), {
            'total': '9.077157',
            'available': '6.077157',
            'reserved': '3.0',
            'reserved_subtotals': {'claims': '1.0', 'supports': '2.0', 'tips': '0.0'}
        })
