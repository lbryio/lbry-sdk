import tempfile

from lbrynet.extras.wallet.transaction import Transaction
from lbrynet.error import InsufficientFundsError
from lbrynet.schema.claim import ClaimDict

from integration.testcase import CommandTestCase


class ClaimCommands(CommandTestCase):

    async def craft_claim(self, name, amount_dewies, claim_dict, address):
        # FIXME: this is here mostly because publish has defensive code for situations that happens accidentally
        # However, it still happens... So, let's reproduce them.
        claim = ClaimDict.load_dict(claim_dict)
        address = address or (await self.account.receiving.get_addresses(limit=1, only_usable=True))[0]
        tx = await Transaction.claim(name, claim, amount_dewies, address, [self.account], self.account)
        await self.broadcast(tx)
        await self.ledger.wait(tx)
        await self.generate(1)
        await self.ledger.wait(tx)
        return tx

    async def test_create_update_and_abandon_claim(self):
        await self.assertBalance(self.account, '10.0')

        claim = await self.make_claim(amount='2.5')  # creates new claim
        txs = await self.out(self.daemon.jsonrpc_transaction_list())
        self.assertEqual(len(txs[0]['claim_info']), 1)
        self.assertEqual(txs[0]['confirmations'], 1)
        self.assertEqual(txs[0]['claim_info'][0]['balance_delta'], '-2.5')
        self.assertEqual(txs[0]['claim_info'][0]['claim_id'], claim['claim_id'])
        self.assertEqual(txs[0]['value'], '0.0')
        self.assertEqual(txs[0]['fee'], '-0.020107')
        await self.assertBalance(self.account, '7.479893')

        await self.make_claim(amount='1.0')  # updates previous claim
        txs = await self.out(self.daemon.jsonrpc_transaction_list())
        self.assertEqual(len(txs[0]['update_info']), 1)
        self.assertEqual(txs[0]['update_info'][0]['balance_delta'], '1.5')
        self.assertEqual(txs[0]['update_info'][0]['claim_id'], claim['claim_id'])
        self.assertEqual(txs[0]['value'], '0.0')
        self.assertEqual(txs[0]['fee'], '-0.0001985')
        await self.assertBalance(self.account, '8.9796945')

        await self.out(self.daemon.jsonrpc_claim_abandon(claim['claim_id']))
        txs = await self.out(self.daemon.jsonrpc_transaction_list())
        self.assertEqual(len(txs[0]['abandon_info']), 1)
        self.assertEqual(txs[0]['abandon_info'][0]['balance_delta'], '1.0')
        self.assertEqual(txs[0]['abandon_info'][0]['claim_id'], claim['claim_id'])
        self.assertEqual(txs[0]['value'], '0.0')
        self.assertEqual(txs[0]['fee'], '-0.000107')
        await self.assertBalance(self.account, '9.9795875')

    async def test_update_claim_holding_address(self):
        other_account_id = (await self.daemon.jsonrpc_account_create('second account'))['id']
        other_account = self.daemon.get_account_or_error(other_account_id)
        other_address = await other_account.receiving.get_or_create_usable_address()

        await self.assertBalance(self.account, '10.0')

        # create the initial name claim
        claim = await self.make_claim()

        self.assertEqual(len(await self.daemon.jsonrpc_claim_list_mine()), 1)
        self.assertEqual(len(await self.daemon.jsonrpc_claim_list_mine(account_id=other_account_id)), 0)
        tx = await self.daemon.jsonrpc_claim_send_to_address(
            claim['claim_id'], other_address
        )
        await self.ledger.wait(tx)
        self.assertEqual(len(await self.daemon.jsonrpc_claim_list_mine()), 0)
        self.assertEqual(len(await self.daemon.jsonrpc_claim_list_mine(account_id=other_account_id)), 1)

    async def test_publishing_checks_all_accounts_for_certificate(self):
        account1_id, account1 = self.account.id, self.account
        new_account = await self.daemon.jsonrpc_account_create('second account')
        account2_id, account2 = new_account['id'], self.daemon.get_account_or_error(new_account['id'])

        spam_channel = await self.out(self.daemon.jsonrpc_channel_new('@spam', '1.0'))
        self.assertTrue(spam_channel['success'])
        await self.confirm_tx(spam_channel['tx']['txid'])

        self.assertEqual('8.989893', await self.daemon.jsonrpc_account_balance())

        result = await self.out(self.daemon.jsonrpc_wallet_send(
            '5.0', await self.daemon.jsonrpc_address_unused(account2_id)
        ))
        await self.confirm_tx(result['txid'])

        self.assertEqual('3.989769', await self.daemon.jsonrpc_account_balance())
        self.assertEqual('5.0', await self.daemon.jsonrpc_account_balance(account2_id))

        baz_channel = await self.out(self.daemon.jsonrpc_channel_new('@baz', '1.0', account2_id))
        self.assertTrue(baz_channel['success'])
        await self.confirm_tx(baz_channel['tx']['txid'])

        channels = await self.out(self.daemon.jsonrpc_channel_list(account1_id))
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0]['name'], '@spam')
        self.assertEqual(channels, await self.out(self.daemon.jsonrpc_channel_list()))

        channels = await self.out(self.daemon.jsonrpc_channel_list(account2_id))
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0]['name'], '@baz')

        # defaults to using all accounts to lookup channel
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'hi!')
            file.flush()
            claim1 = await self.out(self.daemon.jsonrpc_publish(
                'hovercraft', '1.0', file_path=file.name, channel_name='@baz'
            ))
            self.assertTrue(claim1['success'])
            await self.confirm_tx(claim1['tx']['txid'])

        # uses only the specific accounts which contains the channel
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'hi!')
            file.flush()
            claim1 = await self.out(self.daemon.jsonrpc_publish(
                'hovercraft', '1.0', file_path=file.name,
                channel_name='@baz', channel_account_id=[account2_id]
            ))
            self.assertTrue(claim1['success'])
            await self.confirm_tx(claim1['tx']['txid'])

        # fails when specifying account which does not contain channel
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'hi!')
            file.flush()
            with self.assertRaisesRegex(ValueError, "Couldn't find channel with name '@baz'."):
                await self.out(self.daemon.jsonrpc_publish(
                    'hovercraft', '1.0', file_path=file.name,
                    channel_name='@baz', channel_account_id=[account1_id]
                ))

    async def test_updating_claim_includes_claim_value_in_balance_check(self):
        await self.assertBalance(self.account, '10.0')

        await self.make_claim(amount='9.0')
        await self.assertBalance(self.account, '0.979893')

        # update the same claim
        await self.make_claim(amount='9.0')
        await self.assertBalance(self.account, '0.9796205')

        # update the claim a second time but use even more funds
        await self.make_claim(amount='9.97')
        await self.assertBalance(self.account, '0.009348')

        # fails when specifying more than available
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'hi!')
            file.flush()
            with self.assertRaisesRegex(
                InsufficientFundsError,
                "Please lower the bid value, the maximum amount"
                " you can specify for this claim is 9.979274."
            ):
                await self.out(self.daemon.jsonrpc_publish(
                    'hovercraft', '9.98', file_path=file.name
                ))

    async def test_abandoning_claim_at_loss(self):
        await self.assertBalance(self.account, '10.0')
        claim = await self.make_claim(amount='0.0001')
        await self.assertBalance(self.account, '9.979793')
        await self.out(self.daemon.jsonrpc_claim_abandon(claim['claim_id']))
        await self.assertBalance(self.account, '9.97968399')

    async def test_claim_show(self):
        channel = await self.out(self.daemon.jsonrpc_channel_new('@abc', "1.0"))
        self.assertTrue(channel['success'])
        await self.confirm_tx(channel['tx']['txid'])
        channel_from_claim_show = await self.out(
            self.daemon.jsonrpc_claim_show(txid=channel['tx']['txid'], nout=channel['output']['nout'])
        )
        self.assertEqual(channel_from_claim_show['value'], channel['output']['value'])
        channel_from_claim_show = await self.out(
            self.daemon.jsonrpc_claim_show(claim_id=channel['claim_id'])
        )
        self.assertEqual(channel_from_claim_show['value'], channel['output']['value'])

        abandon = await self.out(self.daemon.jsonrpc_claim_abandon(txid=channel['tx']['txid'], nout=0, blocking=False))
        self.assertTrue(abandon['success'])
        await self.confirm_tx(abandon['tx']['txid'])
        not_a_claim = await self.out(
            self.daemon.jsonrpc_claim_show(txid=abandon['tx']['txid'], nout=0)
        )
        self.assertEqual(not_a_claim, 'claim not found')

    async def test_claim_list(self):
        channel = await self.out(self.daemon.jsonrpc_channel_new('@abc', "1.0"))
        self.assertTrue(channel['success'])
        await self.confirm_tx(channel['tx']['txid'])
        claim = await self.make_claim(amount='0.0001', name='on-channel-claim', channel_name='@abc')
        self.assertTrue(claim['success'])
        unsigned_claim = await self.make_claim(amount='0.0001', name='unsigned')
        self.assertTrue(claim['success'])

        channel_from_claim_list = await self.out(self.daemon.jsonrpc_claim_list('@abc'))
        self.assertEqual(channel_from_claim_list['claims'][0]['value'], channel['output']['value'])
        signed_claim_from_claim_list = await self.out(self.daemon.jsonrpc_claim_list('on-channel-claim'))
        self.assertEqual(signed_claim_from_claim_list['claims'][0]['value'], claim['output']['value'])
        unsigned_claim_from_claim_list = await self.out(self.daemon.jsonrpc_claim_list('unsigned'))
        self.assertEqual(unsigned_claim_from_claim_list['claims'][0]['value'], unsigned_claim['output']['value'])

        abandon = await self.out(self.daemon.jsonrpc_claim_abandon(txid=channel['tx']['txid'], nout=0, blocking=False))
        self.assertTrue(abandon['success'])
        await self.confirm_tx(abandon['tx']['txid'])

        empty = await self.out(self.daemon.jsonrpc_claim_list('@abc'))
        self.assertEqual(len(empty['claims']), 0)

    async def test_abandoned_channel_with_signed_claims(self):
        channel = await self.out(self.daemon.jsonrpc_channel_new('@abc', "1.0"))
        self.assertTrue(channel['success'])
        await self.confirm_tx(channel['tx']['txid'])
        claim = await self.make_claim(amount='0.0001', name='on-channel-claim', channel_name='@abc')
        self.assertTrue(claim['success'])
        abandon = await self.out(self.daemon.jsonrpc_claim_abandon(txid=channel['tx']['txid'], nout=0, blocking=False))
        self.assertTrue(abandon['success'])
        channel = await self.out(self.daemon.jsonrpc_channel_new('@abc', "1.0"))
        self.assertTrue(channel['success'])
        await self.confirm_tx(channel['tx']['txid'])

        # Original channel doesnt exists anymore, so the signature is invalid. For invalid signatures, resolution is
        # only possible outside a channel
        response = await self.resolve('lbry://@abc/on-channel-claim')
        self.assertNotIn('claim', response['lbry://@abc/on-channel-claim'])
        response = await self.resolve('lbry://on-channel-claim')
        self.assertIn('claim', response['lbry://on-channel-claim'])
        self.assertFalse(response['lbry://on-channel-claim']['claim']['signature_is_valid'])
        direct_uri = 'lbry://on-channel-claim#' + claim['claim_id']
        response = await self.resolve(direct_uri)
        self.assertIn('claim', response[direct_uri])
        self.assertFalse(response[direct_uri]['claim']['signature_is_valid'])

        uri = 'lbry://@abc/on-channel-claim'
        # now, claim something on this channel (it will update the invalid claim, but we save and forcefully restore)
        original_claim = await self.make_claim(amount='0.00000001', name='on-channel-claim', channel_name='@abc')
        self.assertTrue(original_claim['success'])
        # resolves normally
        response = await self.resolve(uri)
        self.assertIn('claim', response[uri])
        self.assertTrue(response[uri]['claim']['signature_is_valid'])

        # tamper it, invalidating the signature
        value = response[uri]['claim']['value'].copy()
        value['stream']['metadata']['author'] = 'some troll'
        address = response[uri]['claim']['address']
        await self.craft_claim('on-channel-claim', 1, value, address)
        # it resolves to the now only valid claim under the channel, ignoring the fake one
        response = await self.resolve(uri)
        self.assertIn('claim', response[uri])
        self.assertTrue(response[uri]['claim']['signature_is_valid'])

        # ooops! claimed a valid conflict! (this happens on the wild, mostly by accident or race condition)
        await self.craft_claim('on-channel-claim', 1, response[uri]['claim']['value'], address)

        # it still resolves! but to the older claim
        response = await self.resolve(uri)
        self.assertIn('claim', response[uri])
        self.assertTrue(response[uri]['claim']['signature_is_valid'])
        self.assertEqual(response[uri]['claim']['txid'], original_claim['tx']['txid'])

    async def test_claim_list_by_channel(self):
        self.maxDiff = None
        tx = await self.daemon.jsonrpc_account_fund(None, None, '0.001', outputs=100, broadcast=True)
        await self.ledger.wait(tx)
        await self.generate(1)
        await self.ledger.wait(tx)
        channel = await self.out(self.daemon.jsonrpc_channel_new('@abc', "0.0001"))
        self.assertTrue(channel['success'])
        await self.confirm_tx(channel['tx']['txid'])

        # 4 claims per block, 3 blocks. Sorted by height (descending) then claim_id (ascending).
        claims = []
        for j in range(3):
            same_height_claims = []
            for k in range(3):
                claim = await self.make_claim(amount='0.000001', name=f'c{j}-{k}', channel_name='@abc', confirm=False)
                self.assertTrue(claim['success'])
                same_height_claims.append(claim['claim_id'])
                await self.on_transaction_dict(claim['tx'])
            claim = await self.make_claim(amount='0.000001', name=f'c{j}-4', channel_name='@abc', confirm=True)
            self.assertTrue(claim['success'])
            same_height_claims.append(claim['claim_id'])
            same_height_claims.sort(key=lambda x: int(x, 16))
            claims = same_height_claims + claims

        page = await self.out(self.daemon.jsonrpc_claim_list_by_channel(1, page_size=20, uri='@abc'))
        page_claim_ids = [item['claim_id'] for item in page['@abc']['claims_in_channel']]
        self.assertEqual(page_claim_ids, claims)
        page = await self.out(self.daemon.jsonrpc_claim_list_by_channel(1, page_size=6, uri='@abc'))
        page_claim_ids = [item['claim_id'] for item in page['@abc']['claims_in_channel']]
        self.assertEqual(page_claim_ids, claims[:6])
        out_of_bounds = await self.out(self.daemon.jsonrpc_claim_list_by_channel(2, page_size=20, uri='@abc'))
        self.assertEqual(out_of_bounds['error'], 'claim 20 greater than max 12')

    async def test_regular_supports_and_tip_supports(self):
        # account2 will be used to send tips and supports to account1
        account2_id = (await self.daemon.jsonrpc_account_create('second account'))['id']

        # send account2 5 LBC out of the 10 LBC in account1
        result = await self.out(self.daemon.jsonrpc_wallet_send(
            '5.0', await self.daemon.jsonrpc_address_unused(account2_id)
        ))
        await self.confirm_tx(result['txid'])

        # account1 and account2 balances:
        self.assertEqual('4.999876', await self.daemon.jsonrpc_account_balance())
        self.assertEqual('5.0', await self.daemon.jsonrpc_account_balance(account2_id))

        # create the claim we'll be tipping and supporting
        claim = await self.make_claim()

        # account1 and account2 balances:
        self.assertEqual('3.979769', await self.daemon.jsonrpc_account_balance())
        self.assertEqual('5.0', await self.daemon.jsonrpc_account_balance(account2_id))

        # send a tip to the claim using account2
        tip = await self.out(
            self.daemon.jsonrpc_claim_tip(claim['claim_id'], '1.0', account2_id)
        )
        await self.on_transaction_dict(tip)
        await self.generate(1)
        await self.on_transaction_dict(tip)

        # tips don't affect balance so account1 balance is same but account2 balance went down
        self.assertEqual('3.979769', await self.daemon.jsonrpc_account_balance())
        self.assertEqual('3.9998585', await self.daemon.jsonrpc_account_balance(account2_id))

        # verify that the incoming tip is marked correctly as is_tip=True in account1
        txs = await self.out(self.daemon.jsonrpc_transaction_list())
        self.assertEqual(len(txs[0]['support_info']), 1)
        self.assertEqual(txs[0]['support_info'][0]['balance_delta'], '1.0')
        self.assertEqual(txs[0]['support_info'][0]['claim_id'], claim['claim_id'])
        self.assertEqual(txs[0]['support_info'][0]['is_tip'], True)
        self.assertEqual(txs[0]['value'], '1.0')
        self.assertEqual(txs[0]['fee'], '0.0')

        # verify that the outgoing tip is marked correctly as is_tip=True in account2
        txs2 = await self.out(
            self.daemon.jsonrpc_transaction_list(account2_id)
        )
        self.assertEqual(len(txs2[0]['support_info']), 1)
        self.assertEqual(txs2[0]['support_info'][0]['balance_delta'], '-1.0')
        self.assertEqual(txs2[0]['support_info'][0]['claim_id'], claim['claim_id'])
        self.assertEqual(txs2[0]['support_info'][0]['is_tip'], True)
        self.assertEqual(txs2[0]['value'], '-1.0')
        self.assertEqual(txs2[0]['fee'], '-0.0001415')

        # send a support to the claim using account2
        support = await self.out(
            self.daemon.jsonrpc_claim_new_support('hovercraft', claim['claim_id'], '2.0', account2_id)
        )
        await self.on_transaction_dict(support)
        await self.generate(1)
        await self.on_transaction_dict(support)

        # account2 balance went down ~2
        self.assertEqual('3.979769', await self.daemon.jsonrpc_account_balance())
        self.assertEqual('1.999717', await self.daemon.jsonrpc_account_balance(account2_id))

        # verify that the outgoing support is marked correctly as is_tip=False in account2
        txs2 = await self.out(self.daemon.jsonrpc_transaction_list(account2_id))
        self.assertEqual(len(txs2[0]['support_info']), 1)
        self.assertEqual(txs2[0]['support_info'][0]['balance_delta'], '-2.0')
        self.assertEqual(txs2[0]['support_info'][0]['claim_id'], claim['claim_id'])
        self.assertEqual(txs2[0]['support_info'][0]['is_tip'], False)
        self.assertEqual(txs2[0]['value'], '0.0')
        self.assertEqual(txs2[0]['fee'], '-0.0001415')

    async def test_normalization_resolution(self):

        # this test assumes that the lbrycrd forks normalization at height == 250 on regtest

        c1 = await self.make_claim('ΣίσυφοςﬁÆ', '0.1')
        c2 = await self.make_claim('ΣΊΣΥΦΟσFIæ', '0.2')

        r1 = await self.daemon.jsonrpc_resolve(urls='lbry://ΣίσυφοςﬁÆ')
        r2 = await self.daemon.jsonrpc_resolve(urls='lbry://ΣΊΣΥΦΟσFIæ')

        r1c = list(r1.values())[0]['claim']['claim_id']
        r2c = list(r2.values())[0]['claim']['claim_id']
        self.assertEqual(c1['claim_id'], r1c)
        self.assertEqual(c2['claim_id'], r2c)
        self.assertNotEqual(r1c, r2c)

        await self.generate(50)
        head = await self.daemon.jsonrpc_block_show()
        self.assertTrue(head['height'] > 250)

        r3 = await self.daemon.jsonrpc_resolve(urls='lbry://ΣίσυφοςﬁÆ')
        r4 = await self.daemon.jsonrpc_resolve(urls='lbry://ΣΊΣΥΦΟσFIæ')

        r3c = list(r3.values())[0]['claim']['claim_id']
        r4c = list(r4.values())[0]['claim']['claim_id']
        r3n = list(r3.values())[0]['claim']['name']
        r4n = list(r4.values())[0]['claim']['name']

        self.assertEqual(c2['claim_id'], r3c)
        self.assertEqual(c2['claim_id'], r4c)
        self.assertEqual(r3c, r4c)
        self.assertEqual(r3n, r4n)
