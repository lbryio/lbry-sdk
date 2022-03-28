from lbry.testcase import CommandTestCase
from lbry.wallet.dewies import dewies_to_lbc


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
