import os
import unittest
import tempfile
import shutil
from binascii import hexlify, unhexlify
from itertools import cycle

from lbry.testcase import AsyncioTestCase
from lbry.wallet.constants import CENT, COIN, NULL_HASH32
from lbry.wallet import Wallet, Account, Ledger, Database, Headers, Transaction, Output, Input


NULL_HASH = b'\x00'*32
FEE_PER_BYTE = 50
FEE_PER_CHAR = 200000


def get_output(amount=CENT, pubkey_hash=NULL_HASH32, height=-2):
    return Transaction(height=height) \
        .add_outputs([Output.pay_pubkey_hash(amount, pubkey_hash)]) \
        .outputs[0]


def get_input(amount=CENT, pubkey_hash=NULL_HASH):
    return Input.spend(get_output(amount, pubkey_hash))


def get_transaction(txo=None):
    return Transaction() \
        .add_inputs([get_input()]) \
        .add_outputs([txo or Output.pay_pubkey_hash(CENT, NULL_HASH32)])


def get_claim_transaction(claim_name, claim=b''):
    return get_transaction(
        Output.pay_claim_name_pubkey_hash(CENT, claim_name, claim, NULL_HASH32)
    )


class TestSizeAndFeeEstimation(AsyncioTestCase):

    async def asyncSetUp(self):
        self.ledger = Ledger({
            'db': Database(':memory:'),
            'headers': Headers(':memory:')
        })
        await self.ledger.db.open()

    async def asyncTearDown(self):
        await self.ledger.db.close()

    def test_output_size_and_fee(self):
        txo = get_output()
        self.assertEqual(txo.size, 46)
        self.assertEqual(txo.get_fee(self.ledger), 46 * FEE_PER_BYTE)
        claim_name = 'verylongname'
        tx = get_claim_transaction(claim_name, b'0'*4000)
        base_size = tx.size - tx.inputs[0].size - tx.outputs[0].size
        txo = tx.outputs[0]
        self.assertEqual(tx.size, 4225)
        self.assertEqual(tx.base_size, base_size)
        self.assertEqual(txo.size, 4067)
        self.assertEqual(txo.get_fee(self.ledger), len(claim_name) * FEE_PER_CHAR)
        # fee based on total bytes is the larger fee
        claim_name = 'a'
        tx = get_claim_transaction(claim_name, b'0'*4000)
        base_size = tx.size - tx.inputs[0].size - tx.outputs[0].size
        txo = tx.outputs[0]
        self.assertEqual(tx.size, 4214)
        self.assertEqual(tx.base_size, base_size)
        self.assertEqual(txo.size, 4056)
        self.assertEqual(txo.get_fee(self.ledger), txo.size * FEE_PER_BYTE)

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

    def test_is_my_output_not_set(self):
        tx = get_transaction()
        with self.assertRaisesRegex(ValueError, "Cannot access net_account_balance"):
            _ = tx.net_account_balance
        tx.inputs[0].txo_ref.txo.is_my_output = True
        with self.assertRaisesRegex(ValueError, "Cannot access net_account_balance"):
            _ = tx.net_account_balance
        tx.outputs[0].is_my_output = True
        # all inputs/outputs are set now so it should work
        _ = tx.net_account_balance

    def test_paying_from_my_account_to_other_account(self):
        tx = Transaction() \
            .add_inputs([get_input(300*CENT)]) \
            .add_outputs([get_output(190*CENT, NULL_HASH),
                          get_output(100*CENT, NULL_HASH)])
        tx.inputs[0].txo_ref.txo.is_my_output = True
        tx.outputs[0].is_my_output = False
        tx.outputs[1].is_my_output = True
        self.assertEqual(tx.net_account_balance, -200*CENT)

    def test_paying_from_other_account_to_my_account(self):
        tx = Transaction() \
            .add_inputs([get_input(300*CENT)]) \
            .add_outputs([get_output(190*CENT, NULL_HASH),
                          get_output(100*CENT, NULL_HASH)])
        tx.inputs[0].txo_ref.txo.is_my_output = False
        tx.outputs[0].is_my_output = True
        tx.outputs[1].is_my_output = False
        self.assertEqual(tx.net_account_balance, 190*CENT)

    def test_paying_from_my_account_to_my_account(self):
        tx = Transaction() \
            .add_inputs([get_input(300*CENT)]) \
            .add_outputs([get_output(190*CENT, NULL_HASH),
                          get_output(100*CENT, NULL_HASH)])
        tx.inputs[0].txo_ref.txo.is_my_output = True
        tx.outputs[0].is_my_output = True
        tx.outputs[1].is_my_output = True
        self.assertEqual(tx.net_account_balance, -10*CENT)  # lost to fee


