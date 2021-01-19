from itertools import cycle
from binascii import hexlify
from unittest import TestCase, mock

from lbry import Config, Database, Ledger, Account, Wallet, Transaction, Output, Input
from lbry.testcase import AsyncioTestCase, get_output, COIN, CENT
from lbry.wallet.preferences import TimestampedPreferences


class WalletTestCase(AsyncioTestCase):

    async def asyncSetUp(self):
        self.ledger = Ledger(Config.with_null_dir().set(db_url='sqlite:///:memory:'))
        self.db = Database(self.ledger)
        await self.db.open()
        self.addCleanup(self.db.close)


class WalletAccountTest(WalletTestCase):

    async def test_private_key_for_hierarchical_account(self):
        wallet = Wallet("wallet1", self.db)
        account = await wallet.accounts.add_from_dict({
            "seed":
                "carbon smart garage balance margin twelve chest sword toas"
                "t envelope bottom stomach absent"
        })
        await account.receiving.ensure_address_gap()
        private_key = await wallet.get_private_key_for_address(
            'bCqJrLHdoiRqEZ1whFZ3WHNb33bP34SuGx'
        )
        self.assertEqual(
            private_key.extended_key_string(),
            'xprv9vwXVierUTT4hmoe3dtTeBfbNv1ph2mm8RWXARU6HsZjBaAoFaS2FRQu4fptR'
            'AyJWhJW42dmsEaC1nKnVKKTMhq3TVEHsNj1ca3ciZMKktT'
        )
        self.assertIsNone(
            await wallet.get_private_key_for_address('BcQjRlhDOIrQez1WHfz3whnB33Bp34sUgX')
        )

    async def test_private_key_for_single_address_account(self):
        wallet = Wallet("wallet1", self.db)
        account = await wallet.accounts.add_from_dict({
            "seed":
                "carbon smart garage balance margin twelve chest sword toas"
                "t envelope bottom stomach absent",
            'address_generator': {'name': 'single-address'}
        })
        address = await account.receiving.ensure_address_gap()
        private_key = await wallet.get_private_key_for_address(address[0])
        self.assertEqual(
            private_key.extended_key_string(),
            'xprv9s21ZrQH143K42ovpZygnjfHdAqSd9jo7zceDfPRogM7bkkoNVv7'
            'DRNLEoB8HoirMgH969NrgL8jNzLEegqFzPRWM37GXd4uE8uuRkx4LAe',
        )
        self.assertIsNone(
            await wallet.get_private_key_for_address('BcQjRlhDOIrQez1WHfz3whnB33Bp34sUgX')
        )

    async def test_save_max_gap(self):
        wallet = Wallet("wallet1", self.db)
        account = await wallet.accounts.generate(
            address_generator={
                'name': 'deterministic-chain',
                'receiving': {'gap': 3, 'maximum_uses_per_address': 2},
                'change': {'gap': 4, 'maximum_uses_per_address': 2}
            }
        )
        self.assertEqual(account.receiving.gap, 3)
        self.assertEqual(account.change.gap, 4)
        await wallet.save_max_gap()
        self.assertEqual(account.receiving.gap, 20)
        self.assertEqual(account.change.gap, 6)
        # doesn't fail for single-address account
        await wallet.accounts.generate(address_generator={'name': 'single-address'})
        await wallet.save_max_gap()


