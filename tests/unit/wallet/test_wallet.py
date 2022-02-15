import json
import jsonschema
import os
import pathlib
import tempfile
from binascii import hexlify

from unittest import TestCase, mock
from lbry.testcase import AsyncioTestCase
from lbry.wallet import (
    Ledger, RegTestLedger, WalletManager, Account,
    Wallet, WalletStorage, TimestampedPreferences
)


class TestWalletCreation(AsyncioTestCase):

    async def asyncSetUp(self):
        self.manager = WalletManager()
        config = {'data_path': '/tmp/wallet'}
        self.main_ledger = self.manager.get_or_create_ledger(Ledger.get_id(), config)
        self.test_ledger = self.manager.get_or_create_ledger(RegTestLedger.get_id(), config)

        base_dir = pathlib.Path(__file__).parents[3]
        types_dir = base_dir.joinpath('lbry', 'schema', 'types', 'v2')

        with types_dir.joinpath('wallet.json').open() as f:
          self.wallet_schema = json.load(f)

    def test_create_wallet_and_accounts(self):
        wallet = Wallet()
        self.assertEqual(wallet.name, 'Wallet')
        self.assertListEqual(wallet.accounts, [])

        account1 = wallet.generate_account(self.main_ledger)
        wallet.generate_account(self.main_ledger)
        wallet.generate_account(self.test_ledger)
        self.assertEqual(wallet.default_account, account1)
        self.assertEqual(len(wallet.accounts), 3)

    def test_load_and_save_wallet(self):
        wallet_dict = {
            'version': 1,
            'name': 'Main Wallet',
            'preferences': {},
            'accounts': [
                {
                    'certificates': {},
                    'name': 'An Account',
                    'ledger': 'lbc_mainnet',
                    'modified_on': 123,
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
        wallet = Wallet.from_storage(storage, self.manager)
        self.assertEqual(wallet.name, 'Main Wallet')
        self.assertEqual(
            hexlify(wallet.hash), b'869acc4660dde0f13784ed743796adf89562cdf79fdfc9e5c6dbea98d62ccf90'
        )
        self.assertEqual(len(wallet.accounts), 1)
        account = wallet.default_account
        self.assertIsInstance(account, Account)
        self.maxDiff = None
        self.assertDictEqual(wallet_dict, wallet.to_dict())

        encrypted = wallet.pack('password')
        decrypted = Wallet.unpack('password', encrypted)
        self.assertEqual(decrypted['accounts'][0]['name'], 'An Account')


    def test_wallet_file_schema(self):
        # One Deterministic Chain, one Single Address, to test both paths in the schema.
        wallet_dict = {
            'version': 1,
            'name': 'Main Wallet',
            'preferences': {},
            'accounts': [
                {
                    'certificates': {'x': 'y'},
                    'name': 'Account 1',
                    'ledger': 'lbc_mainnet',
                    'modified_on': 123,
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
                },
                {
                    'certificates': {'a': 'b'},
                    'name': 'Account 2',
                    'ledger': 'lbc_mainnet',
                    'modified_on': 123,
                    'seed':
                        "carbon smart garage balance margin twelve chest sword toast envelope bottom stomac"
                        "h absent",
                    'encrypted': True,
                    'private_key':
                        'xprv9s21ZrQH143K42ovpZygnjfHdAqSd9jo7zceDfPRogM7bkkoNVv7'
                        'DRNLEoB8HoirMgH969NrgL8jNzLEegqFzPRWM37GXd4uE8uuRkx4LAe',
                    'public_key':
                        'xpub661MyMwAqRbcGWtPvbWh9sc2BCfw2cTeVDYF23o3N1t6UZ5wv3EMm'
                        'Dgp66FxHuDtWdft3B5eL5xQtyzAtkdmhhC95gjRjLzSTdkho95asu9',
                    'address_generator': {
                        'name': 'single-address',
                    }
                },
            ]
        }

        storage = WalletStorage(default=wallet_dict)
        wallet = Wallet.from_storage(storage, self.manager)
        self.assertDictEqual(wallet_dict, wallet.to_dict())
        jsonschema.validate(schema=self.wallet_schema, instance=wallet.to_dict())

    def test_no_password_but_encryption_preferred(self):
        wallet_dict = {
            'version': 1,
            'name': 'Main Wallet',
            'preferences': {
                "encrypt-on-disk": {
                    "ts": 1571762543.351794,
                    "value": True
                },
            },
            'accounts': [
                {
                    'certificates': {},
                    'name': 'An Account',
                    'ledger': 'lbc_mainnet',
                    'modified_on': 123,
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
        wallet = Wallet.from_storage(storage, self.manager)
        self.assertEqual(
            hexlify(wallet.hash), b'8cc6341885e6ad46f72a17364c65f8441f09e79996c55202196b399c75f8d751'
        )
        self.assertFalse(wallet.is_encrypted)

    def test_read_write(self):
        manager = WalletManager()
        config = {'data_path': '/tmp/wallet'}
        ledger = manager.get_or_create_ledger(Ledger.get_id(), config)

        with tempfile.NamedTemporaryFile(suffix='.json') as wallet_file:
            wallet_file.write(b'{"version": 1}')
            wallet_file.seek(0)

            # create and write wallet to a file
            wallet = manager.import_wallet(wallet_file.name)
            account = wallet.generate_account(ledger)
            wallet.save()

            # read wallet from file
            wallet_storage = WalletStorage(wallet_file.name)
            wallet = Wallet.from_storage(wallet_storage, manager)

            self.assertEqual(account.public_key.address, wallet.default_account.public_key.address)

    def test_merge(self):
        wallet1 = Wallet()
        wallet1.preferences['one'] = 1
        wallet1.preferences['conflict'] = 1
        wallet1.generate_account(self.main_ledger)
        wallet2 = Wallet()
        wallet2.preferences['two'] = 2
        wallet2.preferences['conflict'] = 2  # will be more recent
        wallet2.generate_account(self.main_ledger)

        self.assertEqual(len(wallet1.accounts), 1)
        self.assertEqual(wallet1.preferences, {'one': 1, 'conflict': 1})

        added = wallet1.merge(self.manager, 'password', wallet2.pack('password'))
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
