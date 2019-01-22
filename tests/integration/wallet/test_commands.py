import sys
import json
import tempfile
import logging
from binascii import unhexlify

import twisted.internet
from twisted.internet.asyncioreactor import AsyncioSelectorReactor

from lbrynet.extras.wallet.transaction import Transaction
from lbrynet.p2p.Error import InsufficientFundsError
from lbrynet.schema.claim import ClaimDict

from torba.testcase import IntegrationTestCase

import lbrynet.schema
lbrynet.schema.BLOCKCHAIN_NAME = 'lbrycrd_regtest'

from lbrynet.conf import Config
from lbrynet.extras.daemon.Daemon import Daemon, jsonrpc_dumps_pretty
from lbrynet.extras.wallet import LbryWalletManager
from lbrynet.extras.daemon.Components import WalletComponent
from lbrynet.extras.daemon.Components import (
    DHT_COMPONENT, HASH_ANNOUNCER_COMPONENT, PEER_PROTOCOL_SERVER_COMPONENT,
    REFLECTOR_COMPONENT, UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT
)
from lbrynet.extras.daemon.ComponentManager import ComponentManager


class FakeAnalytics:

    @property
    def is_started(self):
        return True

    async def send_new_channel(self):
        pass

    def shutdown(self):
        pass

    async def send_claim_action(self, action):
        pass

    async def send_credits_sent(self):
        pass

    async def send_server_startup(self):
        pass


class CommandTestCase(IntegrationTestCase):

    timeout = 180
    MANAGER = LbryWalletManager
    VERBOSITY = logging.WARN

    async def asyncSetUp(self):
        await super().asyncSetUp()

        twisted.internet.reactor = sys.modules['twisted.internet.reactor'] = AsyncioSelectorReactor()

        logging.getLogger('lbrynet.p2p').setLevel(self.VERBOSITY)
        logging.getLogger('lbrynet.daemon').setLevel(self.VERBOSITY)

        conf = Config()
        conf.data_dir = self.wallet_node.data_path
        conf.wallet_dir = self.wallet_node.data_path
        conf.download_dir = self.wallet_node.data_path
        conf.share_usage_data = False
        conf.use_upnp = False
        conf.reflect_uploads = False
        conf.blockchain_name = 'lbrycrd_regtest'
        conf.lbryum_servers = [('localhost', 50001)]
        conf.known_dht_nodes = []

        await self.account.ensure_address_gap()
        address = (await self.account.receiving.get_addresses(limit=1, only_usable=True))[0]
        sendtxid = await self.blockchain.send_to_address(address, 10)
        await self.confirm_tx(sendtxid)
        await self.generate(5)

        def wallet_maker(component_manager):
            self.wallet_component = WalletComponent(component_manager)
            self.wallet_component.wallet_manager = self.manager
            self.wallet_component._running = True
            return self.wallet_component

        conf.components_to_skip = [
            DHT_COMPONENT, UPNP_COMPONENT, HASH_ANNOUNCER_COMPONENT,
            PEER_PROTOCOL_SERVER_COMPONENT, REFLECTOR_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT
        ]
        self.daemon = Daemon(conf, ComponentManager(
            conf, skip_components=conf.components_to_skip, wallet=wallet_maker
        ))
        await self.daemon.setup()
        self.daemon.wallet_manager = self.wallet_component.wallet_manager
        self.manager.old_db = self.daemon.storage

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.wallet_component._running = False
        await self.daemon.shutdown()

    async def confirm_tx(self, txid):
        """ Wait for tx to be in mempool, then generate a block, wait for tx to be in a block. """
        await self.on_transaction_id(txid)
        await self.generate(1)
        await self.on_transaction_id(txid)

    async def on_transaction_dict(self, tx):
        await self.ledger.wait(
            self.ledger.transaction_class(unhexlify(tx['hex']))
        )

    @staticmethod
    def get_all_addresses(tx):
        addresses = set()
        for txi in tx['inputs']:
            addresses.add(txi['address'])
        for txo in tx['outputs']:
            addresses.add(txo['address'])
        return list(addresses)

    async def generate(self, blocks):
        """ Ask lbrycrd to generate some blocks and wait until ledger has them. """
        await self.blockchain.generate(blocks)
        await self.ledger.on_header.where(self.blockchain.is_expected_block)

    async def out(self, awaitable):
        """ Converts Daemon API call results (dictionary)
            to JSON and then back to a dictionary. """
        return json.loads(jsonrpc_dumps_pretty(await awaitable, ledger=self.ledger))['result']


