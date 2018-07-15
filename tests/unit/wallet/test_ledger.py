from twisted.internet import defer
from twisted.trial import unittest
from lbrynet import conf
from lbrynet.wallet.account import Account
from lbrynet.wallet.database import WalletDatabase
from lbrynet.wallet.transaction import Transaction, Output, Input
from lbrynet.wallet.ledger import MainNetLedger
from torba.wallet import Wallet


class MockHeaders:
    def __init__(self, ledger):
        self.ledger = ledger
        self.height = 1

    def __len__(self):
        return self.height

    def __getitem__(self, height):
        return {'merkle_root': 'abcd04'}


class MainNetTestLedger(MainNetLedger):
    headers_class = MockHeaders
    network_name = 'unittest'

    def __init__(self):
        super(MainNetLedger, self).__init__({
            'db': WalletDatabase(':memory:')
        })


class LedgerTestCase(unittest.TestCase):

    def setUp(self):
        conf.initialize_settings(False)
        self.ledger = MainNetTestLedger()
        self.account = Account.generate(self.ledger, u"lbryum")
        return self.ledger.db.start()

    def tearDown(self):
        return self.ledger.db.stop()


class BasicAccountingTests(LedgerTestCase):

    @defer.inlineCallbacks
    def test_empty_state(self):
        balance = yield self.account.get_balance()
        self.assertEqual(balance, 0)

    @defer.inlineCallbacks
    def test_balance(self):
        address = yield self.account.receiving.get_or_create_usable_address()
        hash160 = self.ledger.address_to_hash160(address)

        tx = Transaction().add_outputs([Output.pay_pubkey_hash(100, hash160)])
        yield self.ledger.db.save_transaction_io(
            'insert', tx, 1, True, address, hash160, '{}:{}:'.format(tx.id, 1)
        )
        balance = yield self.account.get_balance(0)
        self.assertEqual(balance, 100)

        tx = Transaction().add_outputs([Output.pay_claim_name_pubkey_hash(100, b'foo', b'', hash160)])
        yield self.ledger.db.save_transaction_io(
            'insert', tx, 1, True, address, hash160, '{}:{}:'.format(tx.id, 1)
        )
        balance = yield self.account.get_balance(0)
        self.assertEqual(balance, 100)  # claim names don't count towards balance
        balance = yield self.account.get_balance(0, include_claims=True)
        self.assertEqual(balance, 200)

    @defer.inlineCallbacks
    def test_get_utxo(self):
        address = yield self.account.receiving.get_or_create_usable_address()
        hash160 = self.ledger.address_to_hash160(address)

        tx = Transaction().add_outputs([Output.pay_pubkey_hash(100, hash160)])
        yield self.ledger.db.save_transaction_io(
            'insert', tx, 1, True, address, hash160, '{}:{}:'.format(tx.id, 1)
        )

        utxos = yield self.account.get_unspent_outputs()
        self.assertEqual(len(utxos), 1)

        tx = Transaction().add_inputs([Input.spend(utxos[0])])
        yield self.ledger.db.save_transaction_io(
            'insert', tx, 1, True, address, hash160, '{}:{}:'.format(tx.id, 1)
        )
        balance = yield self.account.get_balance(0, include_claims=True)
        self.assertEqual(balance, 0)

        utxos = yield self.account.get_unspent_outputs()
        self.assertEqual(len(utxos), 0)

