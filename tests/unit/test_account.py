from binascii import hexlify
from twisted.trial import unittest
from twisted.internet import defer

from torba.coin.bitcoinsegwit import MainNetLedger as ledger_class
from torba.baseaccount import HierarchicalDeterministic, SingleKey
from torba.wallet import Wallet


class TestHierarchicalDeterministicAccount(unittest.TestCase):

    @defer.inlineCallbacks
    def setUp(self):
        self.ledger = ledger_class({
            'db': ledger_class.database_class(':memory:'),
            'headers': ledger_class.headers_class(':memory:'),
        })
        yield self.ledger.db.open()
        self.account = self.ledger.account_class.generate(self.ledger, Wallet(), "torba")

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

        self.assertIsInstance(account.receiving, HierarchicalDeterministic)

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
        account = self.ledger.account_class.from_dict(
            self.ledger, Wallet(), {
                "seed": "carbon smart garage balance margin twelve chest sword "
                        "toast envelope bottom stomach absent",
                "address_generator": {
                    'name': 'deterministic-chain',
                    'receiving': {'gap': 3, 'maximum_uses_per_address': 1},
                    'change': {'gap': 2, 'maximum_uses_per_address': 1}
                }
            }
        )
        self.assertEqual(
            account.private_key.extended_key_string(),
            'xprv9s21ZrQH143K3TsAz5efNV8K93g3Ms3FXcjaWB9fVUsMwAoE3ZT4vYymkp5BxK'
            'Kfnpz8J6sHDFriX1SnpvjNkzcks8XBnxjGLS83BTyfpna'
        )
        self.assertEqual(
            account.public_key.extended_key_string(),
            'xpub661MyMwAqRbcFwwe67Bfjd53h5WXmKm6tqfBJZZH3pQLoy8Nb6mKUMJFc7UbpV'
            'NzmwFPN2evn3YHnig1pkKVYcvCV8owTd2yAcEkJfCX53g'
        )
        address = yield account.receiving.ensure_address_gap()
        self.assertEqual(address[0], '1CDLuMfwmPqJiNk5C2Bvew6tpgjAGgUk8J')

        private_key = yield self.ledger.get_private_key_for_address('1CDLuMfwmPqJiNk5C2Bvew6tpgjAGgUk8J')
        self.assertEqual(
            private_key.extended_key_string(),
            'xprv9xV7rhbg6M4yWrdTeLorz3Q1GrQb4aQzzGWboP3du7W7UUztzNTUrEYTnDfz7o'
            'ptBygDxXYRppyiuenJpoBTgYP2C26E1Ah5FEALM24CsWi'
        )

        invalid_key = yield self.ledger.get_private_key_for_address('BcQjRlhDOIrQez1WHfz3whnB33Bp34sUgX')
        self.assertIsNone(invalid_key)

        self.assertEqual(
            hexlify(private_key.wif()),
            b'1c01ae1e4c7d89e39f6d3aa7792c097a30ca7d40be249b6de52c81ec8cf9aab48b01'
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
                'xprv9s21ZrQH143K3TsAz5efNV8K93g3Ms3FXcjaWB9fVUsMwAoE3ZT4vYymkp'
                '5BxKKfnpz8J6sHDFriX1SnpvjNkzcks8XBnxjGLS83BTyfpna',
            'public_key':
                'xpub661MyMwAqRbcFwwe67Bfjd53h5WXmKm6tqfBJZZH3pQLoy8Nb6mKUMJFc7'
                'UbpVNzmwFPN2evn3YHnig1pkKVYcvCV8owTd2yAcEkJfCX53g',
            'address_generator': {
                'name': 'deterministic-chain',
                'receiving': {'gap': 5, 'maximum_uses_per_address': 2},
                'change': {'gap': 5, 'maximum_uses_per_address': 2}
            }
        }

        account = self.ledger.account_class.from_dict(self.ledger, Wallet(), account_data)

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
        self.ledger = ledger_class({
            'db': ledger_class.database_class(':memory:'),
            'headers': ledger_class.headers_class(':memory:'),
        })
        yield self.ledger.db.open()
        self.account = self.ledger.account_class.generate(
            self.ledger, Wallet(), "torba", {'name': 'single-address'})

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
        account = self.ledger.account_class.from_dict(
            self.ledger, Wallet(), {
                "seed":
                    "carbon smart garage balance margin twelve chest sword toas"
                    "t envelope bottom stomach absent",
                'address_generator': {'name': 'single-address'}
            }
        )
        self.assertEqual(
            account.private_key.extended_key_string(),
            'xprv9s21ZrQH143K3TsAz5efNV8K93g3Ms3FXcjaWB9fVUsMwAoE3ZT4vYymkp'
            '5BxKKfnpz8J6sHDFriX1SnpvjNkzcks8XBnxjGLS83BTyfpna',
        )
        self.assertEqual(
            account.public_key.extended_key_string(),
            'xpub661MyMwAqRbcFwwe67Bfjd53h5WXmKm6tqfBJZZH3pQLoy8Nb6mKUMJFc7'
            'UbpVNzmwFPN2evn3YHnig1pkKVYcvCV8owTd2yAcEkJfCX53g',
        )
        address = yield account.receiving.ensure_address_gap()
        self.assertEqual(address[0], account.public_key.address)

        private_key = yield self.ledger.get_private_key_for_address(address[0])
        self.assertEqual(
            private_key.extended_key_string(),
            'xprv9s21ZrQH143K3TsAz5efNV8K93g3Ms3FXcjaWB9fVUsMwAoE3ZT4vYymkp'
            '5BxKKfnpz8J6sHDFriX1SnpvjNkzcks8XBnxjGLS83BTyfpna',
        )

        invalid_key = yield self.ledger.get_private_key_for_address('BcQjRlhDOIrQez1WHfz3whnB33Bp34sUgX')
        self.assertIsNone(invalid_key)

        self.assertEqual(
            hexlify(private_key.wif()),
            b'1c92caa0ef99bfd5e2ceb73b66da8cd726a9370be8c368d448a322f3c5b23aaab901'
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
                'xprv9s21ZrQH143K3TsAz5efNV8K93g3Ms3FXcjaWB9fVUsMwAoE3ZT4vYymkp'
                '5BxKKfnpz8J6sHDFriX1SnpvjNkzcks8XBnxjGLS83BTyfpna',
            'public_key':
                'xpub661MyMwAqRbcFwwe67Bfjd53h5WXmKm6tqfBJZZH3pQLoy8Nb6mKUMJFc7'
                'UbpVNzmwFPN2evn3YHnig1pkKVYcvCV8owTd2yAcEkJfCX53g',
            'address_generator': {'name': 'single-address'}
        }

        account = self.ledger.account_class.from_dict(self.ledger, Wallet(), account_data)

        yield account.ensure_address_gap()

        addresses = yield account.receiving.get_addresses()
        self.assertEqual(len(addresses), 1)
        addresses = yield account.change.get_addresses()
        self.assertEqual(len(addresses), 1)

        self.maxDiff = None
        account_data['ledger'] = 'btc_mainnet'
        self.assertDictEqual(account_data, account.to_dict())


