from torba.testcase import AsyncioTestCase
from torba.client.wallet import Wallet

from lbrynet.wallet.ledger import MainNetLedger, WalletDatabase
from lbrynet.wallet.header import Headers
from lbrynet.wallet.account import Account


class TestAccount(AsyncioTestCase):

    async def asyncSetUp(self):
        self.ledger = MainNetLedger({
            'db': WalletDatabase(':memory:'),
            'headers': Headers(':memory:')
        })
        await self.ledger.db.open()

    async def asyncTearDown(self):
        await self.ledger.db.close()

    async def test_generate_account(self):
        account = Account.generate(self.ledger, Wallet(), 'lbryum')
        self.assertEqual(account.ledger, self.ledger)
        self.assertIsNotNone(account.seed)
        self.assertEqual(account.public_key.ledger, self.ledger)
        self.assertEqual(account.private_key.public_key, account.public_key)

        self.assertEqual(account.public_key.ledger, self.ledger)
        self.assertEqual(account.private_key.public_key, account.public_key)

        addresses = await account.receiving.get_addresses()
        self.assertEqual(len(addresses), 0)
        addresses = await account.change.get_addresses()
        self.assertEqual(len(addresses), 0)

        await account.ensure_address_gap()

        addresses = await account.receiving.get_addresses()
        self.assertEqual(len(addresses), 20)
        addresses = await account.change.get_addresses()
        self.assertEqual(len(addresses), 6)

    async def test_generate_account_from_seed(self):
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
        address = await account.receiving.ensure_address_gap()
        self.assertEqual(address[0], 'bCqJrLHdoiRqEZ1whFZ3WHNb33bP34SuGx')

        private_key = await self.ledger.get_private_key_for_address('bCqJrLHdoiRqEZ1whFZ3WHNb33bP34SuGx')
        self.assertEqual(
            private_key.extended_key_string(),
            'xprv9vwXVierUTT4hmoe3dtTeBfbNv1ph2mm8RWXARU6HsZjBaAoFaS2FRQu4fptR'
            'AyJWhJW42dmsEaC1nKnVKKTMhq3TVEHsNj1ca3ciZMKktT'
        )
        private_key = await self.ledger.get_private_key_for_address('BcQjRlhDOIrQez1WHfz3whnB33Bp34sUgX')
        self.assertIsNone(private_key)

    def test_load_and_save_account(self):
        account_data = {
            'name': 'Main Account',
            'modified_on': 123.456,
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

    async def test_save_max_gap(self):
        account = Account.generate(
            self.ledger, Wallet(), 'lbryum', {
                    'name': 'deterministic-chain',
                    'receiving': {'gap': 3, 'maximum_uses_per_address': 2},
                    'change': {'gap': 4, 'maximum_uses_per_address': 2}
                }
        )
        self.assertEqual(account.receiving.gap, 3)
        self.assertEqual(account.change.gap, 4)
        await account.save_max_gap()
        self.assertEqual(account.receiving.gap, 20)
        self.assertEqual(account.change.gap, 6)
        # doesn't fail for single-address account
        account2 = Account.generate(self.ledger, Wallet(), 'lbryum', {'name': 'single-address'})
        await account2.save_max_gap()
