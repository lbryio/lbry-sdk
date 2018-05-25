from twisted.trial import unittest

from torba.coin.btc import BTC
from torba.manager import WalletManager
from torba.wallet import Account, Wallet, WalletStorage

from .ftc import FTC


class TestWalletCreation(unittest.TestCase):

    def setUp(self):
        self.manager = WalletManager()
        self.btc_ledger = self.manager.get_or_create_ledger(BTC.get_id())
        self.ftc_ledger = self.manager.get_or_create_ledger(FTC.get_id())

    def test_create_wallet_and_accounts(self):
        wallet = Wallet()
        self.assertEqual(wallet.name, 'Wallet')
        self.assertEqual(wallet.coins, [])
        self.assertEqual(wallet.accounts, [])

        account1 = wallet.generate_account(self.btc_ledger)
        account2 = wallet.generate_account(self.btc_ledger)
        account3 = wallet.generate_account(self.ftc_ledger)
        self.assertEqual(wallet.default_account, account1)
        self.assertEqual(len(wallet.coins), 2)
        self.assertEqual(len(wallet.accounts), 3)
        self.assertIsInstance(wallet.coins[0], BTC)
        self.assertIsInstance(wallet.coins[1], FTC)

        self.assertEqual(len(account1.receiving_keys.addresses), 0)
        self.assertEqual(len(account1.change_keys.addresses), 0)
        self.assertEqual(len(account2.receiving_keys.addresses), 0)
        self.assertEqual(len(account2.change_keys.addresses), 0)
        self.assertEqual(len(account3.receiving_keys.addresses), 0)
        self.assertEqual(len(account3.change_keys.addresses), 0)
        account1.ensure_enough_addresses()
        account2.ensure_enough_addresses()
        account3.ensure_enough_addresses()
        self.assertEqual(len(account1.receiving_keys.addresses), 20)
        self.assertEqual(len(account1.change_keys.addresses), 6)
        self.assertEqual(len(account2.receiving_keys.addresses), 20)
        self.assertEqual(len(account2.change_keys.addresses), 6)
        self.assertEqual(len(account3.receiving_keys.addresses), 20)
        self.assertEqual(len(account3.change_keys.addresses), 6)

    def test_load_and_save_wallet(self):
        wallet_dict = {
            'name': 'Main Wallet',
            'accounts': [
                {
                    'coin': 'btc_mainnet',
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
                    'receiving_keys': [
                        '0222345947a59dca4a3363ffa81ac87dd907d2b2feff57383eaeddbab266ca5f2d',
                        '03fdc9826d5d00a484188cba8eb7dba5877c0323acb77905b7bcbbab35d94be9f6'
                    ],
                    'change_gap': 10,
                    'change_keys': [
                        '038836be4147836ed6b4df6a89e0d9f1b1c11cec529b7ff5407de57f2e5b032c83'
                    ]
                }
            ]
        }

        storage = WalletStorage(default=wallet_dict)
        wallet = Wallet.from_storage(storage, self.manager)
        self.assertEqual(wallet.name, 'Main Wallet')
        self.assertEqual(len(wallet.coins), 1)
        self.assertIsInstance(wallet.coins[0], BTC)
        self.assertEqual(len(wallet.accounts), 1)
        account = wallet.default_account
        self.assertIsInstance(account, Account)

        self.assertEqual(len(account.receiving_keys.addresses), 2)
        self.assertEqual(
            account.receiving_keys.addresses[0],
            '1PmX9T3sCiDysNtWszJa44SkKcpGc2NaXP'
        )
        self.assertEqual(len(account.change_keys.addresses), 1)
        self.assertEqual(
            account.change_keys.addresses[0],
            '1PUbu1D1f3c244JPRSJKBCxRqui5NT6geR'
        )
        wallet_dict['coins'] = {'btc_mainnet': {'fee_per_byte': 50}}
        self.assertDictEqual(wallet_dict, wallet.to_dict())
