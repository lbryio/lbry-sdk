import shutil
import tempfile
from twisted.internet import defer
from twisted.trial import unittest
from lbrynet import conf
from lbrynet.database.storage import SQLiteStorage
from lbrynet.wallet.transaction import Transaction, Output, Input
from lbrynet.wallet.coin import LBC
from lbrynet.wallet.manager import LbryWalletManager
from torba.baseaccount import Account
from torba.wallet import Wallet


class LedgerTestCase(unittest.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        conf.initialize_settings(False)
        self.db_dir = tempfile.mkdtemp()
        self.storage = SQLiteStorage(self.db_dir)
        yield self.storage.setup()
        self.manager = LbryWalletManager(self.storage)
        self.ledger = self.manager.get_or_create_ledger(LBC.get_id())
        self.coin = LBC(self.ledger)
        self.wallet = Wallet('Main', [self.coin], [Account.from_seed(
            self.coin, u'carbon smart garage balance margin twelve chest sword toast envelope botto'
                       u'm stomach absent', u'lbryum'
        )])
        self.account = self.wallet.default_account
        yield self.storage.add_account(self.account)

    @defer.inlineCallbacks
    def tearDown(self):
        yield self.storage.stop()
        shutil.rmtree(self.db_dir)


class BasicAccountingTests(LedgerTestCase):

    @defer.inlineCallbacks
    def test_empty_state(self):
        balance = yield self.account.get_balance()
        self.assertEqual(balance, 0)

    @defer.inlineCallbacks
    def test_balance(self):
        tx = Transaction().add_outputs([Output.pay_pubkey_hash(100, b'abc1')])
        yield self.storage.add_tx_output(self.account, tx.outputs[0])
        balance = yield self.storage.get_balance_for_account(self.account)
        self.assertEqual(balance, 100)

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
