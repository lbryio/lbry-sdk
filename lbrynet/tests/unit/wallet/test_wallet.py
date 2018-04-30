from twisted.trial import unittest

from lbrynet.wallet.coins.bitcoin import BTC
from lbrynet.wallet.coins.lbc import LBC
from lbrynet.wallet.manager import WalletManager
from lbrynet.wallet.wallet import Account, Wallet, WalletStorage


class TestWalletCreation(unittest.TestCase):

    def setUp(self):
        WalletManager([], {
            LBC.ledger_class: LBC.ledger_class(LBC),
            BTC.ledger_class: BTC.ledger_class(BTC)
        }).install()
        self.coin = LBC()

    def test_create_wallet_and_accounts(self):
        wallet = Wallet()
        self.assertEqual(wallet.name, 'Wallet')
        self.assertEqual(wallet.coins, [])
        self.assertEqual(wallet.accounts, [])

        account1 = wallet.generate_account(LBC)
        account2 = wallet.generate_account(LBC)
        account3 = wallet.generate_account(BTC)
        self.assertEqual(wallet.default_account, account1)
        self.assertEqual(len(wallet.coins), 2)
        self.assertEqual(len(wallet.accounts), 3)
        self.assertIsInstance(wallet.coins[0], LBC)
        self.assertIsInstance(wallet.coins[1], BTC)

        self.assertEqual(len(account1.receiving_keys.addresses), 0)
        self.assertEqual(len(account1.change_keys.addresses), 0)
        self.assertEqual(len(account2.receiving_keys.addresses), 0)
        self.assertEqual(len(account2.change_keys.addresses), 0)
        self.assertEqual(len(account3.receiving_keys.addresses), 0)
        self.assertEqual(len(account3.change_keys.addresses), 0)
        wallet.ensure_enough_addresses()
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
                    'coin': 'lbc_mainnet',
                    'seed':
                        "carbon smart garage balance margin twelve chest sword toast envelope botto"
                        "m stomach absent",
                    'encrypted': False,
                    'private_key':
                        'LprvXPsFZUGgrX1X9HiyxABZSf6hWJK7kHv4zGZRyyiHbBq5Wu94cE1DMvttnpLYReTPNW4eYwX9dWMvTz3PrB'
                        'wwbRafEeA1ZXL69U2egM4QJdq',
                    'public_key':
                        'Lpub2hkYkGHXktBhLpwUhKKogyuJ1M7Gt9EkjFTVKyDqZiZpWdhLuCoT1eKDfXfysMFfG4SzfXXcA2SsHzrjHK'
                        'Ea5aoCNRBAhjT5NPLV6hXtvEi',
                    'receiving_gap': 10,
                    'receiving_keys': [
                        '02c68e2d1cf85404c86244ffa279f4c5cd00331e996d30a86d6e46480e3a9220f4',
                        '03c5a997d0549875d23b8e4bbc7b4d316d962587483f3a2e62ddd90a21043c4941'
                    ],
                    'change_gap': 10,
                    'change_keys': [
                        '021460e8d728eee325d0d43128572b2e2bacdc027e420451df100cf9f2154ea5ab'
                    ]
                }
            ]
        }

        storage = WalletStorage(default=wallet_dict)
        wallet = Wallet.from_storage(storage)
        self.assertEqual(wallet.name, 'Main Wallet')
        self.assertEqual(len(wallet.coins), 1)
        self.assertIsInstance(wallet.coins[0], LBC)
        self.assertEqual(len(wallet.accounts), 1)
        account = wallet.default_account
        self.assertIsInstance(account, Account)

        self.assertEqual(len(account.receiving_keys.addresses), 2)
        self.assertEqual(
            account.receiving_keys.addresses[0],
            'bCqJrLHdoiRqEZ1whFZ3WHNb33bP34SuGx'
        )
        self.assertEqual(len(account.change_keys.addresses), 1)
        self.assertEqual(
            account.change_keys.addresses[0],
            'bFpHENtqugKKHDshKFq2Mnb59Y2bx4vKgL'
        )
        wallet_dict['coins'] = {'lbc_mainnet': {'fee_per_name_char': 200000, 'fee_per_byte': 50}}
        self.assertDictEqual(wallet_dict, wallet.to_dict())