class EpicAdventuresOfChris45(CommandTestCase):

    VERBOSITY = logging.WARN

    async def test_no_this_is_not_a_test_its_an_adventure(self):
        # Chris45 is an avid user of LBRY and this is his story. It's fact and fiction
        # and everything in between; it's also the setting of some record setting
        # integration tests.

        # Chris45 starts everyday by checking his balance.
        result = await self.daemon.jsonrpc_account_balance()
        self.assertEqual(result, '10.0')
        # "10 LBC, yippy! I can do a lot with that.", he thinks to himself,
        # enthusiastically. But he is hungry so he goes into the kitchen
        # to make himself a spamdwich.

        # While making the spamdwich he wonders... has anyone on LBRY
        # registered the @spam channel yet? "I should do that!" he
        # exclaims and goes back to his computer to do just that!
        channel = await self.out(self.daemon.jsonrpc_channel_new('@spam', "1.0"))
        self.assertTrue(channel['success'])
        await self.confirm_tx(channel['tx']['txid'])

        # Do we have it locally?
        channels = await self.out(self.daemon.jsonrpc_channel_list())
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0]['name'], '@spam')

        # As the new channel claim travels through the intertubes and makes its
        # way into the mempool and then a block and then into the claimtrie,
        # Chris doesn't sit idly by: he checks his balance!

        result = await self.daemon.jsonrpc_account_balance()
        self.assertEqual(result, '8.989893')

        # He waits for 6 more blocks (confirmations) to make sure the balance has been settled.
        await self.generate(6)
        result = await self.daemon.jsonrpc_account_balance(confirmations=6)
        self.assertEqual(result, '8.989893')

        # And is the channel resolvable and empty?
        response = await self.out(self.daemon.jsonrpc_resolve(uri='lbry://@spam'))
        self.assertIn('lbry://@spam', response)
        self.assertIn('certificate', response['lbry://@spam'])

        # "What goes well with spam?" ponders Chris...
        # "A hovercraft with eels!" he exclaims.
        # "That's what goes great with spam!" he further confirms.

        # And so, many hours later, Chris is finished writing his epic story
        # about eels driving a hovercraft across the wetlands while eating spam
        # and decides it's time to publish it to the @spam channel.
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'blah blah blah...')
            file.write(b'[insert long story about eels driving hovercraft]')
            file.write(b'yada yada yada!')
            file.write(b'the end')
            file.flush()
            claim1 = await self.out(self.daemon.jsonrpc_publish(
                'hovercraft', '1.0', file_path=file.name, channel_id=channel['claim_id']
            ))
            self.assertTrue(claim1['success'])
            await self.confirm_tx(claim1['tx']['txid'])

        # He quickly checks the unconfirmed balance to make sure everything looks
        # correct.
        result = await self.daemon.jsonrpc_account_balance()
        self.assertEqual(result, '7.969786')

        # Also checks that his new story can be found on the blockchain before
        # giving the link to all his friends.
        response = await self.out(self.daemon.jsonrpc_resolve(uri='lbry://@spam/hovercraft'))
        self.assertIn('lbry://@spam/hovercraft', response)
        self.assertIn('claim', response['lbry://@spam/hovercraft'])

        # He goes to tell everyone about it and in the meantime 5 blocks are confirmed.
        await self.generate(5)
        # When he comes back he verifies the confirmed balance.
        result = await self.daemon.jsonrpc_account_balance()
        self.assertEqual(result, '7.969786')

        # As people start reading his story they discover some typos and notify
        # Chris who explains in despair "Oh! Noooooos!" but then remembers
        # "No big deal! I can update my claim." And so he updates his claim.
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'blah blah blah...')
            file.write(b'[typo fixing sounds being made]')
            file.write(b'yada yada yada!')
            file.flush()
            claim2 = await self.out(self.daemon.jsonrpc_publish(
                'hovercraft', '1.0', file_path=file.name, channel_name='@spam'
            ))
            self.assertTrue(claim2['success'])
            self.assertEqual(claim2['claim_id'], claim1['claim_id'])
            await self.confirm_tx(claim2['tx']['txid'])

        # After some soul searching Chris decides that his story needs more
        # heart and a better ending. He takes down the story and begins the rewrite.
        abandon = await self.out(self.daemon.jsonrpc_claim_abandon(claim1['claim_id'], blocking=False))
        self.assertTrue(abandon['success'])
        await self.confirm_tx(abandon['tx']['txid'])

        # And now checks that the claim doesn't resolve anymore.
        response = await self.out(self.daemon.jsonrpc_resolve(uri='lbry://@spam/hovercraft'))
        self.assertNotIn('claim', response['lbry://@spam/hovercraft'])

        # After abandoning he just waits for his LBCs to be returned to his account
        await self.generate(5)
        result = await self.daemon.jsonrpc_account_balance()
        self.assertEqual(result, '8.9693585')

        # Amidst all this Chris receives a call from his friend Ramsey
        # who says that it is of utmost urgency that Chris transfer him
        # 1 LBC to which Chris readily obliges
        ramsey_account_id = (await self.daemon.jsonrpc_account_create("Ramsey"))['id']
        ramsey_account = self.daemon.get_account_or_error(ramsey_account_id)
        ramsey_address = await self.daemon.jsonrpc_address_unused(ramsey_account_id)
        result = await self.out(self.daemon.jsonrpc_wallet_send('1.0', ramsey_address))
        self.assertIn("txid", result)
        await self.confirm_tx(result['txid'])

        # Chris then eagerly waits for 6 confirmations to check his balance and then calls Ramsey to verify whether
        # he received it or not
        await self.generate(5)
        result = await self.daemon.jsonrpc_account_balance()
        # Chris' balance was correct
        self.assertEqual(result, '7.9692345')

        # Ramsey too assured him that he had received the 1 LBC and thanks him
        result = await self.daemon.jsonrpc_account_balance(ramsey_account_id)
        self.assertEqual(result, '1.0')

        # After Chris is done with all the "helping other people" stuff he decides that it's time to
        # write a new story and publish it to lbry. All he needed was a fresh start and he came up with:
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'Amazingly Original First Line')
            file.write(b'Super plot for the grand novel')
            file.write(b'Totally un-cliched ending')
            file.write(b'**Audience Gasps**')
            file.flush()
            claim3 = await self.out(self.daemon.jsonrpc_publish(
                'fresh-start', '1.0', file_path=file.name, channel_name='@spam'
            ))
            self.assertTrue(claim3['success'])
            await self.confirm_tx(claim3['tx']['txid'])

        await self.generate(5)

        # He gives the link of his story to all his friends and hopes that this is the much needed break for him
        uri = 'lbry://@spam/fresh-start'

        # And voila, and bravo and encore! His Best Friend Ramsey read the story and immediately knew this was a hit
        # Now to keep this claim winning on the lbry blockchain he immediately supports the claim
        tx = await self.out(self.daemon.jsonrpc_claim_new_support(
            'fresh-start', claim3['claim_id'], '0.2', account_id=ramsey_account_id
        ))
        await self.confirm_tx(tx['txid'])

        # And check if his support showed up
        resolve_result = await self.out(self.daemon.jsonrpc_resolve(uri=uri))
        # It obviously did! Because, blockchain baby \O/
        self.assertEqual(resolve_result[uri]['claim']['amount'], '1.0')
        self.assertEqual(resolve_result[uri]['claim']['effective_amount'], '1.2')
        self.assertEqual(resolve_result[uri]['claim']['supports'][0]['amount'], '0.2')
        self.assertEqual(resolve_result[uri]['claim']['supports'][0]['txid'], tx['txid'])
        await self.generate(5)

        # Now he also wanted to support the original creator of the Award Winning Novel
        # So he quickly decides to send a tip to him
        tx = await self.out(
            self.daemon.jsonrpc_claim_tip(claim3['claim_id'], '0.3', account_id=ramsey_account_id))
        await self.confirm_tx(tx['txid'])

        # And again checks if it went to the just right place
        resolve_result = await self.out(self.daemon.jsonrpc_resolve(uri=uri))
        # Which it obviously did. Because....?????
        self.assertEqual(resolve_result[uri]['claim']['supports'][1]['amount'], '0.3')
        self.assertEqual(resolve_result[uri]['claim']['supports'][1]['txid'], tx['txid'])
        await self.generate(5)

        # Seeing the ravishing success of his novel Chris adds support to his claim too
        tx = await self.out(self.daemon.jsonrpc_claim_new_support('fresh-start', claim3['claim_id'], '0.4'))
        await self.confirm_tx(tx['txid'])

        # And check if his support showed up
        resolve_result = await self.out(self.daemon.jsonrpc_resolve(uri=uri))
        # It did!
        self.assertEqual(resolve_result[uri]['claim']['supports'][2]['amount'], '0.4')
        self.assertEqual(resolve_result[uri]['claim']['supports'][2]['txid'], tx['txid'])
        await self.generate(5)

        # Now Ramsey who is a singer by profession, is preparing for his new "gig". He has everything in place for that
        # the instruments, the theatre, the ads, everything, EXCEPT lyrics!! He panicked.. But then he remembered
        # something, so he un-panicked. He quickly calls up his best bud Chris and requests him to write hit lyrics for
        # his song, seeing as his novel had smashed all the records, he was the perfect candidate!
        # .......
        # Chris agrees.. 17 hours 43 minutes and 14 seconds later, he makes his publish
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'The Whale amd The Bookmark')
            file.write(b'I know right? Totally a hit song')
            file.write(b'That\'s what goes around for songs these days anyways')
            file.flush()
            claim4 = await self.out(self.daemon.jsonrpc_publish(
                'hit-song', '1.0', file_path=file.name, channel_id=channel['claim_id']
            ))
            self.assertTrue(claim4['success'])
            await self.confirm_tx(claim4['tx']['txid'])

        await self.generate(5)

        # He sends the link to Ramsey, all happy and proud
        uri = 'lbry://@spam/hit-song'

        # But sadly Ramsey wasn't so pleased. It was hard for him to tell Chris...
        # Chris, though a bit heartbroken, abandoned the claim for now, but instantly started working on new hit lyrics
        abandon = await self.out(self.daemon.jsonrpc_claim_abandon(txid=claim4['tx']['txid'], nout=0, blocking=False))
        self.assertTrue(abandon['success'])
        await self.confirm_tx(abandon['tx']['txid'])

        # He them checks that the claim doesn't resolve anymore.
        response = await self.out(self.daemon.jsonrpc_resolve(uri=uri))
        self.assertNotIn('claim', response[uri])


