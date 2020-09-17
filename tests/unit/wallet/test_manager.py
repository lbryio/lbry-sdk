import os
import shutil
import tempfile

from lbry import Config, Ledger, Database, WalletManager, Wallet, Account
from lbry.testcase import AsyncioTestCase


class TestWalletManager(AsyncioTestCase):

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp_dir)
        self.ledger = Ledger(Config.with_same_dir(self.temp_dir).set(
            db_url="sqlite:///:memory:"
        ))
        self.db = Database(self.ledger)

    async def test_ensure_path_exists(self):
        wm = WalletManager(self.ledger, self.db)
        self.assertFalse(os.path.exists(wm.path))
        await wm.ensure_path_exists()
        self.assertTrue(os.path.exists(wm.path))

    async def test_load_with_default_wallet_account_progression(self):
        wm = WalletManager(self.ledger, self.db)
        await wm.ensure_path_exists()

        # first, no defaults
        self.ledger.conf.create_default_wallet = False
        self.ledger.conf.create_default_account = False
        await wm.load()
        self.assertIsNone(wm.default)

        # then, yes to default wallet but no to default account
        self.ledger.conf.create_default_wallet = True
        self.ledger.conf.create_default_account = False
        await wm.load()
        self.assertIsInstance(wm.default, Wallet)
        self.assertTrue(os.path.exists(wm.default.storage.path))
        self.assertIsNone(wm.default.accounts.default)

        # finally, yes to all the things
        self.ledger.conf.create_default_wallet = True
        self.ledger.conf.create_default_account = True
        await wm.load()
        self.assertIsInstance(wm.default, Wallet)
        self.assertIsInstance(wm.default.accounts.default, Account)

    async def test_load_with_create_default_everything_upfront(self):
        wm = WalletManager(self.ledger, self.db)
        await wm.ensure_path_exists()
        self.ledger.conf.create_default_wallet = True
        self.ledger.conf.create_default_account = True
        await wm.load()
        self.assertIsInstance(wm.default, Wallet)
        self.assertIsInstance(wm.default.accounts.default, Account)
        self.assertTrue(os.path.exists(wm.default.storage.path))

    async def test_load_errors(self):
        _wm = WalletManager(self.ledger, self.db)
        await _wm.ensure_path_exists()
        await _wm.create('bar', '')
        await _wm.create('foo', '')

        wm = WalletManager(self.ledger, self.db)
        self.ledger.conf.wallets = ['bar', 'foo', 'foo']
        with self.assertLogs(level='WARN') as cm:
            await wm.load()
            self.assertEqual(
                cm.output, [
                    'WARNING:lbry.wallet.manager:Ignoring duplicate wallet_id in config: foo',
                ]
            )
        self.assertEqual({'bar', 'foo'}, set(wm.wallets))

    async def test_creating_and_accessing_wallets(self):
        wm = WalletManager(self.ledger, self.db)
        await wm.ensure_path_exists()
        await wm.load()
        default_wallet = wm.default
        self.assertEqual(default_wallet, wm['default_wallet'])
        self.assertEqual(default_wallet, wm.get_or_default(None))
        new_wallet = await wm.create('second', 'Second Wallet')
        self.assertEqual(default_wallet, wm.default)
        self.assertEqual(new_wallet, wm['second'])
        self.assertEqual(new_wallet, wm.get_or_default('second'))
        self.assertEqual(default_wallet, wm.get_or_default(None))
        with self.assertRaisesRegex(ValueError, "Couldn't find wallet: invalid"):
            _ = wm['invalid']
        with self.assertRaisesRegex(ValueError, "Couldn't find wallet: invalid"):
            wm.get_or_default('invalid')