class TestTransactionSerialization(unittest.TestCase):

    def test_genesis_transaction(self):
        raw = unhexlify(
            "01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff1f0"
            "4ffff001d010417696e736572742074696d657374616d7020737472696e67ffffffff01000004bfc91b8e"
            "001976a914345991dbf57bfb014b87006acdfafbfc5fe8292f88ac00000000"
        )
        tx = Transaction(raw)
        self.assertEqual(tx.version, 1)
        self.assertEqual(tx.locktime, 0)
        self.assertEqual(len(tx.inputs), 1)
        self.assertEqual(len(tx.outputs), 1)

        coinbase = tx.inputs[0]
        self.assertTrue(coinbase.txo_ref.is_null)
        self.assertEqual(coinbase.txo_ref.position, 0xFFFFFFFF)
        self.assertEqual(coinbase.sequence, 0xFFFFFFFF)
        self.assertIsNotNone(coinbase.coinbase)
        self.assertIsNone(coinbase.script)
        self.assertEqual(
            hexlify(coinbase.coinbase),
            b'04ffff001d010417696e736572742074696d657374616d7020737472696e67'
        )

        out = tx.outputs[0]
        self.assertEqual(out.amount, 40000000000000000)
        self.assertEqual(out.position, 0)
        self.assertTrue(out.script.is_pay_pubkey_hash)
        self.assertFalse(out.script.is_pay_script_hash)
        self.assertFalse(out.script.is_claim_involved)

        tx._reset()
        self.assertEqual(tx.raw, raw)

    def test_coinbase_transaction(self):
        raw = unhexlify(
            "01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff200"
            "34d520504f89ac55a086032d217bf0700000d2f6e6f64655374726174756d2f0000000001a03489850800"
            "00001976a914cfab870d6deea54ca94a41912a75484649e52f2088ac00000000"
        )
        tx = Transaction(raw)
        self.assertEqual(tx.version, 1)
        self.assertEqual(tx.locktime, 0)
        self.assertEqual(len(tx.inputs), 1)
        self.assertEqual(len(tx.outputs), 1)

        coinbase = tx.inputs[0]
        self.assertTrue(coinbase.txo_ref.is_null)
        self.assertEqual(coinbase.txo_ref.position, 0xFFFFFFFF)
        self.assertEqual(coinbase.sequence, 0)
        self.assertIsNotNone(coinbase.coinbase)
        self.assertIsNone(coinbase.script)
        self.assertEqual(
            hexlify(coinbase.coinbase),
            b'034d520504f89ac55a086032d217bf0700000d2f6e6f64655374726174756d2f'
        )

        out = tx.outputs[0]
        self.assertEqual(out.amount, 36600100000)
        self.assertEqual(out.position, 0)
        self.assertTrue(out.script.is_pay_pubkey_hash)
        self.assertFalse(out.script.is_pay_script_hash)
        self.assertFalse(out.script.is_claim_involved)

        tx._reset()
        self.assertEqual(tx.raw, raw)

    def test_claim_transaction(self):
        raw = unhexlify(
            "01000000012433e1b327603843b083344dbae5306ff7927f87ebbc5ae9eb50856c5b53fd1d000000006a4"
            "7304402201a91e1023d11c383a11e26bf8f9034087b15d8ada78fa565e0610455ffc8505e0220038a63a6"
            "ecb399723d4f1f78a20ddec0a78bf8fb6c75e63e166ef780f3944fbf0121021810150a2e4b088ec51b20c"
            "be1b335962b634545860733367824d5dc3eda767dffffffff028096980000000000fdff00b50463617473"
            "4cdc080110011a7808011230080410011a084d616361726f6e6922002a003214416c6c207269676874732"
            "072657365727665642e38004a0052005a001a42080110011a30add80aaf02559ba09853636a0658c42b72"
            "7cb5bb4ba8acedb4b7fe656065a47a31878dbf9912135ddb9e13806cc1479d220a696d6167652f6a70656"
            "72a5c080110031a404180cc0fa4d3839ee29cca866baed25fafb43fca1eb3b608ee889d351d3573d042c7"
            "b83e2e643db0d8e062a04e6e9ae6b90540a2f95fe28638d0f18af4361a1c2214f73de93f4299fb32c32f9"
            "49e02198a8e91101abd6d7576a914be16e4b0f9bd8f6d47d02b3a887049c36d3b84cb88ac0cd2520b0000"
            "00001976a914f521178feb733a719964e1da4a9efb09dcc39cfa88ac00000000"
        )
        tx = Transaction(raw)
        self.assertEqual(tx.id, '666c3d15de1d6949a4fe717126c368e274b36957dce29fd401138c1e87e92a62')
        self.assertEqual(tx.version, 1)
        self.assertEqual(tx.locktime, 0)
        self.assertEqual(len(tx.inputs), 1)
        self.assertEqual(len(tx.outputs), 2)

        txin = tx.inputs[0]
        self.assertEqual(
            txin.txo_ref.id,
            '1dfd535b6c8550ebe95abceb877f92f76f30e5ba4d3483b043386027b3e13324:0'
        )
        self.assertEqual(txin.txo_ref.position, 0)
        self.assertEqual(txin.sequence, 0xFFFFFFFF)
        self.assertIsNone(txin.coinbase)
        self.assertEqual(txin.script.template.name, 'pubkey_hash')
        self.assertEqual(
            hexlify(txin.script.values['pubkey']),
            b'021810150a2e4b088ec51b20cbe1b335962b634545860733367824d5dc3eda767d'
        )
        self.assertEqual(
            hexlify(txin.script.values['signature']),
            b'304402201a91e1023d11c383a11e26bf8f9034087b15d8ada78fa565e0610455ffc8505e0220038a63a6'
            b'ecb399723d4f1f78a20ddec0a78bf8fb6c75e63e166ef780f3944fbf01'
        )

        # Claim
        out0 = tx.outputs[0]
        self.assertEqual(out0.amount, 10000000)
        self.assertEqual(out0.position, 0)
        self.assertTrue(out0.script.is_pay_pubkey_hash)
        self.assertTrue(out0.script.is_claim_name)
        self.assertTrue(out0.script.is_claim_involved)
        self.assertEqual(out0.script.values['claim_name'], b'cats')
        self.assertEqual(
            hexlify(out0.script.values['pubkey_hash']),
            b'be16e4b0f9bd8f6d47d02b3a887049c36d3b84cb'
        )

        # Change
        out1 = tx.outputs[1]
        self.assertEqual(out1.amount, 189977100)
        self.assertEqual(out1.position, 1)
        self.assertTrue(out1.script.is_pay_pubkey_hash)
        self.assertFalse(out1.script.is_claim_involved)
        self.assertEqual(
            hexlify(out1.script.values['pubkey_hash']),
            b'f521178feb733a719964e1da4a9efb09dcc39cfa'
        )

        tx._reset()
        self.assertEqual(tx.raw, raw)

    def test_redeem_scripthash_transaction(self):
        raw = unhexlify(
            "0200000001409223c2405238fdc516d4f2e8aa57637ce52d3b1ac42b26f1accdcda9697e79010000008a4"
            "730440220033d5286f161da717d9d1bc3c2bc28da7636b38fc0c6aefb1e0864212f05282c02205df3ce13"
            "5e79c76d44489212f77ad4e3a838562e601e6377704fa6206a6ae44f012102261773e7eebe9da80a5653d"
            "865cc600362f8e7b2b598661139dd902b5b01ea101f03aaf30ab17576a914a3328f18ac1892a6667f713d"
            "7020ff3437d973c888acfeffffff0180ed3e17000000001976a914353352b7ce1e3c9c05ffcd6ae97609d"
            "e2999744488accdf50a00"
        )
        tx = Transaction(raw)
        self.assertEqual(tx.id, 'e466881128889d1cc4110627753051c22e72a81d11229a1a1337da06940bebcf')
        self.assertEqual(tx.version, 2)
        self.assertEqual(tx.locktime, 718285,)
        self.assertEqual(len(tx.inputs), 1)
        self.assertEqual(len(tx.outputs), 1)

        txin = tx.inputs[0]
        self.assertEqual(
            txin.txo_ref.id,
            '797e69a9cdcdacf1262bc41a3b2de57c6357aae8f2d416c5fd385240c2239240:1'
        )
        self.assertEqual(txin.txo_ref.position, 1)
        self.assertEqual(txin.sequence, 4294967294)
        self.assertIsNone(txin.coinbase)
        self.assertEqual(txin.script.template.name, 'script_hash+timelock')
        self.assertEqual(
            hexlify(txin.script.values['signature']),
            b'30440220033d5286f161da717d9d1bc3c2bc28da7636b38fc0c6aefb1e0864212f'
            b'05282c02205df3ce135e79c76d44489212f77ad4e3a838562e601e6377704fa620'
            b'6a6ae44f01'
        )
        self.assertEqual(
            hexlify(txin.script.values['pubkey']),
            b'02261773e7eebe9da80a5653d865cc600362f8e7b2b598661139dd902b5b01ea10'
        )
        script = txin.script.values['script']
        self.assertEqual(script.template.name, 'timelock')
        self.assertEqual(script.values['height'], 717738)
        self.assertEqual(hexlify(script.values['pubkey_hash']), b'a3328f18ac1892a6667f713d7020ff3437d973c8')