class AccountManagement(CommandTestCase):

    VERBOSE = False

    async def test_performing_account_management_commands(self):
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


class ClaimManagement(CommandTestCase):

    VERBOSITY = logging.WARN

    async def make_claim(self, name='hovercraft', amount='1.0', data=b'hi!', channel_name=None, confirm=True):
        with tempfile.NamedTemporaryFile() as file:
            file.write(data)
            file.flush()
            claim = await self.out(self.daemon.jsonrpc_publish(
                name, amount, file_path=file.name, channel_name=channel_name
            ))
            self.assertTrue(claim['success'])
            if confirm:
                await self.on_transaction_dict(claim['tx'])
                await self.generate(1)
                await self.on_transaction_dict(claim['tx'])
            return claim

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
        self.assertEqual('10.0', await self.daemon.jsonrpc_account_balance())

        claim = await self.make_claim(amount='2.5')  # creates new claim
        txs = await self.out(self.daemon.jsonrpc_transaction_list())
        self.assertEqual(len(txs[0]['claim_info']), 1)
        self.assertEqual(txs[0]['confirmations'], 1)
        self.assertEqual(txs[0]['claim_info'][0]['balance_delta'], '-2.5')
        self.assertEqual(txs[0]['claim_info'][0]['claim_id'], claim['claim_id'])
        self.assertEqual(txs[0]['value'], '0.0')
        self.assertEqual(txs[0]['fee'], '-0.020107')
        self.assertEqual('7.479893', await self.daemon.jsonrpc_account_balance())

        await self.make_claim(amount='1.0')  # updates previous claim
        txs = await self.out(self.daemon.jsonrpc_transaction_list())
        self.assertEqual(len(txs[0]['update_info']), 1)
        self.assertEqual(txs[0]['update_info'][0]['balance_delta'], '1.5')
        self.assertEqual(txs[0]['update_info'][0]['claim_id'], claim['claim_id'])
        self.assertEqual(txs[0]['value'], '0.0')
        self.assertEqual(txs[0]['fee'], '-0.0001985')
        self.assertEqual('8.9796945', await self.daemon.jsonrpc_account_balance())

        await self.out(self.daemon.jsonrpc_claim_abandon(claim['claim_id']))
        txs = await self.out(self.daemon.jsonrpc_transaction_list())
        self.assertEqual(len(txs[0]['abandon_info']), 1)
        self.assertEqual(txs[0]['abandon_info'][0]['balance_delta'], '1.0')
        self.assertEqual(txs[0]['abandon_info'][0]['claim_id'], claim['claim_id'])
        self.assertEqual(txs[0]['value'], '0.0')
        self.assertEqual(txs[0]['fee'], '-0.000107')
        self.assertEqual('9.9795875', await self.daemon.jsonrpc_account_balance())

    async def test_update_claim_holding_address(self):
        other_account_id = (await self.daemon.jsonrpc_account_create('second account'))['id']
        other_account = self.daemon.get_account_or_error(other_account_id)
        other_address = await other_account.receiving.get_or_create_usable_address()

        self.assertEqual('10.0', await self.daemon.jsonrpc_account_balance())

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
        self.assertEqual('10.0', await self.daemon.jsonrpc_account_balance())

        await self.make_claim(amount='9.0')
        self.assertEqual('0.979893', await self.daemon.jsonrpc_account_balance())

        # update the same claim
        await self.make_claim(amount='9.0')
        self.assertEqual('0.9796205', await self.daemon.jsonrpc_account_balance())

        # update the claim a second time but use even more funds
        await self.make_claim(amount='9.97')
        self.assertEqual('0.009348', await self.daemon.jsonrpc_account_balance())

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
        self.assertEqual('10.0', await self.daemon.jsonrpc_account_balance())
        claim = await self.make_claim(amount='0.0001')
        self.assertEqual('9.979793', await self.daemon.jsonrpc_account_balance())
        await self.out(self.daemon.jsonrpc_claim_abandon(claim['claim_id']))
        self.assertEqual('9.97968399', await self.daemon.jsonrpc_account_balance())

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
        response = await self.out(self.daemon.jsonrpc_resolve(uri='lbry://@abc/on-channel-claim'))
        self.assertNotIn('claim', response['lbry://@abc/on-channel-claim'])
        response = await self.out(self.daemon.jsonrpc_resolve(uri='lbry://on-channel-claim'))
        self.assertIn('claim', response['lbry://on-channel-claim'])
        self.assertFalse(response['lbry://on-channel-claim']['claim']['signature_is_valid'])
        direct_uri = 'lbry://on-channel-claim#' + claim['claim_id']
        response = await self.out(self.daemon.jsonrpc_resolve(uri=direct_uri))
        self.assertIn('claim', response[direct_uri])
        self.assertFalse(response[direct_uri]['claim']['signature_is_valid'])

        uri = 'lbry://@abc/on-channel-claim'
        # now, claim something on this channel (it will update the invalid claim, but we save and forcefully restore)
        original_claim = await self.make_claim(amount='0.00000001', name='on-channel-claim', channel_name='@abc')
        self.assertTrue(original_claim['success'])
        # resolves normally
        response = await self.out(self.daemon.jsonrpc_resolve(uri=uri))
        self.assertIn('claim', response[uri])
        self.assertTrue(response[uri]['claim']['signature_is_valid'])

        # tamper it, invalidating the signature
        value = response[uri]['claim']['value'].copy()
        value['stream']['metadata']['author'] = 'some troll'
        address = response[uri]['claim']['address']
        await self.craft_claim('on-channel-claim', 1, value, address)
        # it resolves to the now only valid claim under the channel, ignoring the fake one
        response = await self.out(self.daemon.jsonrpc_resolve(uri=uri))
        self.assertIn('claim', response[uri])
        self.assertTrue(response[uri]['claim']['signature_is_valid'])

        # ooops! claimed a valid conflict! (this happens on the wild, mostly by accident or race condition)
        await self.craft_claim('on-channel-claim', 1, response[uri]['claim']['value'], address)

        # it still resolves! but to the older claim
        response = await self.out(self.daemon.jsonrpc_resolve(uri=uri))
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


