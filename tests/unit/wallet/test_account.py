import asyncio
from binascii import hexlify
from lbry.testcase import AsyncioTestCase
from lbry.wallet import Wallet, Ledger, Database, Headers, Account, SingleKey, HierarchicalDeterministic


class TestAccount(AsyncioTestCase):

    async def asyncSetUp(self):
        self.ledger = Ledger({
            'db': Database(':memory:'),
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

    async def test_unused_address_on_account_creation_does_not_cause_a_race(self):
        account = Account.generate(self.ledger, Wallet(), 'lbryum')
        await account.ledger.db.db.executescript("update pubkey_address set used_times=10")
        await account.receiving.address_generator_lock.acquire()
        delayed1 = asyncio.ensure_future(account.receiving.ensure_address_gap())
        delayed = asyncio.ensure_future(account.receiving.get_or_create_usable_address())
        await asyncio.sleep(0)
        # wallet being created and queried at the same time
        account.receiving.address_generator_lock.release()
        await delayed1
        await delayed

    async def test_generate_keys_over_batch_threshold_saves_it_properly(self):
        account = Account.generate(self.ledger, Wallet(), 'lbryum')
        async with account.receiving.address_generator_lock:
            await account.receiving._generate_keys(0, 200)
        records = await account.receiving.get_address_records()
        self.assertEqual(len(records), 201)

    async def test_ensure_address_gap(self):
        account = Account.generate(self.ledger, Wallet(), 'lbryum')

        self.assertIsInstance(account.receiving, HierarchicalDeterministic)

        async with account.receiving.address_generator_lock:
            await account.receiving._generate_keys(4, 7)
            await account.receiving._generate_keys(0, 3)
            await account.receiving._generate_keys(8, 11)
        records = await account.receiving.get_address_records()
        self.assertListEqual(
            [r['pubkey'].n for r in records],
            [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        )

        # we have 12, but default gap is 20
        new_keys = await account.receiving.ensure_address_gap()
        self.assertEqual(len(new_keys), 8)
        records = await account.receiving.get_address_records()
        self.assertListEqual(
            [r['pubkey'].n for r in records],
            [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
        )

        # case #1: no new addresses needed
        empty = await account.receiving.ensure_address_gap()
        self.assertEqual(len(empty), 0)

        # case #2: only one new addressed needed
        records = await account.receiving.get_address_records()
        await self.ledger.db.set_address_history(records[0]['address'], 'a:1:')
        new_keys = await account.receiving.ensure_address_gap()
        self.assertEqual(len(new_keys), 1)

        # case #3: 20 addresses needed
        await self.ledger.db.set_address_history(new_keys[0], 'a:1:')
        new_keys = await account.receiving.ensure_address_gap()
        self.assertEqual(len(new_keys), 20)

    async def test_get_or_create_usable_address(self):
        account = Account.generate(self.ledger, Wallet(), 'lbryum')

        keys = await account.receiving.get_addresses()
        self.assertEqual(len(keys), 0)

        address = await account.receiving.get_or_create_usable_address()
        self.assertIsNotNone(address)

        keys = await account.receiving.get_addresses()
        self.assertEqual(len(keys), 20)

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

        private_key = await self.ledger.get_private_key_for_address(
            account.wallet, 'bCqJrLHdoiRqEZ1whFZ3WHNb33bP34SuGx'
        )
        self.assertEqual(
            private_key.extended_key_string(),
            'xprv9vwXVierUTT4hmoe3dtTeBfbNv1ph2mm8RWXARU6HsZjBaAoFaS2FRQu4fptR'
            'AyJWhJW42dmsEaC1nKnVKKTMhq3TVEHsNj1ca3ciZMKktT'
        )
        private_key = await self.ledger.get_private_key_for_address(
            account.wallet, 'BcQjRlhDOIrQez1WHfz3whnB33Bp34sUgX'
        )
        self.assertIsNone(private_key)

    async def test_load_and_save_account(self):
        account_data = {
            'name': 'Main Account',
            'modified_on': 123,
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

        await account.ensure_address_gap()

        addresses = await account.receiving.get_addresses()
        self.assertEqual(len(addresses), 17)
        addresses = await account.change.get_addresses()
        self.assertEqual(len(addresses), 10)

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

    def test_merge_diff(self):
        account_data = {
            'name': 'My Account',
            'modified_on': 123,
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
        account = Account.from_dict(self.ledger, Wallet(), account_data)

        self.assertEqual(account.name, 'My Account')
        self.assertEqual(account.modified_on, 123)
        self.assertEqual(account.change.gap, 5)
        self.assertEqual(account.change.maximum_uses_per_address, 2)
        self.assertEqual(account.receiving.gap, 5)
        self.assertEqual(account.receiving.maximum_uses_per_address, 2)

        account_data['name'] = 'Changed Name'
        account_data['address_generator']['change']['gap'] = 6
        account_data['address_generator']['change']['maximum_uses_per_address'] = 7
        account_data['address_generator']['receiving']['gap'] = 8
        account_data['address_generator']['receiving']['maximum_uses_per_address'] = 9

        account.merge(account_data)
        # no change because modified_on is not newer
        self.assertEqual(account.name, 'My Account')

        account_data['modified_on'] = 200.00

        account.merge(account_data)
        self.assertEqual(account.name, 'Changed Name')
        self.assertEqual(account.change.gap, 6)
        self.assertEqual(account.change.maximum_uses_per_address, 7)
        self.assertEqual(account.receiving.gap, 8)
        self.assertEqual(account.receiving.maximum_uses_per_address, 9)


class TestSingleKeyAccount(AsyncioTestCase):

    async def asyncSetUp(self):
        self.ledger = Ledger({
            'db': Database(':memory:'),
            'headers': Headers(':memory:')
        })
        await self.ledger.db.open()
        self.account = Account.generate(self.ledger, Wallet(), "torba", {'name': 'single-address'})

    async def asyncTearDown(self):
        await self.ledger.db.close()

    async def test_generate_account(self):
        account = self.account

        self.assertEqual(account.ledger, self.ledger)
        self.assertIsNotNone(account.seed)
        self.assertEqual(account.public_key.ledger, self.ledger)
        self.assertEqual(account.private_key.public_key, account.public_key)

        addresses = await account.receiving.get_addresses()
        self.assertEqual(len(addresses), 0)
        addresses = await account.change.get_addresses()
        self.assertEqual(len(addresses), 0)

        await account.ensure_address_gap()

        addresses = await account.receiving.get_addresses()
        self.assertEqual(len(addresses), 1)
        self.assertEqual(addresses[0], account.public_key.address)
        addresses = await account.change.get_addresses()
        self.assertEqual(len(addresses), 1)
        self.assertEqual(addresses[0], account.public_key.address)

        addresses = await account.get_addresses()
        self.assertEqual(len(addresses), 1)
        self.assertEqual(addresses[0], account.public_key.address)

    async def test_ensure_address_gap(self):
        account = self.account

        self.assertIsInstance(account.receiving, SingleKey)
        addresses = await account.receiving.get_addresses()
        self.assertListEqual(addresses, [])

        # we have 12, but default gap is 20
        new_keys = await account.receiving.ensure_address_gap()
        self.assertEqual(len(new_keys), 1)
        self.assertEqual(new_keys[0], account.public_key.address)
        records = await account.receiving.get_address_records()
        pubkey = records[0].pop('pubkey')
        self.assertListEqual(records, [{
            'chain': 0,
            'account': account.public_key.address,
            'address': account.public_key.address,
            'history': None,
            'used_times': 0
        }])
        self.assertEqual(
            pubkey.extended_key_string(),
            account.public_key.extended_key_string()
        )

        # case #1: no new addresses needed
        empty = await account.receiving.ensure_address_gap()
        self.assertEqual(len(empty), 0)

        # case #2: after use, still no new address needed
        records = await account.receiving.get_address_records()
        await self.ledger.db.set_address_history(records[0]['address'], 'a:1:')
        empty = await account.receiving.ensure_address_gap()
        self.assertEqual(len(empty), 0)

    async def test_get_or_create_usable_address(self):
        account = self.account

        addresses = await account.receiving.get_addresses()
        self.assertEqual(len(addresses), 0)

        address1 = await account.receiving.get_or_create_usable_address()
        self.assertIsNotNone(address1)

        await self.ledger.db.set_address_history(address1, 'a:1:b:2:c:3:')
        records = await account.receiving.get_address_records()
        self.assertEqual(records[0]['used_times'], 3)

        address2 = await account.receiving.get_or_create_usable_address()
        self.assertEqual(address1, address2)

        keys = await account.receiving.get_addresses()
        self.assertEqual(len(keys), 1)

    async def test_generate_account_from_seed(self):
        account = Account.from_dict(
            self.ledger, Wallet(), {
                "seed":
                    "carbon smart garage balance margin twelve chest sword toas"
                    "t envelope bottom stomach absent",
                'address_generator': {'name': 'single-address'}
            }
        )
        self.assertEqual(
            account.private_key.extended_key_string(),
            'xprv9s21ZrQH143K42ovpZygnjfHdAqSd9jo7zceDfPRogM7bkkoNVv7'
            'DRNLEoB8HoirMgH969NrgL8jNzLEegqFzPRWM37GXd4uE8uuRkx4LAe',
        )
        self.assertEqual(
            account.public_key.extended_key_string(),
            'xpub661MyMwAqRbcGWtPvbWh9sc2BCfw2cTeVDYF23o3N1t6UZ5wv3EM'
            'mDgp66FxHuDtWdft3B5eL5xQtyzAtkdmhhC95gjRjLzSTdkho95asu9',
        )
        address = await account.receiving.ensure_address_gap()
        self.assertEqual(address[0], account.public_key.address)

        private_key = await self.ledger.get_private_key_for_address(
            account.wallet, address[0]
        )
        self.assertEqual(
            private_key.extended_key_string(),
            'xprv9s21ZrQH143K42ovpZygnjfHdAqSd9jo7zceDfPRogM7bkkoNVv7'
            'DRNLEoB8HoirMgH969NrgL8jNzLEegqFzPRWM37GXd4uE8uuRkx4LAe',
        )

        invalid_key = await self.ledger.get_private_key_for_address(
            account.wallet, 'BcQjRlhDOIrQez1WHfz3whnB33Bp34sUgX'
        )
        self.assertIsNone(invalid_key)

        self.assertEqual(
            hexlify(private_key.wif()),
            b'1cef6c80310b1bcbcfa3176ea809ac840f48cda634c475d402e6bd68d5bb3827d601'
        )

    async def test_load_and_save_account(self):
        account_data = {
            'name': 'My Account',
            'modified_on': 123,
            'seed':
                "carbon smart garage balance margin twelve chest sword toast envelope bottom stomac"
                "h absent",
            'encrypted': False,
            'private_key': 'xprv9s21ZrQH143K42ovpZygnjfHdAqSd9jo7zceDfPRogM7bkkoNVv7'
                           'DRNLEoB8HoirMgH969NrgL8jNzLEegqFzPRWM37GXd4uE8uuRkx4LAe',
            'public_key': 'xpub661MyMwAqRbcGWtPvbWh9sc2BCfw2cTeVDYF23o3N1t6UZ5wv3EM'
                          'mDgp66FxHuDtWdft3B5eL5xQtyzAtkdmhhC95gjRjLzSTdkho95asu9',
            'address_generator': {'name': 'single-address'},
            'certificates': {}
        }

        account = Account.from_dict(self.ledger, Wallet(), account_data)

        await account.ensure_address_gap()

        addresses = await account.receiving.get_addresses()
        self.assertEqual(len(addresses), 1)
        addresses = await account.change.get_addresses()
        self.assertEqual(len(addresses), 1)

        self.maxDiff = None
        account_data['ledger'] = 'lbc_mainnet'
        self.assertDictEqual(account_data, account.to_dict())


class AccountEncryptionTests(AsyncioTestCase):
    password = "password"
    init_vector = b'0000000000000000'
    unencrypted_account = {
        'name': 'My Account',
        'seed':
            "carbon smart garage balance margin twelve chest sword toast envelope bottom stomac"
            "h absent",
        'encrypted': False,
        'private_key':
            'xprv9s21ZrQH143K42ovpZygnjfHdAqSd9jo7zceDfPRogM7bkkoNVv7DRNLEo'
            'B8HoirMgH969NrgL8jNzLEegqFzPRWM37GXd4uE8uuRkx4LAe',
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
            'MDAwMDAwMDAwMDAwMDAwMLkWikOLScA/ZxlFSGU7dl8pqVjgdpu1S3MWQF3IJ5H'
            'OXPAQcgnhHldVq98uP7Q8JqSWOv1p4gpxGSYnA4w5Gbuh0aUD4hmV70m7nVTj7T'
            '15+Pu30DCspndru59pee/S+mShoK68q7t7r32leaVIfzw=',
        'public_key':
            'xpub661MyMwAqRbcFwwe67Bfjd53h5WXmKm6tqfBJZZH3pQLoy8Nb6mKUMJFc7'
            'UbpVNzmwFPN2evn3YHnig1pkKVYcvCV8owTd2yAcEkJfCX53g',
        'address_generator': {'name': 'single-address'}
    }

    async def asyncSetUp(self):
        self.ledger = Ledger({
            'db': Database(':memory:'),
            'headers': Headers(':memory:')
        })

    def test_encrypt_wallet(self):
        account = Account.from_dict(self.ledger, Wallet(), self.unencrypted_account)
        account.init_vectors = {
            'seed': self.init_vector,
            'private_key': self.init_vector
        }

        self.assertFalse(account.encrypted)
        self.assertIsNotNone(account.private_key)
        account.encrypt(self.password)
        self.assertTrue(account.encrypted)
        self.assertEqual(account.seed, self.encrypted_account['seed'])
        self.assertEqual(account.private_key_string, self.encrypted_account['private_key'])
        self.assertIsNone(account.private_key)

        self.assertEqual(account.to_dict()['seed'], self.encrypted_account['seed'])
        self.assertEqual(account.to_dict()['private_key'], self.encrypted_account['private_key'])

        account.decrypt(self.password)
        self.assertEqual(account.init_vectors['private_key'], self.init_vector)
        self.assertEqual(account.init_vectors['seed'], self.init_vector)

        self.assertEqual(account.seed, self.unencrypted_account['seed'])
        self.assertEqual(account.private_key.extended_key_string(), self.unencrypted_account['private_key'])

        self.assertEqual(account.to_dict(encrypt_password=self.password)['seed'], self.encrypted_account['seed'])
        self.assertEqual(account.to_dict(encrypt_password=self.password)['private_key'], self.encrypted_account['private_key'])

        self.assertFalse(account.encrypted)

    def test_decrypt_wallet(self):
        account = Account.from_dict(self.ledger, Wallet(), self.encrypted_account)

        self.assertTrue(account.encrypted)
        account.decrypt(self.password)
        self.assertEqual(account.init_vectors['private_key'], self.init_vector)
        self.assertEqual(account.init_vectors['seed'], self.init_vector)

        self.assertFalse(account.encrypted)

        self.assertEqual(account.seed, self.unencrypted_account['seed'])
        self.assertEqual(account.private_key.extended_key_string(), self.unencrypted_account['private_key'])

        self.assertEqual(account.to_dict(encrypt_password=self.password)['seed'], self.encrypted_account['seed'])
        self.assertEqual(account.to_dict(encrypt_password=self.password)['private_key'], self.encrypted_account['private_key'])
        self.assertEqual(account.to_dict()['seed'], self.unencrypted_account['seed'])
        self.assertEqual(account.to_dict()['private_key'], self.unencrypted_account['private_key'])

    def test_encrypt_decrypt_read_only_account(self):
        account_data = self.unencrypted_account.copy()
        del account_data['seed']
        del account_data['private_key']
        account = Account.from_dict(self.ledger, Wallet(), account_data)
        encrypted = account.to_dict('password')
        self.assertFalse(encrypted['seed'])
        self.assertFalse(encrypted['private_key'])
        account.encrypt('password')
        account.decrypt('password')
