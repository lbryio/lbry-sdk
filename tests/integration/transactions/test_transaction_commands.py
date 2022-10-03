import asyncio
import unittest

from lbry.testcase import CommandTestCase
from lbry.wallet import Transaction

class TransactionCommandsTestCase(CommandTestCase):

    async def test_txo_dust_prevention(self):
        address = await self.daemon.jsonrpc_address_unused(self.account.id)
        tx = await self.account_send('9.9997758', address)
        # dust prevention threshold not reached, small txo created
        self.assertEqual(2, len(tx['outputs']))
        self.assertEqual(tx['outputs'][1]['amount'], '0.0001002')
        tx = await self.account_send('9.999706', address)
        # dust prevention prevented dust
        self.assertEqual(1, len(tx['outputs']))
        self.assertEqual(tx['outputs'][0]['amount'], '9.999706')

    async def test_transaction_show(self):
        # local tx
        result = await self.out(self.daemon.jsonrpc_account_send(
            '5.0', await self.daemon.jsonrpc_address_unused(self.account.id), blocking=True
        ))
        await self.confirm_tx(result['txid'])
        tx = await self.daemon.jsonrpc_transaction_show(result['txid'])
        self.assertEqual(tx.id, result['txid'])

        # someone's tx
        change_address = await self.blockchain.get_raw_change_address()
        sendtxid = await self.blockchain.send_to_address(change_address, 10)
        # After a few tries, Hub should have the transaction (in mempool).
        for i in range(5):
            tx = await self.daemon.jsonrpc_transaction_show(sendtxid)
            # Retry if Hub is not aware of the transaction.
            if isinstance(tx, dict):
                # Fields: 'success', 'code', 'message'
                self.assertFalse(tx['success'], tx)
                self.assertEqual(tx['code'], 404, tx)
                self.assertEqual(tx['message'], "transaction not found", tx)
                await asyncio.sleep(0.1)
                continue
            break
        # verify transaction show (in mempool)
        self.assertTrue(isinstance(tx, Transaction), str(tx))
        # Fields: 'txid', 'raw', 'height', 'position', 'is_verified', and more.
        self.assertEqual(tx.id, sendtxid, vars(tx))
        self.assertEqual(tx.height, -1, vars(tx))
        self.assertEqual(tx.is_verified, False, vars(tx))

        # transaction is confirmed and leaves mempool
        await self.generate(1)

        # verify transaction show
        tx = await self.daemon.jsonrpc_transaction_show(sendtxid)
        self.assertTrue(isinstance(tx, Transaction), str(tx))
        self.assertEqual(tx.id, sendtxid, vars(tx))
        self.assertEqual(tx.height, self.ledger.headers.height, vars(tx))
        self.assertEqual(tx.is_verified, True, vars(tx))

        # inexistent
        result = await self.daemon.jsonrpc_transaction_show('0'*64)
        self.assertTrue(isinstance(result, dict), result)
        # Fields: 'success', 'code', 'message'
        self.assertFalse(result['success'], result)
        self.assertEqual(result['code'], 404, result)
        self.assertEqual(result['message'], "transaction not found", result)

    async def test_utxo_release(self):
        await self.send_to_address_and_wait(
            await self.account.receiving.get_or_create_usable_address(), 1, 1
        )
        await self.assertBalance(self.account, '11.0')
        await self.ledger.reserve_outputs(await self.account.get_utxos())
        await self.assertBalance(self.account, '0.0')
        await self.daemon.jsonrpc_utxo_release()
        await self.assertBalance(self.account, '11.0')


class TestSegwit(CommandTestCase):

    @unittest.SkipTest
    async def test_segwit(self):
        p2sh_address1 = await self.blockchain.get_new_address(self.blockchain.P2SH_SEGWIT_ADDRESS)
        p2sh_address2 = await self.blockchain.get_new_address(self.blockchain.P2SH_SEGWIT_ADDRESS)
        p2sh_address3 = await self.blockchain.get_new_address(self.blockchain.P2SH_SEGWIT_ADDRESS)
        bech32_address1 = await self.blockchain.get_new_address(self.blockchain.BECH32_ADDRESS)
        bech32_address2 = await self.blockchain.get_new_address(self.blockchain.BECH32_ADDRESS)
        bech32_address3 = await self.blockchain.get_new_address(self.blockchain.BECH32_ADDRESS)

        # fund specific addresses for later use
        p2sh_txid1 = await self.blockchain.send_to_address(p2sh_address1, '1.0')
        p2sh_txid2 = await self.blockchain.send_to_address(p2sh_address2, '1.0')
        bech32_txid1 = await self.blockchain.send_to_address(bech32_address1, '1.0')
        bech32_txid2 = await self.blockchain.send_to_address(bech32_address2, '1.0')
        await self.generate(1)

        # P2SH & BECH32 can pay to P2SH address
        tx = await self.blockchain.create_raw_transaction([
                {"txid": p2sh_txid1, "vout": 0},
                {"txid": bech32_txid1, "vout": 0},
            ], {p2sh_address3: 1.9}
        )
        tx = await self.blockchain.sign_raw_transaction_with_wallet(tx)
        p2sh_txid3 = await self.blockchain.send_raw_transaction(tx)

        await self.generate(1)

        # P2SH & BECH32 can pay to BECH32 address
        tx = await self.blockchain.create_raw_transaction([
            {"txid": p2sh_txid2, "vout": 0},
            {"txid": bech32_txid2, "vout": 0},
        ], {bech32_address3: 1.9}
        )
        tx = await self.blockchain.sign_raw_transaction_with_wallet(tx)
        bech32_txid3 = await self.blockchain.send_raw_transaction(tx)

        await self.generate(1)

        # P2SH & BECH32 can pay lbry wallet P2PKH
        address = (await self.account.receiving.get_addresses(limit=1, only_usable=True))[0]
        tx = await self.blockchain.create_raw_transaction([
                {"txid": p2sh_txid3, "vout": 0},
                {"txid": bech32_txid3, "vout": 0},
            ], {address: 3.5}
        )
        tx = await self.blockchain.sign_raw_transaction_with_wallet(tx)
        txid = await self.blockchain.send_raw_transaction(tx)
        await self.generate_and_wait(1, [txid])
        await self.assertBalance(self.account, '13.5')
