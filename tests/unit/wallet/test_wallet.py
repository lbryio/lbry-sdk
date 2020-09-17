import tempfile
from binascii import hexlify
from unittest import TestCase, mock

from lbry import Config, Database, Ledger, Account, Wallet, WalletManager
from lbry.testcase import AsyncioTestCase
from lbry.wallet.storage import WalletStorage
from lbry.wallet.preferences import TimestampedPreferences


class WalletTestCase(AsyncioTestCase):

    async def asyncSetUp(self):
        self.ledger = Ledger(Config.with_null_dir())
        self.db = Database(self.ledger, "sqlite:///:memory:")
        await self.db.open()
        self.addCleanup(self.db.close)


class WalletAccountTest(WalletTestCase):

    async def test_private_key_for_hierarchical_account(self):
        wallet = Wallet(self.ledger, self.db)
        account = wallet.add_account({
            "seed":
                "carbon smart garage balance margin twelve chest sword toas"
                "t envelope bottom stomach absent"
        })
        await account.receiving.ensure_address_gap()
        private_key = await wallet.get_private_key_for_address(
            'bCqJrLHdoiRqEZ1whFZ3WHNb33bP34SuGx'
        )
        self.assertEqual(
            private_key.extended_key_string(),
            'xprv9vwXVierUTT4hmoe3dtTeBfbNv1ph2mm8RWXARU6HsZjBaAoFaS2FRQu4fptR'
            'AyJWhJW42dmsEaC1nKnVKKTMhq3TVEHsNj1ca3ciZMKktT'
        )
        self.assertIsNone(
            await wallet.get_private_key_for_address('BcQjRlhDOIrQez1WHfz3whnB33Bp34sUgX')
        )

    async def test_private_key_for_single_address_account(self):
        wallet = Wallet(self.ledger, self.db)
        account = wallet.add_account({
            "seed":
                "carbon smart garage balance margin twelve chest sword toas"
                "t envelope bottom stomach absent",
            'address_generator': {'name': 'single-address'}
        })
        address = await account.receiving.ensure_address_gap()
        private_key = await wallet.get_private_key_for_address(address[0])
        self.assertEqual(
            private_key.extended_key_string(),
            'xprv9s21ZrQH143K42ovpZygnjfHdAqSd9jo7zceDfPRogM7bkkoNVv7'
            'DRNLEoB8HoirMgH969NrgL8jNzLEegqFzPRWM37GXd4uE8uuRkx4LAe',
        )
        self.assertIsNone(
            await wallet.get_private_key_for_address('BcQjRlhDOIrQez1WHfz3whnB33Bp34sUgX')
        )

    async def test_save_max_gap(self):
        wallet = Wallet(self.ledger, self.db)
        account = wallet.generate_account(
            'lbryum', {
                'name': 'deterministic-chain',
                'receiving': {'gap': 3, 'maximum_uses_per_address': 2},
                'change': {'gap': 4, 'maximum_uses_per_address': 2}
            }
        )
        self.assertEqual(account.receiving.gap, 3)
        self.assertEqual(account.change.gap, 4)
        await wallet.save_max_gap()
        self.assertEqual(account.receiving.gap, 20)
        self.assertEqual(account.change.gap, 6)
        # doesn't fail for single-address account
        wallet.generate_account('lbryum', {'name': 'single-address'})
        await wallet.save_max_gap()


