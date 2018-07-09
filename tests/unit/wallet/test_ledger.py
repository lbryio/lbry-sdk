from twisted.internet import defer
from twisted.trial import unittest
from lbrynet import conf
from lbrynet.wallet.account import Account
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


class LedgerTestCase(unittest.TestCase):

    def setUp(self):
        conf.initialize_settings(False)
        self.ledger = MainNetLedger(db=MainNetLedger.database_class(':memory:'), headers_class=MockHeaders)
        self.wallet = Wallet('Main', [Account.from_seed(
            self.ledger, u'carbon smart garage balance margin twelve chest sword toast envelope botto'
                         u'm stomach absent', u'lbryum'
        )])
        self.account = self.wallet.default_account
        return self.ledger.db.start()

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.ledger.db.stop()


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
            'insert', tx, 1, True, address, hash160, '{}:{}:'.format(tx.hex_id, 1)
        )
        balance = yield self.account.get_balance()
        self.assertEqual(balance, 100)

        tx = Transaction().add_outputs([Output.pay_claim_name_pubkey_hash(100, b'foo', b'', hash160)])
        yield self.ledger.db.save_transaction_io(
            'insert', tx, 1, True, address, hash160, '{}:{}:'.format(tx.hex_id, 1)
        )
        balance = yield self.account.get_balance()
        self.assertEqual(balance, 100)  # claim names don't count towards balance
        balance = yield self.account.get_balance(include_claims=True)
        self.assertEqual(balance, 200)

    @defer.inlineCallbacks
    def test_get_utxo(self):
        tx1 = Transaction().add_outputs([Output.pay_pubkey_hash(100, b'abc1')])
        txo = tx1.outputs[0]
        yield self.storage.add_tx_output(self.account, txo)
        balance = yield self.storage.get_balance_for_account(self.account)
        self.assertEqual(balance, 100)

        utxos = yield self.storage.get_utxos(self.account, Output)
        self.assertEqual(len(utxos), 1)

        txi = Transaction().add_inputs([Input.spend(txo)]).inputs[0]
        yield self.storage.add_tx_input(self.account, txi)
        balance = yield self.storage.get_balance_for_account(self.account)
        self.assertEqual(balance, 0)

        utxos = yield self.storage.get_utxos(self.account, Output)
        self.assertEqual(len(utxos), 0)
