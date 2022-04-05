from binascii import hexlify, unhexlify

from lbry.testcase import CommandTestCase
from lbry.wallet.script import InputScript
from lbry.wallet.dewies import dewies_to_lbc
from lbry.wallet.account import DeterministicChannelKeyManager
from lbry.crypto.hash import hash160
from lbry.crypto.base58 import Base58


def extract(d, keys):
    return {k: d[k] for k in keys}


class AccountManagement(CommandTestCase):
    async def test_account_list_set_create_remove_add(self):
        # check initial account
        accounts = await self.daemon.jsonrpc_account_list()
        self.assertItemCount(accounts, 1)

        # change account name and gap
        account_id = accounts['items'][0]['id']
        self.daemon.jsonrpc_account_set(
            account_id=account_id, new_name='test account',
            receiving_gap=95, receiving_max_uses=96,
            change_gap=97, change_max_uses=98
        )
        accounts = (await self.daemon.jsonrpc_account_list())['items'][0]
        self.assertEqual(accounts['name'], 'test account')
        self.assertEqual(
            accounts['address_generator']['receiving'],
            {'gap': 95, 'maximum_uses_per_address': 96}
        )
        self.assertEqual(
            accounts['address_generator']['change'],
            {'gap': 97, 'maximum_uses_per_address': 98}
        )

        # create another account
        await self.daemon.jsonrpc_account_create('second account')
        accounts = await self.daemon.jsonrpc_account_list()
        self.assertItemCount(accounts, 2)
        self.assertEqual(accounts['items'][1]['name'], 'second account')
        account_id2 = accounts['items'][1]['id']

        # make new account the default
        self.daemon.jsonrpc_account_set(account_id=account_id2, default=True)
        accounts = await self.daemon.jsonrpc_account_list(show_seed=True)
        self.assertEqual(accounts['items'][0]['name'], 'second account')

        account_seed = accounts['items'][1]['seed']

        # remove account
        self.daemon.jsonrpc_account_remove(accounts['items'][1]['id'])
        accounts = await self.daemon.jsonrpc_account_list()
        self.assertItemCount(accounts, 1)

        # add account
        await self.daemon.jsonrpc_account_add('recreated account', seed=account_seed)
        accounts = await self.daemon.jsonrpc_account_list()
        self.assertItemCount(accounts, 2)
        self.assertEqual(accounts['items'][1]['name'], 'recreated account')

        # list specific account
        accounts = await self.daemon.jsonrpc_account_list(account_id, include_claims=True)
        self.assertEqual(accounts['items'][0]['name'], 'recreated account')

    async def test_wallet_migration(self):
        old_id, new_id, valid_key = (
            'mi9E8KqFfW5ngktU22pN2jpgsdf81ZbsGY',
            'mqs77XbdnuxWN4cXrjKbSoGLkvAHa4f4B8',
            '-----BEGIN EC PRIVATE KEY-----\nMHQCAQEEIBZRTZ7tHnYCH3IE9mCo95'
            '466L/ShYFhXGrjmSMFJw8eoAcGBSuBBAAK\noUQDQgAEmucoPz9nI+ChZrfhnh'
            '0RZ/bcX0r2G0pYBmoNKovtKzXGa8y07D66MWsW\nqXptakqO/9KddIkBu5eJNS'
            'UZzQCxPQ==\n-----END EC PRIVATE KEY-----\n'
        )
        # null certificates should get deleted
        self.account.channel_keys = {
            new_id: 'not valid key',
            'foo': 'bar',
        }
        await self.account.maybe_migrate_certificates()
        self.assertEqual(self.account.channel_keys, {})
        self.account.channel_keys = {
            new_id: 'not valid key',
            'foo': 'bar',
            'invalid address': valid_key,
        }
        await self.account.maybe_migrate_certificates()
        self.assertEqual(self.account.channel_keys, {
            new_id: valid_key
        })

    async def assertFindsClaims(self, claim_names, awaitable):
        self.assertEqual(claim_names, [txo.claim_name for txo in (await awaitable)['items']])

    async def assertOutputAmount(self, amounts, awaitable):
        self.assertEqual(amounts, [dewies_to_lbc(txo.amount) for txo in (await awaitable)['items']])

    async def test_commands_across_accounts(self):
        channel_list = self.daemon.jsonrpc_channel_list
        stream_list = self.daemon.jsonrpc_stream_list
        support_list = self.daemon.jsonrpc_support_list
        utxo_list = self.daemon.jsonrpc_utxo_list
        default_account = self.wallet.default_account
        second_account = await self.daemon.jsonrpc_account_create('second account')

        tx = await self.daemon.jsonrpc_account_send(
            '0.05', await self.daemon.jsonrpc_address_unused(account_id=second_account.id), blocking=True
        )
        await self.confirm_tx(tx.id)
        await self.assertOutputAmount(['0.05', '9.949876'], utxo_list())
        await self.assertOutputAmount(['0.05'], utxo_list(account_id=second_account.id))
        await self.assertOutputAmount(['9.949876'], utxo_list(account_id=default_account.id))

        channel1 = await self.channel_create('@channel-in-account1', '0.01')
        channel2 = await self.channel_create(
            '@channel-in-account2', '0.01', account_id=second_account.id, funding_account_ids=[default_account.id]
        )

        await self.assertFindsClaims(['@channel-in-account2', '@channel-in-account1'], channel_list())
        await self.assertFindsClaims(['@channel-in-account1'], channel_list(account_id=default_account.id))
        await self.assertFindsClaims(['@channel-in-account2'], channel_list(account_id=second_account.id))

        stream1 = await self.stream_create('stream-in-account1', '0.01', channel_id=self.get_claim_id(channel1))
        stream2 = await self.stream_create(
            'stream-in-account2', '0.01', channel_id=self.get_claim_id(channel2),
            account_id=second_account.id, funding_account_ids=[default_account.id]
        )
        await self.assertFindsClaims(['stream-in-account2', 'stream-in-account1'], stream_list())
        await self.assertFindsClaims(['stream-in-account1'], stream_list(account_id=default_account.id))
        await self.assertFindsClaims(['stream-in-account2'], stream_list(account_id=second_account.id))

        await self.assertFindsClaims(
            ['stream-in-account2', 'stream-in-account1', '@channel-in-account2', '@channel-in-account1'],
            self.daemon.jsonrpc_claim_list()
        )
        await self.assertFindsClaims(
            ['stream-in-account1', '@channel-in-account1'],
            self.daemon.jsonrpc_claim_list(account_id=default_account.id)
        )
        await self.assertFindsClaims(
            ['stream-in-account2', '@channel-in-account2'],
            self.daemon.jsonrpc_claim_list(account_id=second_account.id)
        )

        support1 = await self.support_create(self.get_claim_id(stream1), '0.01')
        support2 = await self.support_create(
            self.get_claim_id(stream2), '0.01', account_id=second_account.id, funding_account_ids=[default_account.id]
        )
        self.assertEqual([support2['txid'], support1['txid']], [txo.tx_ref.id for txo in (await support_list())['items']])
        self.assertEqual([support1['txid']], [txo.tx_ref.id for txo in (await support_list(account_id=default_account.id))['items']])
        self.assertEqual([support2['txid']], [txo.tx_ref.id for txo in (await support_list(account_id=second_account.id))['items']])

        history = await self.daemon.jsonrpc_transaction_list()
        self.assertItemCount(history, 8)
        history = history['items']
        self.assertEqual(extract(history[0]['support_info'][0], ['claim_name', 'is_tip', 'amount', 'balance_delta']), {
            'claim_name': 'stream-in-account2',
            'is_tip': False,
            'amount': '0.01',
            'balance_delta': '-0.01'
        })
        self.assertEqual(extract(history[1]['support_info'][0], ['claim_name', 'is_tip', 'amount', 'balance_delta']), {
            'claim_name': 'stream-in-account1',
            'is_tip': False,
            'amount': '0.01',
            'balance_delta': '-0.01'
        })
        self.assertEqual(extract(history[2]['claim_info'][0], ['claim_name', 'amount', 'balance_delta']), {
            'claim_name': 'stream-in-account2',
            'amount': '0.01',
            'balance_delta': '-0.01'
        })
        self.assertEqual(extract(history[3]['claim_info'][0], ['claim_name', 'amount', 'balance_delta']), {
            'claim_name': 'stream-in-account1',
            'amount': '0.01',
            'balance_delta': '-0.01'
        })
        self.assertEqual(extract(history[4]['claim_info'][0], ['claim_name', 'amount', 'balance_delta']), {
            'claim_name': '@channel-in-account2',
            'amount': '0.01',
            'balance_delta': '-0.01'
        })
        self.assertEqual(extract(history[5]['claim_info'][0], ['claim_name', 'amount', 'balance_delta']), {
            'claim_name': '@channel-in-account1',
            'amount': '0.01',
            'balance_delta': '-0.01'
        })
        self.assertEqual(history[6]['value'], '0.0')
        self.assertEqual(history[7]['value'], '10.0')

    async def test_address_validation(self):
        address = await self.daemon.jsonrpc_address_unused()
        bad_address = address[0:20] + '9999999' + address[27:]
        with self.assertRaisesRegex(Exception, f"'{bad_address}' is not a valid address"):
            await self.daemon.jsonrpc_account_send('0.1', addresses=[bad_address])

    async def test_hybrid_channel_keys(self):
        # non-deterministic channel
        self.account.channel_keys = {
            'mqs77XbdnuxWN4cXrjKbSoGLkvAHa4f4B8':
                '-----BEGIN EC PRIVATE KEY-----\nMHQCAQEEIBZRTZ7tHnYCH3IE9mCo95'
                '466L/ShYFhXGrjmSMFJw8eoAcGBSuBBAAK\noUQDQgAEmucoPz9nI+ChZrfhnh'
                '0RZ/bcX0r2G0pYBmoNKovtKzXGa8y07D66MWsW\nqXptakqO/9KddIkBu5eJNS'
                'UZzQCxPQ==\n-----END EC PRIVATE KEY-----\n'
        }
        channel1 = await self.create_nondeterministic_channel('@foo1', '1.0', unhexlify(
            '3056301006072a8648ce3d020106052b8104000a034200049ae7283f3f6723e0a1'
            '66b7e19e1d1167f6dc5f4af61b4a58066a0d2a8bed2b35c66bccb4ec3eba316b16'
            'a97a6d6a4a8effd29d748901bb9789352519cd00b13d'
        ))
        await self.confirm_tx(channel1['txid'])

        # deterministic channel
        channel2 = await self.channel_create('@foo2')

        await self.stream_create('stream-in-channel1', '0.01', channel_id=self.get_claim_id(channel1))
        await self.stream_create('stream-in-channel2', '0.01', channel_id=self.get_claim_id(channel2))

        resolved_stream1 = await self.resolve('@foo1/stream-in-channel1')
        self.assertEqual('stream-in-channel1', resolved_stream1['name'])
        self.assertTrue(resolved_stream1['is_channel_signature_valid'])

        resolved_stream2 = await self.resolve('@foo2/stream-in-channel2')
        self.assertEqual('stream-in-channel2', resolved_stream2['name'])
        self.assertTrue(resolved_stream2['is_channel_signature_valid'])

    async def test_deterministic_channel_keys(self):
        seed = self.account.seed
        keys = self.account.deterministic_channel_keys

        # create two channels and make sure they have different keys
        channel1a = await self.channel_create('@foo1')
        channel2a = await self.channel_create('@foo2')
        self.assertNotEqual(
            channel1a['outputs'][0]['value']['public_key'],
            channel2a['outputs'][0]['value']['public_key'],
        )

        # start another daemon from the same seed
        self.daemon2 = await self.add_daemon(seed=seed)
        channel2b, channel1b = (await self.daemon2.jsonrpc_channel_list())['items']

        # both daemons end up with the same channel signing keys automagically
        self.assertTrue(channel1b.has_private_key)
        self.assertEqual(
            channel1a['outputs'][0]['value']['public_key_id'],
            channel1b.private_key.address
        )
        self.assertTrue(channel2b.has_private_key)
        self.assertEqual(
            channel2a['outputs'][0]['value']['public_key_id'],
            channel2b.private_key.address
        )

        # repeatedly calling next channel key returns the same key when not used
        current_known = keys.last_known
        next_key = await keys.generate_next_key()
        self.assertEqual(current_known, keys.last_known)
        self.assertEqual(next_key.address, (await keys.generate_next_key()).address)
        # again, should be idempotent
        next_key = await keys.generate_next_key()
        self.assertEqual(current_known, keys.last_known)
        self.assertEqual(next_key.address, (await keys.generate_next_key()).address)

        # create third channel while both daemons running, second daemon should pick it up
        channel3a = await self.channel_create('@foo3')
        self.assertEqual(current_known+1, keys.last_known)
        self.assertNotEqual(next_key.address, (await keys.generate_next_key()).address)
        channel3b, = (await self.daemon2.jsonrpc_channel_list(name='@foo3'))['items']
        self.assertTrue(channel3b.has_private_key)
        self.assertEqual(
            channel3a['outputs'][0]['value']['public_key_id'],
            channel3b.private_key.address
        )

        # channel key cache re-populated after simulated restart

        # reset cache
        self.account.deterministic_channel_keys = DeterministicChannelKeyManager(self.account)
        channel3c, channel2c, channel1c = (await self.daemon.jsonrpc_channel_list())['items']
        self.assertFalse(channel1c.has_private_key)
        self.assertFalse(channel2c.has_private_key)
        self.assertFalse(channel3c.has_private_key)

        # repopulate cache
        await self.account.deterministic_channel_keys.ensure_cache_primed()
        self.assertEqual(self.account.deterministic_channel_keys.last_known, keys.last_known)
        channel3c, channel2c, channel1c = (await self.daemon.jsonrpc_channel_list())['items']
        self.assertTrue(channel1c.has_private_key)
        self.assertTrue(channel2c.has_private_key)
        self.assertTrue(channel3c.has_private_key)

    async def test_time_locked_transactions(self):
        address = await self.account.receiving.get_or_create_usable_address()
        private_key = await self.ledger.get_private_key_for_address(self.wallet, address)

        script = InputScript(
            template=InputScript.TIME_LOCK_SCRIPT,
            values={'height': 210, 'pubkey_hash': self.ledger.address_to_hash160(address)}
        )
        script_address = self.ledger.hash160_to_script_address(hash160(script.source))
        script_source = hexlify(script.source).decode()

        await self.assertBalance(self.account, '10.0')
        tx = await self.daemon.jsonrpc_account_send('4.0', script_address)
        await self.confirm_tx(tx.id)
        await self.generate(510)
        await self.assertBalance(self.account, '5.999877')
        tx = await self.daemon.jsonrpc_account_deposit(
            tx.id, 0, script_source,
            Base58.encode_check(self.ledger.private_key_to_wif(private_key.private_key_bytes))
        )
        await self.confirm_tx(tx.id)
        await self.assertBalance(self.account, '9.9997545')
