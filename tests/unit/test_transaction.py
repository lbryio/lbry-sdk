import unittest
from binascii import hexlify, unhexlify
from itertools import cycle

from orchstr8.testcase import AsyncioTestCase

from torba.coin.bitcoinsegwit import MainNetLedger as ledger_class
from torba.wallet import Wallet
from torba.constants import CENT, COIN


NULL_HASH = b'\x00'*32
FEE_PER_BYTE = 50
FEE_PER_CHAR = 200000


def get_output(amount=CENT, pubkey_hash=NULL_HASH):
    return ledger_class.transaction_class() \
        .add_outputs([ledger_class.transaction_class.output_class.pay_pubkey_hash(amount, pubkey_hash)]) \
        .outputs[0]


def get_input(amount=CENT, pubkey_hash=NULL_HASH):
    return ledger_class.transaction_class.input_class.spend(get_output(amount, pubkey_hash))


def get_transaction(txo=None):
    return ledger_class.transaction_class() \
        .add_inputs([get_input()]) \
        .add_outputs([txo or ledger_class.transaction_class.output_class.pay_pubkey_hash(CENT, NULL_HASH)])


class TestSizeAndFeeEstimation(AsyncioTestCase):

    async def asyncSetUp(self):
        self.ledger = ledger_class({
            'db': ledger_class.database_class(':memory:'),
            'headers': ledger_class.headers_class(':memory:'),
        })

    def test_output_size_and_fee(self):
        txo = get_output()
        self.assertEqual(txo.size, 46)
        self.assertEqual(txo.get_fee(self.ledger), 46 * FEE_PER_BYTE)

    def test_input_size_and_fee(self):
        txi = get_input()
        self.assertEqual(txi.size, 148)
        self.assertEqual(txi.get_fee(self.ledger), 148 * FEE_PER_BYTE)

    def test_transaction_size_and_fee(self):
        tx = get_transaction()
        self.assertEqual(tx.size, 204)
        self.assertEqual(tx.base_size, tx.size - tx.inputs[0].size - tx.outputs[0].size)
        self.assertEqual(tx.get_base_fee(self.ledger), FEE_PER_BYTE * tx.base_size)


class TestAccountBalanceImpactFromTransaction(unittest.TestCase):

    def test_is_my_account_not_set(self):
        tx = get_transaction()
        with self.assertRaisesRegex(ValueError, "Cannot access net_account_balance"):
            _ = tx.net_account_balance
        tx.inputs[0].txo_ref.txo.is_my_account = True
        with self.assertRaisesRegex(ValueError, "Cannot access net_account_balance"):
            _ = tx.net_account_balance
        tx.outputs[0].is_my_account = True
        # all inputs/outputs are set now so it should work
        _ = tx.net_account_balance

    def test_paying_from_my_account_to_other_account(self):
        tx = ledger_class.transaction_class() \
            .add_inputs([get_input(300*CENT)]) \
            .add_outputs([get_output(190*CENT, NULL_HASH),
                          get_output(100*CENT, NULL_HASH)])
        tx.inputs[0].txo_ref.txo.is_my_account = True
        tx.outputs[0].is_my_account = False
        tx.outputs[1].is_my_account = True
        self.assertEqual(tx.net_account_balance, -200*CENT)

    def test_paying_from_other_account_to_my_account(self):
        tx = ledger_class.transaction_class() \
            .add_inputs([get_input(300*CENT)]) \
            .add_outputs([get_output(190*CENT, NULL_HASH),
                          get_output(100*CENT, NULL_HASH)])
        tx.inputs[0].txo_ref.txo.is_my_account = False
        tx.outputs[0].is_my_account = True
        tx.outputs[1].is_my_account = False
        self.assertEqual(tx.net_account_balance, 190*CENT)

    def test_paying_from_my_account_to_my_account(self):
        tx = ledger_class.transaction_class() \
            .add_inputs([get_input(300*CENT)]) \
            .add_outputs([get_output(190*CENT, NULL_HASH),
                          get_output(100*CENT, NULL_HASH)])
        tx.inputs[0].txo_ref.txo.is_my_account = True
        tx.outputs[0].is_my_account = True
        tx.outputs[1].is_my_account = True
        self.assertEqual(tx.net_account_balance, -10*CENT)  # lost to fee