class TestWalletCreation(WalletTestCase):

    async def test_create_wallet_and_accounts(self):
        wallet = Wallet("wallet1", self.db)
        self.assertEqual(wallet.id, "wallet1")
        self.assertEqual(wallet.name, "")
        self.assertEqual(list(wallet.accounts), [])

        account1 = await wallet.accounts.generate()
        await wallet.accounts.generate()
        await wallet.accounts.generate()
        self.assertEqual(wallet.accounts.default, account1)
        self.assertEqual(len(wallet.accounts), 3)

    async def test_load_and_save_wallet(self):
        wallet_dict = {
            'version': 1,
            'name': 'Main Wallet',
            'ledger': 'lbc_mainnet',
            'preferences': {},
            'accounts': [
                {
                    'certificates': {},
                    'name': 'An Account',
                    'modified_on': 123.456,
                    'seed':
                        "carbon smart garage balance margin twelve chest sword toast envelope bottom stomac"
                        "h absent",
                    'encrypted': False,
                    'lang': 'en',
                    'private_key':
                        'xprv9s21ZrQH143K42ovpZygnjfHdAqSd9jo7zceDfPRogM7bkkoNVv7'
                        'DRNLEoB8HoirMgH969NrgL8jNzLEegqFzPRWM37GXd4uE8uuRkx4LAe',
                    'public_key':
                        'xpub661MyMwAqRbcGWtPvbWh9sc2BCfw2cTeVDYF23o3N1t6UZ5wv3EMm'
                        'Dgp66FxHuDtWdft3B5eL5xQtyzAtkdmhhC95gjRjLzSTdkho95asu9',
                    'address_generator': {
                        'name': 'deterministic-chain',
                        'receiving': {'gap': 17, 'maximum_uses_per_address': 3},
                        'change': {'gap': 10, 'maximum_uses_per_address': 3}
                    }
                }
            ]
        }

        wallet = await Wallet.from_dict('wallet1', wallet_dict, self.db)
        self.assertEqual(wallet.name, 'Main Wallet')
        self.assertEqual(
            hexlify(wallet.hash),
            b'64a32cf8434a59c547abf61b4691a8189ac24272678b52ced2310fbf93eac974'
        )
        self.assertEqual(len(wallet.accounts), 1)
        account = wallet.accounts.default
        self.assertIsInstance(account, Account)
        self.maxDiff = None
        self.assertDictEqual(wallet_dict, wallet.to_dict())

        encrypted = wallet.pack('password')
        decrypted = Wallet.unpack('password', encrypted)
        self.assertEqual(decrypted['accounts'][0]['name'], 'An Account')

    async def test_merge(self):
        wallet1 = Wallet('wallet1', self.db)
        wallet1.preferences['one'] = 1
        wallet1.preferences['conflict'] = 1
        await wallet1.accounts.generate()
        wallet2 = Wallet('wallet2', self.db)
        wallet2.preferences['two'] = 2
        wallet2.preferences['conflict'] = 2  # will be more recent
        await wallet2.accounts.generate()

        self.assertEqual(len(wallet1.accounts), 1)
        self.assertEqual(wallet1.preferences, {'one': 1, 'conflict': 1})

        added = await wallet1.merge('password', wallet2.pack('password'))
        self.assertEqual(added[0].id, wallet2.accounts.default.id)
        self.assertEqual(len(wallet1.accounts), 2)
        self.assertEqual(list(wallet1.accounts)[1].id, wallet2.accounts.default.id)
        self.assertEqual(wallet1.preferences, {'one': 1, 'two': 2, 'conflict': 2})


class TestTimestampedPreferences(TestCase):

    def test_init(self):
        p = TimestampedPreferences()
        p['one'] = 1
        p2 = TimestampedPreferences(p.data)
        self.assertEqual(p2['one'], 1)

    def test_hash(self):
        p = TimestampedPreferences()
        self.assertEqual(
            hexlify(p.hash), b'44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a'
        )
        with mock.patch('time.time', mock.Mock(return_value=12345)):
            p['one'] = 1
        self.assertEqual(
            hexlify(p.hash), b'c9e82bf4cb099dd0125f78fa381b21a8131af601917eb531e1f5f980f8f3da66'
        )

    def test_merge(self):
        p1 = TimestampedPreferences()
        p2 = TimestampedPreferences()
        with mock.patch('time.time', mock.Mock(return_value=10)):
            p1['one'] = 1
            p1['conflict'] = 1
        with mock.patch('time.time', mock.Mock(return_value=20)):
            p2['two'] = 2
            p2['conflict'] = 2

        # conflict in p2 overrides conflict in p1
        p1.merge(p2.data)
        self.assertEqual(p1, {'one': 1, 'two': 2, 'conflict': 2})

        # have a newer conflict in p1 so it is not overridden this time
        with mock.patch('time.time', mock.Mock(return_value=21)):
            p1['conflict'] = 1
        p1.merge(p2.data)
        self.assertEqual(p1, {'one': 1, 'two': 2, 'conflict': 1})


