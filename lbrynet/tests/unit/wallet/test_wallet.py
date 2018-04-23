from twisted.trial import unittest
from lbrynet.wallet.wallet import Account, Wallet
from lbrynet.wallet.manager import WalletManager
from lbrynet.wallet import set_wallet_manager


class TestWalletAccount(unittest.TestCase):

    def test_wallet_automatically_creates_default_account(self):
        wallet = Wallet()
        set_wallet_manager(WalletManager(wallet=wallet))
        account = wallet.default_account  # type: Account
        self.assertIsInstance(account, Account)
        self.assertEqual(len(account.receiving_keys.child_keys), 0)
        self.assertEqual(len(account.receiving_keys.addresses), 0)
        self.assertEqual(len(account.change_keys.child_keys), 0)
        self.assertEqual(len(account.change_keys.addresses), 0)
        wallet.ensure_enough_addresses()
        self.assertEqual(len(account.receiving_keys.child_keys), 20)
        self.assertEqual(len(account.receiving_keys.addresses), 20)
        self.assertEqual(len(account.change_keys.child_keys), 6)
        self.assertEqual(len(account.change_keys.addresses), 6)

    def test_generate_account_from_seed(self):
        account = Account.generate_from_seed(
            "carbon smart garage balance margin twelve chest sword toast envelope bottom stomach ab"
            "sent"
        )  # type: Account
        self.assertEqual(
            account.private_key.extended_key_string(),
            "xprv9s21ZrQH143K42ovpZygnjfHdAqSd9jo7zceDfPRogM7bkkoNVv7DRNLEoB8HoirMgH969NrgL8jNzLEeg"
            "qFzPRWM37GXd4uE8uuRkx4LAe",
        )
        self.assertEqual(
            account.public_key.extended_key_string(),
            "xpub661MyMwAqRbcGWtPvbWh9sc2BCfw2cTeVDYF23o3N1t6UZ5wv3EMmDgp66FxHuDtWdft3B5eL5xQtyzAtk"
            "dmhhC95gjRjLzSTdkho95asu9",
        )
        self.assertEqual(
            account.receiving_keys.generate_next_address(),
            'bCqJrLHdoiRqEZ1whFZ3WHNb33bP34SuGx'
        )
        private_key = account.get_private_key_for_address('bCqJrLHdoiRqEZ1whFZ3WHNb33bP34SuGx')
        self.assertEqual(
            private_key.extended_key_string(),
            'xprv9vwXVierUTT4hmoe3dtTeBfbNv1ph2mm8RWXARU6HsZjBaAoFaS2FRQu4fptRAyJWhJW42dmsEaC1nKnVK'
            'KTMhq3TVEHsNj1ca3ciZMKktT'
        )
        self.assertIsNone(account.get_private_key_for_address('BcQjRlhDOIrQez1WHfz3whnB33Bp34sUgX'))

    def test_load_and_save_account(self):
        wallet_data = {
            'name': 'Main Wallet',
            'accounts': {
                0: {
                    'seed':
                        "carbon smart garage balance margin twelve chest sword toast envelope botto"
                        "m stomach absent",
                    'encrypted': False,
                    'private_key':
                        "xprv9s21ZrQH143K42ovpZygnjfHdAqSd9jo7zceDfPRogM7bkkoNVv7DRNLEoB8HoirMgH969"
                        "NrgL8jNzLEegqFzPRWM37GXd4uE8uuRkx4LAe",
                    'public_key':
                        "xpub661MyMwAqRbcGWtPvbWh9sc2BCfw2cTeVDYF23o3N1t6UZ5wv3EMmDgp66FxHuDtWdft3B"
                        "5eL5xQtyzAtkdmhhC95gjRjLzSTdkho95asu9",
                    'receiving_gap': 10,
                    'receiving_keys': [
                        '02c68e2d1cf85404c86244ffa279f4c5cd00331e996d30a86d6e46480e3a9220f4',
                        '03c5a997d0549875d23b8e4bbc7b4d316d962587483f3a2e62ddd90a21043c4941'],
                    'change_gap': 10,
                    'change_keys': [
                        '021460e8d728eee325d0d43128572b2e2bacdc027e420451df100cf9f2154ea5ab']
                }
            }
        }

        wallet = Wallet.from_json(wallet_data)
        set_wallet_manager(WalletManager(wallet=wallet))
        self.assertEqual(wallet.name, 'Main Wallet')

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

        self.assertDictEqual(
            wallet_data['accounts'][0],
            account.to_json()
        )