class TestTransactionSigning(AsyncioTestCase):

    async def asyncSetUp(self):
        self.ledger = Ledger({
            'db': Database(':memory:'),
            'headers': Headers(':memory:')
        })
        await self.ledger.db.open()

    async def asyncTearDown(self):
        await self.ledger.db.close()

    async def test_sign(self):
        account = Account.from_dict(
            self.ledger, Wallet(), {
                "seed":
                    "carbon smart garage balance margin twelve chest sword toas"
                    "t envelope bottom stomach absent"
            }
        )

        await account.ensure_address_gap()
        address1, address2 = await account.receiving.get_addresses(limit=2)
        pubkey_hash1 = self.ledger.address_to_hash160(address1)
        pubkey_hash2 = self.ledger.address_to_hash160(address2)

        tx = Transaction() \
            .add_inputs([Input.spend(get_output(int(2*COIN), pubkey_hash1))]) \
            .add_outputs([Output.pay_pubkey_hash(int(1.9*COIN), pubkey_hash2)])

        await tx.sign([account])

        self.assertEqual(
            hexlify(tx.inputs[0].script.values['signature']),
            b'304402200dafa26ad7cf38c5a971c8a25ce7d85a076235f146126762296b1223c42ae21e022020ef9eeb8'
            b'398327891008c5c0be4357683f12cb22346691ff23914f457bf679601'
        )