class TestTransactionSigning(WalletTestCase):

    async def test_sign(self):
        wallet = Wallet('wallet1', self.db)
        account = await wallet.accounts.add_from_dict({
            "seed":
                "carbon smart garage balance margin twelve chest sword toas"
                "t envelope bottom stomach absent"
        })

        await account.ensure_address_gap()
        address1, address2 = await account.receiving.get_addresses(limit=2)
        pubkey_hash1 = self.ledger.address_to_hash160(address1)
        pubkey_hash2 = self.ledger.address_to_hash160(address2)

        tx = Transaction() \
            .add_inputs([Input.spend(get_output(int(2*COIN), pubkey_hash1))]) \
            .add_outputs([Output.pay_pubkey_hash(int(1.9*COIN), pubkey_hash2)])

        await wallet.sign(tx)

        self.assertEqual(
            hexlify(tx.inputs[0].script.values['signature']),
            b'304402200dafa26ad7cf38c5a971c8a25ce7d85a076235f146126762296b1223c42ae21e022020ef9eeb8'
            b'398327891008c5c0be4357683f12cb22346691ff23914f457bf679601'
        )


class TransactionIOBalancing(WalletTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.wallet = Wallet('wallet1', self.db)
        self.account = await self.wallet.accounts.add_from_dict({
            "seed":
                "carbon smart garage balance margin twelve chest sword toas"
                "t envelope bottom stomach absent"
        })
        addresses = await self.account.ensure_address_gap()
        self.pubkey_hash = [self.ledger.address_to_hash160(a) for a in addresses]
        self.hash_cycler = cycle(self.pubkey_hash)

    def txo(self, amount, address=None):
        return get_output(int(amount*COIN), address or next(self.hash_cycler))

    def txi(self, txo):
        return Input.spend(txo)

    def tx(self, inputs, outputs):
        return self.wallet.create_transaction(inputs, outputs, [self.account], self.account)

    async def create_utxos(self, amounts):
        utxos = [self.txo(amount) for amount in amounts]

        self.funding_tx = Transaction(is_verified=True) \
            .add_inputs([self.txi(self.txo(sum(amounts)+0.1))]) \
            .add_outputs(utxos)

        await self.db.insert_transactions([(b'beef', self.funding_tx)])

        return utxos

    @staticmethod
    def inputs(tx):
        return [round(i.amount/COIN, 2) for i in tx.inputs]

    @staticmethod
    def outputs(tx):
        return [round(o.amount/COIN, 2) for o in tx.outputs]

    async def test_basic_use_cases(self):
        self.ledger.fee_per_byte = int(.01*CENT)

        # available UTXOs for filling missing inputs
        utxos = await self.create_utxos([
            1, 1, 3, 5, 10
        ])

        # pay 3 coins (3.02 w/ fees)
        tx = await self.tx(
            [],            # inputs
            [self.txo(3)]  # outputs
        )
        # best UTXO match is 5 (as UTXO 3 will be short 0.02 to cover fees)
        self.assertListEqual(self.inputs(tx), [5])
        # a change of 1.98 is added to reach balance
        self.assertListEqual(self.outputs(tx), [3, 1.98])

        await self.db.release_outputs(utxos)

        # pay 2.98 coins (3.00 w/ fees)
        tx = await self.tx(
            [],               # inputs
            [self.txo(2.98)]  # outputs
        )
        # best UTXO match is 3 and no change is needed
        self.assertListEqual(self.inputs(tx), [3])
        self.assertListEqual(self.outputs(tx), [2.98])

        await self.db.release_outputs(utxos)

        # supplied input and output, but input is not enough to cover output
        tx = await self.tx(
            [self.txi(self.txo(10))],  # inputs
            [self.txo(11)]             # outputs
        )
        # additional input is chosen (UTXO 3)
        self.assertListEqual([10, 3], self.inputs(tx))
        # change is now needed to consume extra input
        self.assertListEqual([11, 1.96], self.outputs(tx))

        await self.db.release_outputs(utxos)

        # liquidating a UTXO
        tx = await self.tx(
            [self.txi(self.txo(10))],  # inputs
            []                         # outputs
        )
        self.assertListEqual([10], self.inputs(tx))
        # missing change added to consume the amount
        self.assertListEqual([9.98], self.outputs(tx))

        await self.db.release_outputs(utxos)

        # liquidating at a loss, requires adding extra inputs
        tx = await self.tx(
            [self.txi(self.txo(0.01))],  # inputs
            []                           # outputs
        )
        # UTXO 1 is added to cover some of the fee
        self.assertListEqual([0.01, 1], self.inputs(tx))
        # change is now needed to consume extra input
        self.assertListEqual([0.97], self.outputs(tx))