class TransactionCommandsTestCase(CommandTestCase):

    async def test_transaction_show(self):
        # local tx
        result = await self.out(self.daemon.jsonrpc_wallet_send(
            '5.0', await self.daemon.jsonrpc_address_unused(self.account.id)
        ))
        await self.confirm_tx(result['txid'])
        tx = await self.daemon.jsonrpc_transaction_show(result['txid'])
        self.assertEqual(tx.id, result['txid'])

        # someone's tx
        change_address = await self.blockchain.get_raw_change_address()
        sendtxid = await self.blockchain.send_to_address(change_address, 10)
        tx = await self.daemon.jsonrpc_transaction_show(sendtxid)
        self.assertEqual(tx.id, sendtxid)
        self.assertEqual(tx.height, -2)
        await self.generate(1)
        tx = await self.daemon.jsonrpc_transaction_show(sendtxid)
        self.assertEqual(tx.height, self.ledger.headers.height)

        # inexistent
        result = await self.daemon.jsonrpc_transaction_show('0'*64)
        self.assertFalse(result['success'])

    async def test_utxo_release(self):
        sendtxid = await self.blockchain.send_to_address(
            await self.account.receiving.get_or_create_usable_address(), 1
        )
        await self.confirm_tx(sendtxid)
        await self.assertBalance(self.account, '11.0')
        await self.ledger.reserve_outputs(await self.account.get_utxos())
        await self.assertBalance(self.account, '0.0')
        await self.daemon.jsonrpc_utxo_release()
        await self.assertBalance(self.account, '11.0')
