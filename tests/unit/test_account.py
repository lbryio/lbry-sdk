from binascii import hexlify
from twisted.trial import unittest
from twisted.internet import defer

from torba.coin.bitcoinsegwit import MainNetLedger


class TestAccount(unittest.TestCase):

    def setUp(self):
        self.ledger = MainNetLedger(db=':memory:')
        return self.ledger.db.start()

    @defer.inlineCallbacks
    def test_generate_account(self):
        account = self.ledger.account_class.generate(self.ledger, u"torba")
        self.assertEqual(account.ledger, self.ledger)
        self.assertIsNotNone(account.seed)
        self.assertEqual(account.public_key.ledger, self.ledger)
        self.assertEqual(account.private_key.public_key, account.public_key)

        keys = yield account.receiving.get_keys()
        addresses = yield account.receiving.get_addresses()
        self.assertEqual(len(keys), 0)
        self.assertEqual(len(addresses), 0)
        keys = yield account.change.get_keys()
        addresses = yield account.change.get_addresses()
        self.assertEqual(len(keys), 0)
        self.assertEqual(len(addresses), 0)

        yield account.ensure_enough_useable_addresses()

        keys = yield account.receiving.get_keys()
        addresses = yield account.receiving.get_addresses()
        self.assertEqual(len(keys), 20)
        self.assertEqual(len(addresses), 20)
        keys = yield account.change.get_keys()
        addresses = yield account.change.get_addresses()
        self.assertEqual(len(keys), 6)
        self.assertEqual(len(addresses), 6)

    @defer.inlineCallbacks
    def test_generate_account_from_seed(self):
        account = self.ledger.account_class.from_seed(
            self.ledger,
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
        address = yield account.receiving.ensure_enough_useable_addresses()
        self.assertEqual(address[0], b'1PGDB1CRy8UxPCrkcakRqroVnHxqzvUZhp')
        private_key = yield self.ledger.get_private_key_for_address(b'1PGDB1CRy8UxPCrkcakRqroVnHxqzvUZhp')
        self.assertEqual(
            private_key.extended_key_string(),
            b'xprv9xNEfQ296VTRc5QF7AZZ1WTimGzMs54FepRXVxbyypJXCrUKjxsYSyk5EhHYNxU4ApsaBr8AQ4sYo86BbGh2dZSddGXU1CMGwExvnyckjQn'
        )
        invalid_key = yield self.ledger.get_private_key_for_address(b'BcQjRlhDOIrQez1WHfz3whnB33Bp34sUgX')
        self.assertIsNone(invalid_key)

        self.assertEqual(
            hexlify(private_key.wif()),
            b'1c5664e848772b199644ab390b5c27d2f6664d9cdfdb62e1c7ac25151b00858b7a01'
        )

    @defer.inlineCallbacks
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
            'change_gap': 10,
        }

        account = self.ledger.account_class.from_dict(self.ledger, account_data)

        yield account.ensure_enough_useable_addresses()

        keys = yield account.receiving.get_keys()
        addresses = yield account.receiving.get_addresses()
        self.assertEqual(len(keys), 10)
        self.assertEqual(len(addresses), 10)
        keys = yield account.change.get_keys()
        addresses = yield account.change.get_addresses()
        self.assertEqual(len(keys), 10)
        self.assertEqual(len(addresses), 10)

        self.maxDiff = None
        account_data['ledger'] = 'btc_mainnet'
        self.assertDictEqual(account_data, account.to_dict())