class TestWalletCreation(WalletTestCase):

    def test_create_wallet_and_accounts(self):
        wallet = Wallet(self.ledger, self.db)
        self.assertEqual(wallet.name, 'Wallet')
        self.assertListEqual(wallet.accounts, [])

        account1 = wallet.generate_account()
        wallet.generate_account()
        wallet.generate_account()
        self.assertEqual(wallet.default_account, account1)
        self.assertEqual(len(wallet.accounts), 3)

    def test_load_and_save_wallet(self):
        wallet_dict = {
            'version': 1,
            'name': 'Main Wallet',
            'ledger': 'lbc_mainnet',
            'preferences': {},
            'accounts': [
                {
                    'certificates': {},
                    'name': 'An Account',
                    'modified_on': 123.456,
                    'seed':
                        "carbon smart garage balance margin twelve chest sword toast envelope bottom stomac"
                        "h absent",
                    'encrypted': False,
                    'private_key':
                        'xprv9s21ZrQH143K42ovpZygnjfHdAqSd9jo7zceDfPRogM7bkkoNVv7'
                        'DRNLEoB8HoirMgH969NrgL8jNzLEegqFzPRWM37GXd4uE8uuRkx4LAe',
                    'public_key':
                        'xpub661MyMwAqRbcGWtPvbWh9sc2BCfw2cTeVDYF23o3N1t6UZ5wv3EMm'
                        'Dgp66FxHuDtWdft3B5eL5xQtyzAtkdmhhC95gjRjLzSTdkho95asu9',
                    'address_generator': {
                        'name': 'deterministic-chain',
                        'receiving': {'gap': 17, 'maximum_uses_per_address': 3},
                        'change': {'gap': 10, 'maximum_uses_per_address': 3}
                    }
                }
            ]
        }

        storage = WalletStorage(default=wallet_dict)
        wallet = Wallet.from_storage(self.ledger, self.db, storage)
        self.assertEqual(wallet.name, 'Main Wallet')
        self.assertEqual(
            hexlify(wallet.hash),
            b'3b23aae8cd9b360f4296130b8f7afc5b2437560cdef7237bed245288ce8a5f79'
        )
        self.assertEqual(len(wallet.accounts), 1)
        account = wallet.default_account
        self.assertIsInstance(account, Account)
        self.maxDiff = None
        self.assertDictEqual(wallet_dict, wallet.to_dict())

        encrypted = wallet.pack('password')
        decrypted = Wallet.unpack('password', encrypted)
        self.assertEqual(decrypted['accounts'][0]['name'], 'An Account')

    def test_read_write(self):
        manager = WalletManager(self.ledger, self.db)

        with tempfile.NamedTemporaryFile(suffix='.json') as wallet_file:
            wallet_file.write(b'{"version": 1}')
            wallet_file.seek(0)

            # create and write wallet to a file
            wallet = manager.import_wallet(wallet_file.name)
            account = wallet.generate_account()
            wallet.save()

            # read wallet from file
            wallet_storage = WalletStorage(wallet_file.name)
            wallet = Wallet.from_storage(self.ledger, self.db, wallet_storage)

            self.assertEqual(account.public_key.address, wallet.default_account.public_key.address)

    def test_merge(self):
        wallet1 = Wallet(self.ledger, self.db)
        wallet1.preferences['one'] = 1
        wallet1.preferences['conflict'] = 1
        wallet1.generate_account()
        wallet2 = Wallet(self.ledger, self.db)
        wallet2.preferences['two'] = 2
        wallet2.preferences['conflict'] = 2  # will be more recent
        wallet2.generate_account()

        self.assertEqual(len(wallet1.accounts), 1)
        self.assertEqual(wallet1.preferences, {'one': 1, 'conflict': 1})

        added = await wallet1.merge('password', wallet2.pack('password'))
        self.assertEqual(added[0].id, wallet2.default_account.id)
        self.assertEqual(len(wallet1.accounts), 2)
        self.assertEqual(wallet1.accounts[1].id, wallet2.default_account.id)
        self.assertEqual(wallet1.preferences, {'one': 1, 'two': 2, 'conflict': 2})


class TestTimestampedPreferences(TestCase):

    def test_init(self):
        p = TimestampedPreferences()
        p['one'] = 1
        p2 = TimestampedPreferences(p.data)
        self.assertEqual(p2['one'], 1)

    def test_hash(self):
        p = TimestampedPreferences()
        self.assertEqual(
            hexlify(p.hash), b'44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'
        )
        with mock.patch('time.time', mock.Mock(return_value=12345)):
            p['one'] = 1
        self.assertEqual(
            hexlify(p.hash), b'c9e82bf4cb099dd0125f78fa381b21a8131af601917eb531e1f5f980f8f3da66'
        )

    def test_merge(self):
        p1 = TimestampedPreferences()
        p2 = TimestampedPreferences()
        with mock.patch('time.time', mock.Mock(return_value=10)):
            p1['one'] = 1
            p1['conflict'] = 1
        with mock.patch('time.time', mock.Mock(return_value=20)):
            p2['two'] = 2
            p2['conflict'] = 2

        # conflict in p2 overrides conflict in p1
        p1.merge(p2.data)
        self.assertEqual(p1, {'one': 1, 'two': 2, 'conflict': 2})

        # have a newer conflict in p1 so it is not overridden this time
        with mock.patch('time.time', mock.Mock(return_value=21)):
            p1['conflict'] = 1
        p1.merge(p2.data)
        self.assertEqual(p1, {'one': 1, 'two': 2, 'conflict': 1})
