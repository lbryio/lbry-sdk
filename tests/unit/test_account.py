from binascii import hexlify
from twisted.trial import unittest

from torba.coin.bitcoinsegwit import BTC
from torba.basemanager import WalletManager
from torba.wallet import Account


class TestAccount(unittest.TestCase):

    def setUp(self):
        ledger = WalletManager().get_or_create_ledger(BTC.get_id())
        self.coin = BTC(ledger)

    def test_generate_account(self):
        account = Account.generate(self.coin, u"torba")
        self.assertEqual(account.coin, self.coin)
        self.assertIsNotNone(account.seed)
        self.assertEqual(account.public_key.coin, self.coin)
        self.assertEqual(account.private_key.public_key, account.public_key)

        self.assertEqual(len(account.receiving_keys.child_keys), 0)
        self.assertEqual(len(account.receiving_keys.addresses), 0)
        self.assertEqual(len(account.change_keys.child_keys), 0)
        self.assertEqual(len(account.change_keys.addresses), 0)

        account.ensure_enough_addresses()
        self.assertEqual(len(account.receiving_keys.child_keys), 20)
        self.assertEqual(len(account.receiving_keys.addresses), 20)
        self.assertEqual(len(account.change_keys.child_keys), 6)
        self.assertEqual(len(account.change_keys.addresses), 6)

    def test_generate_account_from_seed(self):
        account = Account.from_seed(
            self.coin,
            u"carbon smart garage balance margin twelve chest sword toast envelope bottom stomach ab"
            u"sent",
            u"torba"
        )
        self.assertEqual(
            account.private_key.extended_key_string(),
            b'xprv9s21ZrQH143K2dyhK7SevfRG72bYDRNv25yKPWWm6dqApNxm1Zb1m5gGcBWYfbsPjTr2v5joit8Af2Zp5P'
            b'6yz3jMbycrLrRMpeAJxR8qDg8'
        )
        self.assertEqual(
            account.public_key.extended_key_string(),
            b'xpub661MyMwAqRbcF84AR8yfHoMzf4S2ct6mPJtvBtvNeyN9hBHuZ6uGJszkTSn5fQUCdz3XU17eBzFeAUwV6f'
            b'iW44g14WF52fYC5J483wqQ5ZP'
        )
        self.assertEqual(
            account.receiving_keys.generate_next_address(),
            b'1PmX9T3sCiDysNtWszJa44SkKcpGc2NaXP'
        )
        private_key = account.get_private_key_for_address(b'1PmX9T3sCiDysNtWszJa44SkKcpGc2NaXP')
        self.assertEqual(
            private_key.extended_key_string(),
            b'xprv9xNEfQ296VTRaEUDZ8oKq74xw2U6kpj486vFUB4K1wT9U25GX4UwuzFgJN1YuRrqkQ5TTwCpkYnjNpSoHS'
            b'BaEigNHPkoeYbuPMRo6mRUjxg'
        )
        self.assertIsNone(account.get_private_key_for_address(b'BcQjRlhDOIrQez1WHfz3whnB33Bp34sUgX'))

        self.assertEqual(
            hexlify(private_key.wif()),
            b'1cc27be89ad47ef932562af80e95085eb0ab2ae3e5c019b1369b8b05ff2e94512f01'
        )

    def test_load_and_save_account(self):
        account_data = {
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

        account = Account.from_dict(self.coin, account_data)

        self.assertEqual(len(account.receiving_keys.addresses), 2)
        self.assertEqual(
            account.receiving_keys.addresses[0],
            b'1PmX9T3sCiDysNtWszJa44SkKcpGc2NaXP'
        )
        self.assertEqual(len(account.change_keys.addresses), 1)
        self.assertEqual(
            account.change_keys.addresses[0],
            b'1PUbu1D1f3c244JPRSJKBCxRqui5NT6geR'
        )

        self.maxDiff = None
        account_data['coin'] = 'btc_mainnet'
        self.assertDictEqual(account_data, account.to_dict())
