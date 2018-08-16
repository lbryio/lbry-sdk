from twisted.trial import unittest
from twisted.internet import defer

from lbrynet.wallet.ledger import MainNetLedger, WalletDatabase
from lbrynet.wallet.header import Headers
from lbrynet.wallet.account import Account
from torba.wallet import Wallet


class TestAccount(unittest.TestCase):

    def setUp(self):
        self.ledger = MainNetLedger({
            'db': WalletDatabase(':memory:'),
            'headers': Headers(':memory:')
        })
        return self.ledger.db.open()

    @defer.inlineCallbacks
    def test_generate_account(self):
        account = Account.generate(self.ledger, Wallet(), 'lbryum')
        self.assertEqual(account.ledger, self.ledger)
        self.assertIsNotNone(account.seed)
        self.assertEqual(account.public_key.ledger, self.ledger)
        self.assertEqual(account.private_key.public_key, account.public_key)

        self.assertEqual(account.public_key.ledger, self.ledger)
        self.assertEqual(account.private_key.public_key, account.public_key)

        addresses = yield account.receiving.get_addresses()
        self.assertEqual(len(addresses), 0)
        addresses = yield account.change.get_addresses()
        self.assertEqual(len(addresses), 0)

        yield account.ensure_address_gap()

        addresses = yield account.receiving.get_addresses()
        self.assertEqual(len(addresses), 20)
        addresses = yield account.change.get_addresses()
        self.assertEqual(len(addresses), 6)

    @defer.inlineCallbacks
    def test_generate_account_from_seed(self):
        account = Account.from_dict(
            self.ledger, Wallet(), {
                "seed":
                    "carbon smart garage balance margin twelve chest sword toas"
                    "t envelope bottom stomach absent"
            }
        )
        self.assertEqual(
            account.private_key.extended_key_string(),
            'xprv9s21ZrQH143K42ovpZygnjfHdAqSd9jo7zceDfPRogM7bkkoNVv7DRNLEoB8'
            'HoirMgH969NrgL8jNzLEegqFzPRWM37GXd4uE8uuRkx4LAe'
        )
        self.assertEqual(
            account.public_key.extended_key_string(),
            'xpub661MyMwAqRbcGWtPvbWh9sc2BCfw2cTeVDYF23o3N1t6UZ5wv3EMmDgp66FxH'
            'uDtWdft3B5eL5xQtyzAtkdmhhC95gjRjLzSTdkho95asu9'
        )
        address = yield account.receiving.ensure_address_gap()
        self.assertEqual(address[0], 'bCqJrLHdoiRqEZ1whFZ3WHNb33bP34SuGx')

        private_key = yield self.ledger.get_private_key_for_address('bCqJrLHdoiRqEZ1whFZ3WHNb33bP34SuGx')
        self.assertEqual(
            private_key.extended_key_string(),
            'xprv9vwXVierUTT4hmoe3dtTeBfbNv1ph2mm8RWXARU6HsZjBaAoFaS2FRQu4fptR'
            'AyJWhJW42dmsEaC1nKnVKKTMhq3TVEHsNj1ca3ciZMKktT'
        )
        private_key = yield self.ledger.get_private_key_for_address('BcQjRlhDOIrQez1WHfz3whnB33Bp34sUgX')
        self.assertIsNone(private_key)

    def test_load_and_save_account(self):
        account_data = {
            'name': 'Main Account',
            'seed':
                "carbon smart garage balance margin twelve chest sword toast envelope bottom stomac"
                "h absent",
            'encrypted': False,
            'private_key':
                'xprv9s21ZrQH143K42ovpZygnjfHdAqSd9jo7zceDfPRogM7bkkoNVv7DRNLEoB8'
                'HoirMgH969NrgL8jNzLEegqFzPRWM37GXd4uE8uuRkx4LAe',
            'public_key':
                'xpub661MyMwAqRbcGWtPvbWh9sc2BCfw2cTeVDYF23o3N1t6UZ5wv3EMmDgp66FxH'
                'uDtWdft3B5eL5xQtyzAtkdmhhC95gjRjLzSTdkho95asu9',
            'certificates': {},
            'address_generator': {
                'name': 'deterministic-chain',
                'receiving': {'gap': 17, 'maximum_uses_per_address': 2},
                'change': {'gap': 10, 'maximum_uses_per_address': 2}
            }
        }

        account = Account.from_dict(self.ledger, Wallet(), account_data)
        account_data['ledger'] = 'lbc_mainnet'
        self.assertDictEqual(account_data, account.to_dict())