class TransactionIOBalancing(AsyncioTestCase):

    async def asyncSetUp(self):
        wallet_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, wallet_dir)
        self.ledger = Ledger({
            'db': Database(os.path.join(wallet_dir, 'blockchain.db')),
            'headers': Headers(':memory:'),
        })
        await self.ledger.db.open()
        self.account = Account.from_dict(
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
        return Input.spend(txo)

    def tx(self, inputs, outputs):
        return Transaction.create(inputs, outputs, [self.account], self.account)

    async def create_utxos(self, amounts):
        utxos = [self.txo(amount) for amount in amounts]

        self.funding_tx = Transaction(is_verified=True) \
            .add_inputs([self.txi(self.txo(sum(amounts)+0.1))]) \
            .add_outputs(utxos)

        await self.ledger.db.insert_transaction(self.funding_tx)

        for utxo in utxos:
            await self.ledger.db.save_transaction_io(
                self.funding_tx,
                self.ledger.hash160_to_address(utxo.script.values['pubkey_hash']),
                utxo.script.values['pubkey_hash'], ''
            )

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
        self.assertListEqual(self.inputs(tx), [5])
        # a change of 1.98 is added to reach balance
        self.assertListEqual(self.outputs(tx), [3, 1.98])

        await self.ledger.release_outputs(utxos)

        # pay 2.98 coins (3.00 w/ fees)
        tx = await self.tx(
            [],               # inputs
            [self.txo(2.98)]  # outputs
        )
        # best UTXO match is 3 and no change is needed
        self.assertListEqual(self.inputs(tx), [3])
        self.assertListEqual(self.outputs(tx), [2.98])

        await self.ledger.release_outputs(utxos)

        # supplied input and output, but input is not enough to cover output
        tx = await self.tx(
            [self.txi(self.txo(10))],  # inputs
            [self.txo(11)]             # outputs
        )
        # additional input is chosen (UTXO 3)
        self.assertListEqual([10, 3], self.inputs(tx))
        # change is now needed to consume extra input
        self.assertListEqual([11, 1.96], self.outputs(tx))

        await self.ledger.release_outputs(utxos)

        # liquidating a UTXO
        tx = await self.tx(
            [self.txi(self.txo(10))],  # inputs
            []                         # outputs
        )
        self.assertListEqual([10], self.inputs(tx))
        # missing change added to consume the amount
        self.assertListEqual([9.98], self.outputs(tx))

        await self.ledger.release_outputs(utxos)

        # liquidating at a loss, requires adding extra inputs
        tx = await self.tx(
            [self.txi(self.txo(0.01))],  # inputs
            []                           # outputs
        )
        # UTXO 1 is added to cover some of the fee
        self.assertListEqual([0.01, 1], self.inputs(tx))
        # change is now needed to consume extra input
        self.assertListEqual([0.97], self.outputs(tx))

    async def test_basic_use_cases_sqlite(self):
        self.ledger.coin_selection_strategy = 'sqlite'
        self.ledger.fee_per_byte = int(0.01*CENT)

        # available UTXOs for filling missing inputs
        utxos = await self.create_utxos([
            1, 1, 3, 5, 10
        ])

        self.assertEqual(5, len(await self.ledger.get_utxos()))

        # pay 3 coins (3.07 w/ fees)
        tx = await self.tx(
            [],            # inputs
            [self.txo(3)]  # outputs
        )

        await self.ledger.db.db.run(self.ledger.db._transaction_io, tx, tx.outputs[0].get_address(self.ledger), tx.id)

        self.assertListEqual(self.inputs(tx), [1.0, 1.0, 3.0])
        # a change of 1.95 is added to reach balance
        self.assertListEqual(self.outputs(tx), [3, 1.95])
        # utxos: 1.95, 3, 5, 10
        self.assertEqual(2, len(await self.ledger.get_utxos()))
        # pay 4.946 coins (5.00 w/ fees)
        tx = await self.tx(
            [],                # inputs
            [self.txo(4.946)]  # outputs
        )
        self.assertEqual(1, len(await self.ledger.get_utxos()))

        self.assertListEqual(self.inputs(tx), [5.0])
        self.assertEqual(2, len(tx.outputs))
        self.assertEqual(494600000, tx.outputs[0].amount)

        # utxos: 3, 1.95, 4.946, 10
        await self.ledger.release_outputs(utxos)

        # supplied input and output, but input is not enough to cover output
        tx = await self.tx(
            [self.txi(self.txo(10))],  # inputs
            [self.txo(11)]             # outputs
        )
        # additional input is chosen (UTXO 1)
        self.assertListEqual([10, 1.0, 1.0], self.inputs(tx))
        # change is now needed to consume extra input
        self.assertListEqual([11, 0.95], self.outputs(tx))
        await self.ledger.release_outputs(utxos)
        # liquidating a UTXO
        tx = await self.tx(
            [self.txi(self.txo(10))],  # inputs
            []                         # outputs
        )
        self.assertListEqual([10], self.inputs(tx))
        # missing change added to consume the amount
        self.assertListEqual([9.98], self.outputs(tx))
        await self.ledger.release_outputs(utxos)
        # liquidating at a loss, requires adding extra inputs
        tx = await self.tx(
            [self.txi(self.txo(0.01))],  # inputs
            []                           # outputs
        )
        # UTXO 1 is added to cover some of the fee
        self.assertListEqual([0.01, 1], self.inputs(tx))
        # change is now needed to consume extra input
        self.assertListEqual([0.97], self.outputs(tx))
