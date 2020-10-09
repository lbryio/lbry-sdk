import os
import shutil
import tempfile

from lbry import Config, Ledger, Database, WalletManager, Wallet, Account
from lbry.testcase import AsyncioTestCase
from lbry.wallet.manager import FileWallet, DatabaseWallet


class DBBasedWalletManagerTestCase(AsyncioTestCase):

    async def asyncSetUp(self):
        self.ledger = Ledger(Config.with_null_dir().set(
            db_url="sqlite:///:memory:",
            wallet_storage="database"
        ))
        self.db = Database(self.ledger)
        await self.db.open()
        self.addCleanup(self.db.close)


class TestDatabaseWalletManager(DBBasedWalletManagerTestCase):

    async def test_initialize_with_default_wallet_account_progression(self):
        wm = WalletManager(self.db)
        self.assertIsInstance(wm.storage, DatabaseWallet)
        storage: DatabaseWallet = wm.storage
        await storage.prepare()

        # first, no defaults
        self.ledger.conf.create_default_wallet = False
        self.ledger.conf.create_default_account = False
        await wm.initialize()
        self.assertIsNone(wm.default)

        # then, yes to default wallet but no to default account
        self.ledger.conf.create_default_wallet = True
        self.ledger.conf.create_default_account = False
        await wm.initialize()
        self.assertIsInstance(wm.default, Wallet)
        self.assertTrue(await storage.exists(wm.default.id))
        self.assertIsNone(wm.default.accounts.default)

        # finally, yes to all the things
        self.ledger.conf.create_default_wallet = True
        self.ledger.conf.create_default_account = True
        await wm.initialize()
        self.assertIsInstance(wm.default, Wallet)
        self.assertIsInstance(wm.default.accounts.default, Account)

    async def test_load_with_create_default_everything_upfront(self):
        wm = WalletManager(self.db)
        await wm.storage.prepare()
        self.ledger.conf.create_default_wallet = True
        self.ledger.conf.create_default_account = True
        await wm.initialize()
        self.assertIsInstance(wm.default, Wallet)
        self.assertIsInstance(wm.default.accounts.default, Account)
        self.assertTrue(await wm.storage.exists(wm.default.id))

    async def test_load_errors(self):
        _wm = WalletManager(self.db)
        await _wm.storage.prepare()
        await _wm.create('bar', '')
        await _wm.create('foo', '')

        wm = WalletManager(self.db)
        self.ledger.conf.wallets = ['bar', 'foo', 'foo']
        with self.assertLogs(level='WARN') as cm:
            await wm.initialize()
            self.assertEqual(
                cm.output, [
                    'WARNING:lbry.wallet.manager:Ignoring duplicate wallet_id in config: foo',
                ]
            )
        self.assertEqual({'bar', 'foo'}, set(wm.wallets))

    async def test_creating_and_accessing_wallets(self):
        wm = WalletManager(self.db)
        await wm.storage.prepare()
        await wm.initialize()
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


class TestFileBasedWalletManager(AsyncioTestCase):

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.temp_dir)
        self.ledger = Ledger(Config(
            data_dir=self.temp_dir,
            db_url="sqlite:///:memory:"
        ))
        self.ledger.conf.set_default_paths()
        self.db = Database(self.ledger)
        await self.db.open()
        self.addCleanup(self.db.close)

    async def test_ensure_path_exists(self):
        wm = WalletManager(self.db)
        self.assertIsInstance(wm.storage, FileWallet)
        storage: FileWallet = wm.storage
        self.assertFalse(os.path.exists(storage.wallet_dir))
        await storage.prepare()
        self.assertTrue(os.path.exists(storage.wallet_dir))

    async def test_initialize_with_default_wallet_account_progression(self):
        wm = WalletManager(self.db)
        storage: FileWallet = wm.storage
        await storage.prepare()

        # first, no defaults
        self.ledger.conf.create_default_wallet = False
        self.ledger.conf.create_default_account = False
        await wm.initialize()
        self.assertIsNone(wm.default)

        # then, yes to default wallet but no to default account
        self.ledger.conf.create_default_wallet = True
        self.ledger.conf.create_default_account = False
        await wm.initialize()
        self.assertIsInstance(wm.default, Wallet)
        self.assertTrue(os.path.exists(storage.get_wallet_path(wm.default.id)))
        self.assertIsNone(wm.default.accounts.default)

        # finally, yes to all the things
        self.ledger.conf.create_default_wallet = True
        self.ledger.conf.create_default_account = True
        await wm.initialize()
        self.assertIsInstance(wm.default, Wallet)
        self.assertIsInstance(wm.default.accounts.default, Account)

    async def test_load_with_create_default_everything_upfront(self):
        wm = WalletManager(self.db)
        await wm.storage.prepare()
        self.ledger.conf.create_default_wallet = True
        self.ledger.conf.create_default_account = True
        await wm.initialize()
        self.assertIsInstance(wm.default, Wallet)
        self.assertIsInstance(wm.default.accounts.default, Account)
        self.assertTrue(os.path.exists(wm.storage.get_wallet_path(wm.default.id)))

    async def test_load_errors(self):
        _wm = WalletManager(self.db)
        await _wm.storage.prepare()
        await _wm.create('bar', '')
        await _wm.create('foo', '')

        wm = WalletManager(self.db)
        self.ledger.conf.wallets = ['bar', 'foo', 'foo']
        with self.assertLogs(level='WARN') as cm:
            await wm.initialize()
            self.assertEqual(
                cm.output, [
                    'WARNING:lbry.wallet.manager:Ignoring duplicate wallet_id in config: foo',
                ]
            )
        self.assertEqual({'bar', 'foo'}, set(wm.wallets))

    async def test_creating_and_accessing_wallets(self):
        wm = WalletManager(self.db)
        await wm.storage.prepare()
        await wm.initialize()
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

    async def test_read_write(self):
        manager = WalletManager(self.db)
        await manager.storage.prepare()

        with tempfile.NamedTemporaryFile(suffix='.json') as wallet_file:
            wallet_file.write(b'{"version": 1}')
            wallet_file.seek(0)

            # create and write wallet to a file
            wallet = await manager.load(wallet_file.name)
            account = await wallet.accounts.generate()
            await manager.storage.save(wallet)

            # read wallet from file
            wallet = await manager.load(wallet_file.name)

            self.assertEqual(account.public_key.address, wallet.accounts.default.public_key.address)
