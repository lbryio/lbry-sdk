from lbrynet.testcase import CommandTestCase


class AccountManagement(CommandTestCase):

    async def test_account_list_set_create_remove_add(self):
        # check initial account
        response = await self.daemon.jsonrpc_account_list()
        self.assertEqual(len(response['lbc_regtest']), 1)

        # change account name and gap
        account_id = response['lbc_regtest'][0]['id']
        self.daemon.jsonrpc_account_set(
            account_id=account_id, new_name='test account',
            receiving_gap=95, receiving_max_uses=96,
            change_gap=97, change_max_uses=98
        )
        response = (await self.daemon.jsonrpc_account_list())['lbc_regtest'][0]
        self.assertEqual(response['name'], 'test account')
        self.assertEqual(
            response['address_generator']['receiving'],
            {'gap': 95, 'maximum_uses_per_address': 96}
        )
        self.assertEqual(
            response['address_generator']['change'],
            {'gap': 97, 'maximum_uses_per_address': 98}
        )

        # create another account
        await self.daemon.jsonrpc_account_create('second account')
        response = await self.daemon.jsonrpc_account_list()
        self.assertEqual(len(response['lbc_regtest']), 2)
        self.assertEqual(response['lbc_regtest'][1]['name'], 'second account')
        account_id2 = response['lbc_regtest'][1]['id']

        # make new account the default
        self.daemon.jsonrpc_account_set(account_id=account_id2, default=True)
        response = await self.daemon.jsonrpc_account_list(show_seed=True)
        self.assertEqual(response['lbc_regtest'][0]['name'], 'second account')

        account_seed = response['lbc_regtest'][1]['seed']

        # remove account
        self.daemon.jsonrpc_account_remove(response['lbc_regtest'][1]['id'])
        response = await self.daemon.jsonrpc_account_list()
        self.assertEqual(len(response['lbc_regtest']), 1)

        # add account
        await self.daemon.jsonrpc_account_add('recreated account', seed=account_seed)
        response = await self.daemon.jsonrpc_account_list()
        self.assertEqual(len(response['lbc_regtest']), 2)
        self.assertEqual(response['lbc_regtest'][1]['name'], 'recreated account')

        # list specific account
        response = await self.daemon.jsonrpc_account_list(account_id, include_claims=True)
        self.assertEqual(response['name'], 'recreated account')