class TestTransactionSerialization(unittest.TestCase):

    def test_genesis_transaction(self):
        raw = unhexlify(
            '01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff4d04'
            'ffff001d0104455468652054696d65732030332f4a616e2f32303039204368616e63656c6c6f72206f6e20'
            '6272696e6b206f66207365636f6e64206261696c6f757420666f722062616e6b73ffffffff0100f2052a01'
            '000000434104678afdb0fe5548271967f1a67130b7105cd6a828e03909a67962e0ea1f61deb649f6bc3f4c'
            'ef38c4f35504e51ec112de5c384df7ba0b8d578a4c702b6bf11d5fac00000000'
        )
        tx = ledger_class.transaction_class(raw)
        self.assertEqual(tx.version, 1)
        self.assertEqual(tx.locktime, 0)
        self.assertEqual(len(tx.inputs), 1)
        self.assertEqual(len(tx.outputs), 1)

        coinbase = tx.inputs[0]
        self.assertTrue(coinbase.txo_ref.is_null, NULL_HASH)
        self.assertEqual(coinbase.txo_ref.position, 0xFFFFFFFF)
        self.assertEqual(coinbase.sequence, 4294967295)
        self.assertIsNotNone(coinbase.coinbase)
        self.assertIsNone(coinbase.script)
        self.assertEqual(
            coinbase.coinbase[8:],
            b'The Times 03/Jan/2009 Chancellor on brink of second bailout for banks'
        )

        out = tx.outputs[0]
        self.assertEqual(out.amount, 5000000000)
        self.assertEqual(out.position, 0)
        self.assertTrue(out.script.is_pay_pubkey)
        self.assertFalse(out.script.is_pay_pubkey_hash)
        self.assertFalse(out.script.is_pay_script_hash)

        tx._reset()
        self.assertEqual(tx.raw, raw)

    def test_coinbase_transaction(self):
        raw = unhexlify(
            '01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff4e03'
            '1f5a070473319e592f4254432e434f4d2f4e59412ffabe6d6dcceb2a9d0444c51cabc4ee97a1a000036ca0'
            'cb48d25b94b78c8367d8b868454b0100000000000000c0309b21000008c5f8f80000ffffffff0291920b5d'
            '0000000017a914e083685a1097ce1ea9e91987ab9e94eae33d8a13870000000000000000266a24aa21a9ed'
            'e6c99265a6b9e1d36c962fda0516b35709c49dc3b8176fa7e5d5f1f6197884b400000000'
        )
        tx = ledger_class.transaction_class(raw)
        self.assertEqual(tx.version, 1)
        self.assertEqual(tx.locktime, 0)
        self.assertEqual(len(tx.inputs), 1)
        self.assertEqual(len(tx.outputs), 2)

        coinbase = tx.inputs[0]
        self.assertTrue(coinbase.txo_ref.is_null)
        self.assertEqual(coinbase.txo_ref.position, 0xFFFFFFFF)
        self.assertEqual(coinbase.sequence, 4294967295)
        self.assertIsNotNone(coinbase.coinbase)
        self.assertIsNone(coinbase.script)
        self.assertEqual(coinbase.coinbase[9:22], b'/BTC.COM/NYA/')

        out = tx.outputs[0]
        self.assertEqual(out.amount, 1561039505)
        self.assertEqual(out.position, 0)
        self.assertFalse(out.script.is_pay_pubkey)
        self.assertFalse(out.script.is_pay_pubkey_hash)
        self.assertTrue(out.script.is_pay_script_hash)
        self.assertFalse(out.script.is_return_data)

        out1 = tx.outputs[1]
        self.assertEqual(out1.amount, 0)
        self.assertEqual(out1.position, 1)
        self.assertEqual(
            hexlify(out1.script.values['data']),
            b'aa21a9ede6c99265a6b9e1d36c962fda0516b35709c49dc3b8176fa7e5d5f1f6197884b4'
        )
        self.assertTrue(out1.script.is_return_data)
        self.assertFalse(out1.script.is_pay_pubkey)
        self.assertFalse(out1.script.is_pay_pubkey_hash)
        self.assertFalse(out1.script.is_pay_script_hash)

        tx._reset()
        self.assertEqual(tx.raw, raw)


class TestTransactionSigning(AsyncioTestCase):

    async def asyncSetUp(self):
        self.ledger = ledger_class({
            'db': ledger_class.database_class(':memory:'),
            'headers': ledger_class.headers_class(':memory:'),
        })
        await self.ledger.db.open()

    async def asyncTearDown(self):
        await self.ledger.db.close()

    async def test_sign(self):
        account = self.ledger.account_class.from_dict(
            self.ledger, Wallet(), {
                "seed": "carbon smart garage balance margin twelve chest sword "
                        "toast envelope bottom stomach absent"

            }
        )

        await account.ensure_address_gap()
        address1, address2 = await account.receiving.get_addresses(limit=2)
        pubkey_hash1 = self.ledger.address_to_hash160(address1)
        pubkey_hash2 = self.ledger.address_to_hash160(address2)

        tx_class = ledger_class.transaction_class

        tx = tx_class() \
            .add_inputs([tx_class.input_class.spend(get_output(2*COIN, pubkey_hash1))]) \
            .add_outputs([tx_class.output_class.pay_pubkey_hash(int(1.9*COIN), pubkey_hash2)]) \

        await tx.sign([account])

        self.assertEqual(
            hexlify(tx.inputs[0].script.values['signature']),
            b'304402205a1df8cd5d2d2fa5934b756883d6c07e4f83e1350c740992d47a12422'
            b'226aaa202200098ac8675827aea2b0d6f0e49566143a95d523e311d342172cd99e2021e47cb01'
        )


