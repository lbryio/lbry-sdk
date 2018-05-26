from binascii import hexlify, unhexlify
from twisted.trial import unittest

from torba.account import Account
from torba.constants import CENT, COIN
from torba.wallet import Wallet

from lbrynet.wallet.coin import LBC
from lbrynet.wallet.transaction import Transaction, Output, Input
from lbrynet.wallet.manager import LbryWalletManager


NULL_HASH = '\x00'*32
FEE_PER_BYTE = 50
FEE_PER_CHAR = 200000


def get_output(amount=CENT, pubkey_hash=NULL_HASH):
    return Transaction() \
        .add_outputs([Output.pay_pubkey_hash(amount, pubkey_hash)]) \
        .outputs[0]


def get_input():
    return Input.spend(get_output())


def get_transaction(txo=None):
    return Transaction() \
        .add_inputs([get_input()]) \
        .add_outputs([txo or Output.pay_pubkey_hash(CENT, NULL_HASH)])


def get_claim_transaction(claim_name, claim=''):
    return get_transaction(
        Output.pay_claim_name_pubkey_hash(CENT, claim_name, claim, NULL_HASH)
    )


def get_wallet_and_coin():
    ledger = LbryWalletManager().get_or_create_ledger(LBC.get_id())
    coin = LBC(ledger)
    return Wallet('Main', [coin], [Account.generate(coin, u'lbryum')]), coin


class TestSizeAndFeeEstimation(unittest.TestCase):

    def setUp(self):
        self.wallet, self.coin = get_wallet_and_coin()

    def io_fee(self, io):
        return self.coin.get_input_output_fee(io)

    def test_output_size_and_fee(self):
        txo = get_output()
        self.assertEqual(txo.size, 46)
        self.assertEqual(self.io_fee(txo), 46 * FEE_PER_BYTE)

    def test_input_size_and_fee(self):
        txi = get_input()
        self.assertEqual(txi.size, 148)
        self.assertEqual(self.io_fee(txi), 148 * FEE_PER_BYTE)

    def test_transaction_size_and_fee(self):
        tx = get_transaction()
        base_size = tx.size - 1 - tx.inputs[0].size
        self.assertEqual(tx.size, 204)
        self.assertEqual(tx.base_size, base_size)
        self.assertEqual(self.coin.get_transaction_base_fee(tx), FEE_PER_BYTE * base_size)

    def test_claim_name_transaction_size_and_fee(self):
        # fee based on claim name is the larger fee
        claim_name = 'verylongname'
        tx = get_claim_transaction(claim_name, '0'*4000)
        base_size = tx.size - 1 - tx.inputs[0].size
        self.assertEqual(tx.size, 4225)
        self.assertEqual(tx.base_size, base_size)
        self.assertEqual(self.coin.get_transaction_base_fee(tx), len(claim_name) * FEE_PER_CHAR)
        # fee based on total bytes is the larger fee
        claim_name = 'a'
        tx = get_claim_transaction(claim_name, '0'*4000)
        base_size = tx.size - 1 - tx.inputs[0].size
        self.assertEqual(tx.size, 4214)
        self.assertEqual(tx.base_size, base_size)
        self.assertEqual(self.coin.get_transaction_base_fee(tx), FEE_PER_BYTE * base_size)


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
        self.assertEqual(coinbase.output_txid, NULL_HASH)
        self.assertEqual(coinbase.output_index, 0xFFFFFFFF)
        self.assertEqual(coinbase.sequence, 0xFFFFFFFF)
        self.assertTrue(coinbase.is_coinbase)
        self.assertEqual(coinbase.script, None)
        self.assertEqual(
            hexlify(coinbase.coinbase),
            b'04ffff001d010417696e736572742074696d657374616d7020737472696e67'
        )

        out = tx.outputs[0]
        self.assertEqual(out.amount, 40000000000000000)
        self.assertEqual(out.index, 0)
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
        self.assertEqual(coinbase.output_txid, NULL_HASH)
        self.assertEqual(coinbase.output_index, 0xFFFFFFFF)
        self.assertEqual(coinbase.sequence, 0)
        self.assertTrue(coinbase.is_coinbase)
        self.assertEqual(coinbase.script, None)
        self.assertEqual(
            hexlify(coinbase.coinbase),
            b'034d520504f89ac55a086032d217bf0700000d2f6e6f64655374726174756d2f'
        )

        out = tx.outputs[0]
        self.assertEqual(out.amount, 36600100000)
        self.assertEqual(out.index, 0)
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
        self.assertEqual(hexlify(tx.id), b'666c3d15de1d6949a4fe717126c368e274b36957dce29fd401138c1e87e92a62')
        self.assertEqual(tx.version, 1)
        self.assertEqual(tx.locktime, 0)
        self.assertEqual(len(tx.inputs), 1)
        self.assertEqual(len(tx.outputs), 2)

        txin = tx.inputs[0]
        self.assertEqual(
            hexlify(txin.output_txid[::-1]),
            b'1dfd535b6c8550ebe95abceb877f92f76f30e5ba4d3483b043386027b3e13324'
        )
        self.assertEqual(txin.output_index, 0)
        self.assertEqual(txin.sequence, 0xFFFFFFFF)
        self.assertFalse(txin.is_coinbase)
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
        self.assertEqual(out0.index, 0)
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
        self.assertEqual(out1.index, 1)
        self.assertTrue(out1.script.is_pay_pubkey_hash)
        self.assertFalse(out1.script.is_claim_involved)
        self.assertEqual(
            hexlify(out1.script.values['pubkey_hash']),
            b'f521178feb733a719964e1da4a9efb09dcc39cfa'
        )

        tx._reset()
        self.assertEqual(tx.raw, raw)


class TestTransactionSigning(unittest.TestCase):

    def test_sign(self):
        ledger = LbryWalletManager().get_or_create_ledger(LBC.get_id())
        coin = LBC(ledger)
        wallet = Wallet('Main', [coin], [Account.from_seed(
            coin, u'carbon smart garage balance margin twelve chest sword toast envelope bottom sto'
                  u'mach absent', u'lbryum'
        )])
        account = wallet.default_account

        address1 = account.receiving_keys.generate_next_address()
        address2 = account.receiving_keys.generate_next_address()
        pubkey_hash1 = account.coin.address_to_hash160(address1)
        pubkey_hash2 = account.coin.address_to_hash160(address2)

        tx = Transaction() \
            .add_inputs([Input.spend(get_output(2*COIN, pubkey_hash1))]) \
            .add_outputs([Output.pay_pubkey_hash(1.9*COIN, pubkey_hash2)]) \
            .sign(account)

        print(hexlify(tx.inputs[0].script.values['signature']))
        self.assertEqual(
            hexlify(tx.inputs[0].script.values['signature']),
            b'304402200dafa26ad7cf38c5a971c8a25ce7d85a076235f146126762296b1223c42ae21e022020ef9eeb8'
            b'398327891008c5c0be4357683f12cb22346691ff23914f457bf679601'
        )
