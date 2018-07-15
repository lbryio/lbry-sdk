from binascii import hexlify
from twisted.trial import unittest
from twisted.internet import defer

from torba.coin.bitcoinsegwit import MainNetLedger
from torba.baseaccount import KeyChain, SingleKey


class TestKeyChainAccount(unittest.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        self.ledger = MainNetLedger({'db': MainNetLedger.database_class(':memory:')})
        yield self.ledger.db.start()
        self.account = self.ledger.account_class.generate(self.ledger, u"torba")

    @defer.inlineCallbacks
    def test_generate_account(self):
        account = self.account

        self.assertEqual(account.ledger, self.ledger)
        self.assertIsNotNone(account.seed)
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

        addresses = yield account.get_addresses()
        self.assertEqual(len(addresses), 26)

    @defer.inlineCallbacks
    def test_ensure_address_gap(self):
        account = self.account

        self.assertIsInstance(account.receiving, KeyChain)

        yield account.receiving.generate_keys(4, 7)
        yield account.receiving.generate_keys(0, 3)
        yield account.receiving.generate_keys(8, 11)
        records = yield account.receiving.get_address_records()
        self.assertEqual(
            [r['position'] for r in records],
            [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        )

        # we have 12, but default gap is 20
        new_keys = yield account.receiving.ensure_address_gap()
        self.assertEqual(len(new_keys), 8)
        records = yield account.receiving.get_address_records()
        self.assertEqual(
            [r['position'] for r in records],
            [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
        )

        # case #1: no new addresses needed
        empty = yield account.receiving.ensure_address_gap()
        self.assertEqual(len(empty), 0)

        # case #2: only one new addressed needed
        records = yield account.receiving.get_address_records()
        yield self.ledger.db.set_address_history(records[0]['address'], 'a:1:')
        new_keys = yield account.receiving.ensure_address_gap()
        self.assertEqual(len(new_keys), 1)

        # case #3: 20 addresses needed
        yield self.ledger.db.set_address_history(new_keys[0], 'a:1:')
        new_keys = yield account.receiving.ensure_address_gap()
        self.assertEqual(len(new_keys), 20)

    @defer.inlineCallbacks
    def test_get_or_create_usable_address(self):
        account = self.account

        keys = yield account.receiving.get_addresses()
        self.assertEqual(len(keys), 0)

        address = yield account.receiving.get_or_create_usable_address()
        self.assertIsNotNone(address)

        keys = yield account.receiving.get_addresses()
        self.assertEqual(len(keys), 20)

    @defer.inlineCallbacks
    def test_generate_account_from_seed(self):
        account = self.ledger.account_class.from_seed(
            self.ledger,
            "carbon smart garage balance margin twelve chest sword toast envelope bottom stomach ab"
            "sent", "torba", receiving_gap=3, change_gap=2
        )
        self.assertEqual(
            account.private_key.extended_key_string(),
            'xprv9s21ZrQH143K2dyhK7SevfRG72bYDRNv25yKPWWm6dqApNxm1Zb1m5gGcBWYfbsPjTr2v5joit8Af2Zp5P'
            '6yz3jMbycrLrRMpeAJxR8qDg8'
        )
        self.assertEqual(
            account.public_key.extended_key_string(),
            'xpub661MyMwAqRbcF84AR8yfHoMzf4S2ct6mPJtvBtvNeyN9hBHuZ6uGJszkTSn5fQUCdz3XU17eBzFeAUwV6f'
            'iW44g14WF52fYC5J483wqQ5ZP'
        )
        address = yield account.receiving.ensure_address_gap()
        self.assertEqual(address[0], '1PmX9T3sCiDysNtWszJa44SkKcpGc2NaXP')

        private_key = yield self.ledger.get_private_key_for_address('1PmX9T3sCiDysNtWszJa44SkKcpGc2NaXP')
        self.assertEqual(
            private_key.extended_key_string(),
            'xprv9xNEfQ296VTRaEUDZ8oKq74xw2U6kpj486vFUB4K1wT9U25GX4UwuzFgJN1YuRrqkQ5TTwCpkYnjNpSoH'
            'SBaEigNHPkoeYbuPMRo6mRUjxg'
        )

        invalid_key = yield self.ledger.get_private_key_for_address('BcQjRlhDOIrQez1WHfz3whnB33Bp34sUgX')
        self.assertIsNone(invalid_key)

        self.assertEqual(
            hexlify(private_key.wif()),
            b'1cc27be89ad47ef932562af80e95085eb0ab2ae3e5c019b1369b8b05ff2e94512f01'
        )

    @defer.inlineCallbacks
    def test_load_and_save_account(self):
        account_data = {
            'name': 'My Account',
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
            'is_hd': True,
            'receiving_gap': 5,
            'receiving_maximum_uses_per_address': 2,
            'change_gap': 5,
            'change_maximum_uses_per_address': 2
        }

        account = self.ledger.account_class.from_dict(self.ledger, account_data)

        yield account.ensure_address_gap()

        addresses = yield account.receiving.get_addresses()
        self.assertEqual(len(addresses), 5)
        addresses = yield account.change.get_addresses()
        self.assertEqual(len(addresses), 5)

        self.maxDiff = None
        account_data['ledger'] = 'btc_mainnet'
        self.assertDictEqual(account_data, account.to_dict())


class TestSingleKeyAccount(unittest.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        self.ledger = MainNetLedger({'db': MainNetLedger.database_class(':memory:')})
        yield self.ledger.db.start()
        self.account = self.ledger.account_class.generate(self.ledger, u"torba", is_hd=False)

    @defer.inlineCallbacks
    def test_generate_account(self):
        account = self.account

        self.assertEqual(account.ledger, self.ledger)
        self.assertIsNotNone(account.seed)
        self.assertEqual(account.public_key.ledger, self.ledger)
        self.assertEqual(account.private_key.public_key, account.public_key)

        addresses = yield account.receiving.get_addresses()
        self.assertEqual(len(addresses), 0)
        addresses = yield account.change.get_addresses()
        self.assertEqual(len(addresses), 0)

        yield account.ensure_address_gap()

        addresses = yield account.receiving.get_addresses()
        self.assertEqual(len(addresses), 1)
        self.assertEqual(addresses[0], account.public_key.address)
        addresses = yield account.change.get_addresses()
        self.assertEqual(len(addresses), 1)
        self.assertEqual(addresses[0], account.public_key.address)

        addresses = yield account.get_addresses()
        self.assertEqual(len(addresses), 1)
        self.assertEqual(addresses[0], account.public_key.address)

    @defer.inlineCallbacks
    def test_ensure_address_gap(self):
        account = self.account

        self.assertIsInstance(account.receiving, SingleKey)
        addresses = yield account.receiving.get_addresses()
        self.assertEqual(addresses, [])

        # we have 12, but default gap is 20
        new_keys = yield account.receiving.ensure_address_gap()
        self.assertEqual(len(new_keys), 1)
        self.assertEqual(new_keys[0], account.public_key.address)
        records = yield account.receiving.get_address_records()
        self.assertEqual(records, [{
            'position': 0, 'address': account.public_key.address, 'used_times': 0
        }])

        # case #1: no new addresses needed
        empty = yield account.receiving.ensure_address_gap()
        self.assertEqual(len(empty), 0)

        # case #2: after use, still no new address needed
        records = yield account.receiving.get_address_records()
        yield self.ledger.db.set_address_history(records[0]['address'], 'a:1:')
        empty = yield account.receiving.ensure_address_gap()
        self.assertEqual(len(empty), 0)

    @defer.inlineCallbacks
    def test_get_or_create_usable_address(self):
        account = self.account

        addresses = yield account.receiving.get_addresses()
        self.assertEqual(len(addresses), 0)

        address1 = yield account.receiving.get_or_create_usable_address()
        self.assertIsNotNone(address1)

        yield self.ledger.db.set_address_history(address1, 'a:1:b:2:c:3:')
        records = yield account.receiving.get_address_records()
        self.assertEqual(records[0]['used_times'], 3)

        address2 = yield account.receiving.get_or_create_usable_address()
        self.assertEqual(address1, address2)

        keys = yield account.receiving.get_addresses()
        self.assertEqual(len(keys), 1)

    @defer.inlineCallbacks
    def test_generate_account_from_seed(self):
        account = self.ledger.account_class.from_seed(
            self.ledger,
            "carbon smart garage balance margin twelve chest sword toast envelope bottom stomach ab"
            "sent", "torba", is_hd=False
        )
        self.assertEqual(
            account.private_key.extended_key_string(),
            'xprv9s21ZrQH143K2dyhK7SevfRG72bYDRNv25yKPWWm6dqApNxm1Zb1m5gGcBWYfbsPjTr2v5joit8Af2Zp5P'
            '6yz3jMbycrLrRMpeAJxR8qDg8'
        )
        self.assertEqual(
            account.public_key.extended_key_string(),
            'xpub661MyMwAqRbcF84AR8yfHoMzf4S2ct6mPJtvBtvNeyN9hBHuZ6uGJszkTSn5fQUCdz3XU17eBzFeAUwV6f'
            'iW44g14WF52fYC5J483wqQ5ZP'
        )
        address = yield account.receiving.ensure_address_gap()
        self.assertEqual(address[0], account.public_key.address)

        private_key = yield self.ledger.get_private_key_for_address(address[0])
        self.assertEqual(
            private_key.extended_key_string(),
            'xprv9s21ZrQH143K2dyhK7SevfRG72bYDRNv25yKPWWm6dqApNxm1Zb1m5gGcBWYfbsPjTr2v5joit8Af2Zp5P'
            '6yz3jMbycrLrRMpeAJxR8qDg8'
        )

        invalid_key = yield self.ledger.get_private_key_for_address('BcQjRlhDOIrQez1WHfz3whnB33Bp34sUgX')
        self.assertIsNone(invalid_key)

        self.assertEqual(
            hexlify(private_key.wif()),
            b'1c2423f3dc6087d9683f73a684935abc0ccd8bc26370588f56653128c6a6f0bf7c01'
        )

    @defer.inlineCallbacks
    def test_load_and_save_account(self):
        account_data = {
            'name': 'My Account',
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
            'is_hd': False
        }

        account = self.ledger.account_class.from_dict(self.ledger, account_data)

        yield account.ensure_address_gap()

        addresses = yield account.receiving.get_addresses()
        self.assertEqual(len(addresses), 1)
        addresses = yield account.change.get_addresses()
        self.assertEqual(len(addresses), 1)

        self.maxDiff = None
        account_data['ledger'] = 'btc_mainnet'
        self.assertDictEqual(account_data, account.to_dict())