class AccountEncryptionTests(unittest.TestCase):
    password = "password"
    init_vector = b'0000000000000000'
    unencrypted_account = {
            'name': 'My Account',
            'seed':
                "carbon smart garage balance margin twelve chest sword toast envelope bottom stomac"
                "h absent",
            'encrypted': False,
            'private_key':
                'xprv9s21ZrQH143K3TsAz5efNV8K93g3Ms3FXcjaWB9fVUsMwAoE3ZT4vYymkp'
                '5BxKKfnpz8J6sHDFriX1SnpvjNkzcks8XBnxjGLS83BTyfpna',
            'public_key':
                'xpub661MyMwAqRbcFwwe67Bfjd53h5WXmKm6tqfBJZZH3pQLoy8Nb6mKUMJFc7'
                'UbpVNzmwFPN2evn3YHnig1pkKVYcvCV8owTd2yAcEkJfCX53g',
            'address_generator': {'name': 'single-address'}
    }
    encrypted_account = {
            'name': 'My Account',
            'seed':
                "MDAwMDAwMDAwMDAwMDAwMJ4e4W4pE6nQtPiD6MujNIQ7aFPhUBl63GwPziAgGN"
                "MBTMoaSjZfyyvw7ELMCqAYTWJ61aV7K4lmd2hR11g9dpdnnpCb9f9j3zLZHRv7+"
                "bIkZ//trah9AIkmrc/ZvNkC0Q==",
            'encrypted': True,
            'private_key':
                'MDAwMDAwMDAwMDAwMDAwMLkWikOLScA/ZxlFSGU7dl//7Q/1gS9h7vqQyrd8DX+'
                'jwcp7SwlJ1mkMwuraUaWLq9/LxiaGmqJBUZ50p77YVZbDycaCN1unBr1/i1q6RP'
                'Ob2MNCaG8nyjxZhQai+V/2JmJ+UnFMp3nHany7F8/Hr0g=',
            'public_key':
                'xpub661MyMwAqRbcFwwe67Bfjd53h5WXmKm6tqfBJZZH3pQLoy8Nb6mKUMJFc7'
                'UbpVNzmwFPN2evn3YHnig1pkKVYcvCV8owTd2yAcEkJfCX53g',
            'address_generator': {'name': 'single-address'}
    }

    def setUp(self):
        self.ledger = ledger_class({
            'db': ledger_class.database_class(':memory:'),
            'headers': ledger_class.headers_class(':memory:'),
        })

    def test_encrypt_wallet(self):
        account = self.ledger.account_class.from_dict(self.ledger, Wallet(), self.unencrypted_account)
        account.encryption_init_vector = self.init_vector

        self.assertFalse(account.serialize_encrypted)
        self.assertFalse(account.encrypted)
        self.assertIsNotNone(account.private_key)
        account.encrypt(self.password)
        self.assertFalse(account.serialize_encrypted)
        self.assertTrue(account.encrypted)
        self.assertEqual(account.seed, self.encrypted_account['seed'])
        self.assertEqual(account.private_key_string, self.encrypted_account['private_key'])
        self.assertIsNone(account.private_key)

        self.assertEqual(account.to_dict()['seed'], self.encrypted_account['seed'])
        self.assertEqual(account.to_dict()['private_key'], self.encrypted_account['private_key'])

        account.serialize_encrypted = True
        account.decrypt(self.password)

        self.assertEqual(account.seed, self.unencrypted_account['seed'])
        self.assertEqual(account.private_key.extended_key_string(), self.unencrypted_account['private_key'])

        self.assertEqual(account.to_dict()['seed'], self.encrypted_account['seed'])
        self.assertEqual(account.to_dict()['private_key'], self.encrypted_account['private_key'])

        account.encryption_init_vector = None
        self.assertNotEqual(account.to_dict()['seed'], self.encrypted_account['seed'])
        self.assertNotEqual(account.to_dict()['private_key'], self.encrypted_account['private_key'])

        self.assertFalse(account.encrypted)
        self.assertTrue(account.serialize_encrypted)

    def test_decrypt_wallet(self):
        account = self.ledger.account_class.from_dict(self.ledger, Wallet(), self.encrypted_account)
        account.encryption_init_vector = self.init_vector

        self.assertTrue(account.encrypted)
        self.assertTrue(account.serialize_encrypted)
        account.decrypt(self.password)
        self.assertFalse(account.encrypted)
        self.assertTrue(account.serialize_encrypted)

        self.assertEqual(account.seed, self.unencrypted_account['seed'])
        self.assertEqual(account.private_key.extended_key_string(), self.unencrypted_account['private_key'])

        self.assertEqual(account.to_dict()['seed'], self.encrypted_account['seed'])
        self.assertEqual(account.to_dict()['private_key'], self.encrypted_account['private_key'])

        account.serialize_encrypted = False
        self.assertEqual(account.to_dict()['seed'], self.unencrypted_account['seed'])
        self.assertEqual(account.to_dict()['private_key'], self.unencrypted_account['private_key'])
