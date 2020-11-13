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

    async def assertFindsClaims(self, claim_names, awaitable):
        self.assertEqual(claim_names, [txo["name"] for txo in await awaitable])

    async def assertOutputAmount(self, amounts, awaitable):
        self.assertEqual(amounts, [txo["amount"] for txo in await awaitable])

    async def test_commands_across_accounts(self):
        account1 = self.wallet.accounts.default.id
        account2 = (await self.account_create('second account'))["id"]

        address2 = await self.address_unused(account2)
        await self.wallet_send('0.05', address2, fund_account_id=self.account.id)
        await self.generate(1)
        await self.assertOutputAmount(['0.05', '9.949876'], self.utxo_list())
        await self.assertOutputAmount(['9.949876'], self.utxo_list(account_id=account1))
        await self.assertOutputAmount(['0.05'], self.utxo_list(account_id=account2))

        channel1 = await self.channel_create('@channel-in-account1', '0.01')
        channel2 = await self.channel_create(
            '@channel-in-account2', '0.01', account_id=account2, fund_account_id=[account1]
        )

        await self.assertFindsClaims(['@channel-in-account2', '@channel-in-account1'], self.channel_list())
        await self.assertFindsClaims(['@channel-in-account1'], self.channel_list(account_id=account1))
        await self.assertFindsClaims(['@channel-in-account2'], self.channel_list(account_id=account2))

        stream1 = await self.stream_create('stream-in-account1', '0.01', channel_id=self.get_claim_id(channel1))
        stream2 = await self.stream_create(
            'stream-in-account2', '0.01', channel_id=self.get_claim_id(channel2),
            account_id=account2, fund_account_id=[account1]
        )
        await self.assertFindsClaims(['stream-in-account2', 'stream-in-account1'], self.stream_list())
        await self.assertFindsClaims(['stream-in-account1'], self.stream_list(account_id=account1))
        await self.assertFindsClaims(['stream-in-account2'], self.stream_list(account_id=account2))

        await self.assertFindsClaims(
            ['stream-in-account2', 'stream-in-account1', '@channel-in-account2', '@channel-in-account1'],
            self.claim_list()
        )
        await self.assertFindsClaims(
            ['stream-in-account1', '@channel-in-account1'],
            self.claim_list(account_id=account1)
        )
        await self.assertFindsClaims(
            ['stream-in-account2', '@channel-in-account2'],
            self.claim_list(account_id=account2)
        )

        support1 = await self.support_create(self.get_claim_id(stream1), '0.01')
        support2 = await self.support_create(
            self.get_claim_id(stream2), '0.01', account_id=account2, fund_account_id=[account1]
        )
        self.assertEqual([support2['txid'], support1['txid']], [txo['txid'] for txo in await self.support_list()])
        self.assertEqual([support1['txid']], [txo['txid'] for txo in await self.support_list(account_id=account1)])
        self.assertEqual([support2['txid']], [txo['txid'] for txo in await self.support_list(account_id=account2)])

        history = await self.transaction_list()
        self.assertEqual(len(history), 8)
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
        address = await self.address_unused()
        bad_address = address[0:20] + '9999999' + address[27:]
        with self.assertRaisesRegex(Exception, f"'{bad_address}' is not a valid address"):
            await self.wallet_send('0.1', bad_address)
