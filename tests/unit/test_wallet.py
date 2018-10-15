import tempfile

from orchstr8.testcase import AsyncioTestCase

from torba.coin.bitcoinsegwit import MainNetLedger as BTCLedger
from torba.coin.bitcoincash import MainNetLedger as BCHLedger
from torba.basemanager import BaseWalletManager
from torba.wallet import Wallet, WalletStorage


class TestWalletCreation(AsyncioTestCase):

    async def asyncSetUp(self):
        self.manager = BaseWalletManager()
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
                    'name': 'An Account',
                    'ledger': 'btc_mainnet',
                    'seed':
                        "carbon smart garage balance margin twelve chest sword toast envelope bottom stomac"
                        "h absent",
                    'encrypted': False,
                    'private_key':
                        'xprv9s21ZrQH143K3TsAz5efNV8K93g3Ms3FXcjaWB9fVUsMwAoE3Z'
                        'T4vYymkp5BxKKfnpz8J6sHDFriX1SnpvjNkzcks8XBnxjGLS83BTyfpna',
                    'public_key':
                        'xpub661MyMwAqRbcFwwe67Bfjd53h5WXmKm6tqfBJZZH3pQLoy8Nb6'
                        'mKUMJFc7UbpVNzmwFPN2evn3YHnig1pkKVYcvCV8owTd2yAcEkJfCX53g',
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
        self.assertEqual(len(wallet.accounts), 1)
        account = wallet.default_account
        self.assertIsInstance(account, BTCLedger.account_class)
        self.maxDiff = None
        self.assertDictEqual(wallet_dict, wallet.to_dict())

    def test_read_write(self):
        manager = BaseWalletManager()
        config = {'data_path': '/tmp/wallet'}
        ledger = manager.get_or_create_ledger(BTCLedger.get_id(), config)

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