class TransactionIOBalancing(AsyncioTestCase):

    async def asyncSetUp(self):
        self.ledger = ledger_class({
            'db': ledger_class.database_class(':memory:'),
            'headers': ledger_class.headers_class(':memory:'),
        })
        await self.ledger.db.open()
        self.account = self.ledger.account_class.from_dict(
            self.ledger, Wallet(), {
                "seed": "carbon smart garage balance margin twelve chest sword "
                        "toast envelope bottom stomach absent"
            }
        )

        addresses = await self.account.ensure_address_gap()
        self.pubkey_hash = [self.ledger.address_to_hash160(a) for a in addresses]
        self.hash_cycler = cycle(self.pubkey_hash)

    async def asyncTearDown(self):
        await self.ledger.db.close()

    def txo(self, amount, address=None):
        return get_output(int(amount*COIN), address or next(self.hash_cycler))

    def txi(self, txo):
        return ledger_class.transaction_class.input_class.spend(txo)

    def tx(self, inputs, outputs):
        return ledger_class.transaction_class.create(inputs, outputs, [self.account], self.account)

    async def create_utxos(self, amounts):
        utxos = [self.txo(amount) for amount in amounts]

        self.funding_tx = ledger_class.transaction_class(is_verified=True) \
            .add_inputs([self.txi(self.txo(sum(amounts)+0.1))]) \
            .add_outputs(utxos)

        save_tx = 'insert'
        for utxo in utxos:
            await self.ledger.db.save_transaction_io(
                save_tx, self.funding_tx,
                self.ledger.hash160_to_address(utxo.script.values['pubkey_hash']),
                utxo.script.values['pubkey_hash'], ''
            )
            save_tx = 'update'

        return utxos

    @staticmethod
    def inputs(tx):
        return [round(i.amount/COIN, 2) for i in tx.inputs]

    @staticmethod
    def outputs(tx):
        return [round(o.amount/COIN, 2) for o in tx.outputs]

    async def test_basic_use_cases(self):
        self.ledger.fee_per_byte = int(.01*CENT)

        # available UTXOs for filling missing inputs
        utxos = await self.create_utxos([
            1, 1, 3, 5, 10
        ])

        # pay 3 coins (3.02 w/ fees)
        tx = await self.tx(
            [],            # inputs
            [self.txo(3)]  # outputs
        )
        # best UTXO match is 5 (as UTXO 3 will be short 0.02 to cover fees)
        self.assertEqual(self.inputs(tx), [5])
        # a change of 1.98 is added to reach balance
        self.assertEqual(self.outputs(tx), [3, 1.98])

        await self.ledger.release_outputs(utxos)

        # pay 2.98 coins (3.00 w/ fees)
        tx = await self.tx(
            [],               # inputs
            [self.txo(2.98)]  # outputs
        )
        # best UTXO match is 3 and no change is needed
        self.assertEqual(self.inputs(tx), [3])
        self.assertEqual(self.outputs(tx), [2.98])

        await self.ledger.release_outputs(utxos)

        # supplied input and output, but input is not enough to cover output
        tx = await self.tx(
            [self.txi(self.txo(10))],  # inputs
            [self.txo(11)]             # outputs
        )
        # additional input is chosen (UTXO 3)
        self.assertEqual([10, 3], self.inputs(tx))
        # change is now needed to consume extra input
        self.assertEqual([11, 1.96], self.outputs(tx))

        await self.ledger.release_outputs(utxos)

        # liquidating a UTXO
        tx = await self.tx(
            [self.txi(self.txo(10))],  # inputs
            []                         # outputs
        )
        self.assertEqual([10], self.inputs(tx))
        # missing change added to consume the amount
        self.assertEqual([9.98], self.outputs(tx))

        await self.ledger.release_outputs(utxos)

        # liquidating at a loss, requires adding extra inputs
        tx = await self.tx(
            [self.txi(self.txo(0.01))],  # inputs
            []                           # outputs
        )
        # UTXO 1 is added to cover some of the fee
        self.assertEqual([0.01, 1], self.inputs(tx))
        # change is now needed to consume extra input
        self.assertEqual([0.97], self.outputs(tx))
