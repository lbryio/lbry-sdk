from twisted.internet import defer
from twisted.trial import unittest
from lbrynet.wallet.account import Account
from lbrynet.wallet.transaction import Transaction, Output, Input
from lbrynet.wallet.ledger import MainNetLedger
from torba.wallet import Wallet


class LedgerTestCase(unittest.TestCase):

    def setUp(self):
        super().setUp()
        self.ledger = MainNetLedger({
            'db': MainNetLedger.database_class(':memory:'),
            'headers': MainNetLedger.headers_class(':memory:')
        })
        self.account = Account.generate(self.ledger, Wallet(), "lbryum")
        return self.ledger.db.open()

    def tearDown(self):
        super().tearDown()
        return self.ledger.db.close()


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

        tx = Transaction().add_outputs([Output.pay_claim_name_pubkey_hash(100, 'foo', b'', hash160)])
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

