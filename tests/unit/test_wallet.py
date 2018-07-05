import tempfile
from twisted.trial import unittest

from torba.coin.bitcoinsegwit import MainNetLedger as BTCLedger
from torba.coin.bitcoincash import MainNetLedger as BCHLedger
from torba.manager import WalletManager
from torba.wallet import Wallet, WalletStorage


class TestWalletCreation(unittest.TestCase):

    def setUp(self):
        self.manager = WalletManager()
        config = {'data_path': '/tmp/wallet'}
        self.btc_ledger = self.manager.get_or_create_ledger(BTCLedger.get_id(), config)
        self.bch_ledger = self.manager.get_or_create_ledger(BCHLedger.get_id(), config)

    def test_create_wallet_and_accounts(self):
        wallet = Wallet()
        self.assertEqual(wallet.name, 'Wallet')
        self.assertEqual(wallet.accounts, [])

        account1 = wallet.generate_account(self.btc_ledger)
        wallet.generate_account(self.btc_ledger)
        wallet.generate_account(self.bch_ledger)
        self.assertEqual(wallet.default_account, account1)
        self.assertEqual(len(wallet.accounts), 3)

    def test_load_and_save_wallet(self):
        wallet_dict = {
            'version': 1,
            'name': 'Main Wallet',
            'accounts': [
                {
                    'ledger': 'btc_mainnet',
                    'seed':
                        "carbon smart garage balance margin twelve chest sword toast envelope bottom stomac"
                        "h absent",
                    'encrypted': False,
                    'private_key':
                        'xprv9s21ZrQH143K2dyhK7SevfRG72bYDRNv25yKPWWm6dqApNxm1Zb1m5gGcBWYfbsPjTr2v5joit8Af2Zp5P'
                        '6yz3jMbycrLrRMpeAJxR8qDg8',
                    'public_key':
                        'xpub661MyMwAqRbcF84AR8yfHoMzf4S2ct6mPJtvBtvNeyN9hBHuZ6uGJszkTSn5fQUCdz3XU17eBzFeAUwV6f'
                        'iW44g14WF52fYC5J483wqQ5ZP',
                    'receiving_gap': 10,
                    'receiving_maximum_use_per_address': 2,
                    'change_gap': 10,
                    'change_maximum_use_per_address': 2,
                }
            ]
        }

        storage = WalletStorage(default=wallet_dict)
        wallet = Wallet.from_storage(storage, self.manager)
        self.assertEqual(wallet.name, 'Main Wallet')
        self.assertEqual(len(wallet.accounts), 1)
        account = wallet.default_account
        self.assertIsInstance(account, BTCLedger.account_class)
        self.maxDiff = None
        self.assertDictEqual(wallet_dict, wallet.to_dict())

    def test_read_write(self):
        manager = WalletManager()
        config = {'data_path': '/tmp/wallet'}
        ledger = manager.get_or_create_ledger(BTCLedger.get_id(), config)

        with tempfile.NamedTemporaryFile(suffix='.json') as wallet_file:
            wallet_file.write(b'{"version": 1}')
            wallet_file.seek(0)

            # create and write wallet to a file
            wallet_storage = WalletStorage(wallet_file.name)
            wallet = Wallet.from_storage(wallet_storage, manager)
            account = wallet.generate_account(ledger)
            wallet.save()

            # read wallet from file
            wallet_storage = WalletStorage(wallet_file.name)
            wallet = Wallet.from_storage(wallet_storage, manager)

            self.assertEqual(account.public_key.address, wallet.default_account.public_key.address)
