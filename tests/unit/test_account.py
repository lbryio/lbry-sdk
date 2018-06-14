from binascii import hexlify
from twisted.trial import unittest
from twisted.internet import defer

from torba.coin.bitcoinsegwit import MainNetLedger


class TestKeyChain(unittest.TestCase):

    def setUp(self):
        self.ledger = MainNetLedger(db=':memory:')
        return self.ledger.db.start()

    @defer.inlineCallbacks
    def test_address_gap_algorithm(self):
        account = self.ledger.account_class.generate(self.ledger, u"torba")

        # save records out of order to make sure we're really testing ORDER BY
        # and not coincidentally getting records in the correct order
        yield account.receiving.generate_keys(4, 7)
        yield account.receiving.generate_keys(0, 3)
        yield account.receiving.generate_keys(8, 11)
        keys = yield account.receiving.get_addresses(None, True)
        self.assertEqual(
            [key['position'] for key in keys],
            [11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
        )

        # we have 12, but default gap is 20
        new_keys = yield account.receiving.ensure_address_gap()
        self.assertEqual(len(new_keys), 8)
        keys = yield account.receiving.get_addresses(None, True)
        self.assertEqual(
            [key['position'] for key in keys],
            [19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
        )

        # case #1: no new addresses needed
        empty = yield account.receiving.ensure_address_gap()
        self.assertEqual(len(empty), 0)

        # case #2: only one new addressed needed
        keys = yield account.receiving.get_addresses(None, True)
        yield self.ledger.db.set_address_history(keys[19]['address'], b'a:1:')
        new_keys = yield account.receiving.ensure_address_gap()
        self.assertEqual(len(new_keys), 1)

        # case #3: 20 addresses needed
        keys = yield account.receiving.get_addresses(None, True)
        yield self.ledger.db.set_address_history(keys[0]['address'], b'a:1:')
        new_keys = yield account.receiving.ensure_address_gap()
        self.assertEqual(len(new_keys), 20)

    @defer.inlineCallbacks
    def test_create_usable_address(self):
        account = self.ledger.account_class.generate(self.ledger, u"torba")

        keys = yield account.receiving.get_addresses(None, True)
        self.assertEqual(len(keys), 0)

        address = yield account.receiving.get_or_create_usable_address()
        self.assertIsNotNone(address)

        keys = yield account.receiving.get_addresses(None, True)
        self.assertEqual(len(keys), 20)


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
        address = yield account.receiving.ensure_address_gap()
        self.assertEqual(address[0], b'1PmX9T3sCiDysNtWszJa44SkKcpGc2NaXP')

        self.maxDiff = None
        private_key = yield self.ledger.get_private_key_for_address(b'1PmX9T3sCiDysNtWszJa44SkKcpGc2NaXP')
        self.assertEqual(
            private_key.extended_key_string(),
            b'xprv9xNEfQ296VTRaEUDZ8oKq74xw2U6kpj486vFUB4K1wT9U25GX4UwuzFgJN1YuRrqkQ5TTwCpkYnjNpSoH'
            b'SBaEigNHPkoeYbuPMRo6mRUjxg'
        )

        invalid_key = yield self.ledger.get_private_key_for_address(b'BcQjRlhDOIrQez1WHfz3whnB33Bp34sUgX')
        self.assertIsNone(invalid_key)

        self.assertEqual(
            hexlify(private_key.wif()),
            b'1cc27be89ad47ef932562af80e95085eb0ab2ae3e5c019b1369b8b05ff2e94512f01'
        )

    @defer.inlineCallbacks
    def test_load_and_save_account(self):
        account_data = {
            'seed':
                "carbon smart garage balance margin twelve chest sword toast envelope bottom stomac"
                "h absent",
            'encrypted': False,
            'private_key':
                b'xprv9s21ZrQH143K2dyhK7SevfRG72bYDRNv25yKPWWm6dqApNxm1Zb1m5gGcBWYfbsPjTr2v5joit8Af2Zp5P'
                b'6yz3jMbycrLrRMpeAJxR8qDg8',
            'public_key':
                b'xpub661MyMwAqRbcF84AR8yfHoMzf4S2ct6mPJtvBtvNeyN9hBHuZ6uGJszkTSn5fQUCdz3XU17eBzFeAUwV6f'
                b'iW44g14WF52fYC5J483wqQ5ZP',
            'receiving_gap': 10,
            'receiving_maximum_use_per_address': 2,
            'change_gap': 10,
            'change_maximum_use_per_address': 2
        }

        account = self.ledger.account_class.from_dict(self.ledger, account_data)

        yield account.ensure_address_gap()

        addresses = yield account.receiving.get_addresses()
        self.assertEqual(len(addresses), 10)
        addresses = yield account.change.get_addresses()
        self.assertEqual(len(addresses), 10)

        self.maxDiff = None
        account_data['ledger'] = 'btc_mainnet'
        self.assertDictEqual(account_data, account.to_dict())
