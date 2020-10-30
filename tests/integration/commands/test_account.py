from lbry.testcase import CommandTestCase
from lbry.blockchain import dewies_to_lbc


def extract(d, keys):
    return {k: d[k] for k in keys}


class AccountManagement(CommandTestCase):

    async def test_account_list_set_create_remove_add(self):
        # check initial account
        self.assertEqual(len(await self.account_list()), 1)

        # create another account
        await self.account_create('second account')
        accounts = await self.account_list()
        self.assertEqual(len(accounts), 2)
        account = accounts[1]
        self.assertEqual(account['name'], 'second account')
        self.assertEqual(account['address_generator'], {
            'name': 'deterministic-chain',
            'receiving': {'gap': 20, 'maximum_uses_per_address': 1},
            'change': {'gap': 6, 'maximum_uses_per_address': 1},
        })

        # change account name and gap
        await self.account_set(
            account_id=account['id'], new_name='test account',
            receiving_gap=95, receiving_max_uses=96,
            change_gap=97, change_max_uses=98
        )
        account = (await self.account_list())[1]
        self.assertEqual(account['name'], 'test account')
        self.assertEqual(account['address_generator'], {
            'name': 'deterministic-chain',
            'receiving': {'gap': 95, 'maximum_uses_per_address': 96},
            'change': {'gap': 97, 'maximum_uses_per_address': 98},
        })

        # make new account the default
        await self.account_set(account_id=account['id'], default=True)
        actual = (await self.account_list())[0]
        self.assertNotEqual(account['modified_on'], actual['modified_on'])
        del account['modified_on']
        del actual['modified_on']
        self.assertEqual(account, actual)

        account_seed, account_pubkey = account['seed'], account['public_key']

        # remove account
        await self.account_remove(account['id'])
        self.assertEqual(len(await self.account_list()), 1)

        # add account
        await self.account_add('recreated account', seed=account_seed)
        accounts = await self.account_list()
        self.assertEqual(len(accounts), 2)
        account = accounts[1]
        self.assertEqual(account['name'], 'recreated account')
        self.assertEqual(account['public_key'], account_pubkey)

        # list specific account
        accounts = await self.account_list(account['id'])
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]['name'], 'recreated account')

    async def test_wallet_migration(self):
        # null certificates should get deleted
        await self.channel_create('@foo1')
        await self.channel_create('@foo2')
        await self.channel_create('@foo3')
        keys = list(self.account.channel_keys.keys())
        self.account.channel_keys[keys[0]] = None
        self.account.channel_keys[keys[1]] = "some invalid junk"
        await self.account.maybe_migrate_certificates()
        self.assertEqual(list(self.account.channel_keys.keys()), [keys[2]])

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
            '0.05', await self.daemon.jsonrpc_address_unused(account_id=second_account.id)
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
