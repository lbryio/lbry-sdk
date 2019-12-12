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


class TestSegwit(CommandTestCase):

    VERBOSITY = 10

    async def test_segwit(self):
        p2sh_address = await self.blockchain.get_new_address(self.blockchain.P2SH_SEGWIT_ADDRESS)
        bech32_address = await self.blockchain.get_new_address(self.blockchain.BECH32_ADDRESS)
        p2sh_tx1 = await self.blockchain.send_to_address(p2sh_address, '1.0')
        p2sh_tx2 = await self.blockchain.send_to_address(p2sh_address, '1.0')
        bech32_tx1 = await self.blockchain.send_to_address(bech32_address, '1.0')
        bech32_tx2 = await self.blockchain.send_to_address(bech32_address, '1.0')

        await self.generate(1)

        address = (await self.account.receiving.get_addresses(limit=1, only_usable=True))[0]

        tx = await self.blockchain.create_raw_transaction([
                {"txid": p2sh_tx1, "vout": 0},
                {"txid": p2sh_tx2, "vout": 0},
                {"txid": bech32_tx1, "vout": 0},
                {"txid": bech32_tx2, "vout": 0},
            ], [{address: '3.5'}]
        )

        tx = await self.blockchain.sign_raw_transaction_with_wallet(tx)
        txid = await self.blockchain.send_raw_transaction(tx)
        await self.on_transaction_id(txid)

        await self.assertBalance(self.account, '13.5')
