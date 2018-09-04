import json
import tempfile
import logging
import asyncio
from decimal import Decimal
from types import SimpleNamespace

from twisted.internet import defer
from orchstr8.testcase import IntegrationTestCase, d2f

import lbryschema
lbryschema.BLOCKCHAIN_NAME = 'lbrycrd_regtest'

from lbrynet import conf as lbry_conf
from lbrynet.dht.node import Node
from lbrynet.daemon.Daemon import Daemon
from lbrynet.wallet.manager import LbryWalletManager
from lbrynet.daemon.Components import WalletComponent, DHTComponent, HashAnnouncerComponent, \
    ExchangeRateManagerComponent
from lbrynet.daemon.Components import UPnPComponent
from lbrynet.daemon.Components import REFLECTOR_COMPONENT
from lbrynet.daemon.Components import PEER_PROTOCOL_SERVER_COMPONENT
from lbrynet.daemon.ComponentManager import ComponentManager
from lbrynet.daemon.auth.server import jsonrpc_dumps_pretty


log = logging.getLogger(__name__)


class FakeUPnP(UPnPComponent):

    def __init__(self, component_manager):
        self.component_manager = component_manager
        self._running = False
        self.use_upnp = False
        self.upnp_redirects = {}

    def start(self):
        pass

    def stop(self):
        pass


class FakeDHT(DHTComponent):

    def start(self):
        self.dht_node = Node()


class FakeExchangeRateComponent(ExchangeRateManagerComponent):

    def start(self):
        self.exchange_rate_manager = SimpleNamespace()

    def stop(self):
        pass


class FakeHashAnnouncerComponent(HashAnnouncerComponent):

    def start(self):
        self.hash_announcer = SimpleNamespace()

    def stop(self):
        pass


class FakeAnalytics:

    @property
    def is_started(self):
        return True

    def send_new_channel(self):
        pass

    def shutdown(self):
        pass

    def send_claim_action(self, action):
        pass

    def send_credits_sent(self):
        pass


class CommandTestCase(IntegrationTestCase):

    timeout = 180
    WALLET_MANAGER = LbryWalletManager

    async def setUp(self):
        await super().setUp()

        if self.VERBOSE:
            log.setLevel(logging.DEBUG)
            logging.getLogger('lbrynet.core').setLevel(logging.DEBUG)

        lbry_conf.settings = None
        lbry_conf.initialize_settings(load_conf_file=False)
        lbry_conf.settings['data_dir'] = self.stack.wallet.data_path
        lbry_conf.settings['lbryum_wallet_dir'] = self.stack.wallet.data_path
        lbry_conf.settings['download_directory'] = self.stack.wallet.data_path
        lbry_conf.settings['use_upnp'] = False
        lbry_conf.settings['reflect_uploads'] = False
        lbry_conf.settings['blockchain_name'] = 'lbrycrd_regtest'
        lbry_conf.settings['lbryum_servers'] = [('localhost', 50001)]
        lbry_conf.settings['known_dht_nodes'] = []
        lbry_conf.settings.node_id = None

        await d2f(self.account.ensure_address_gap())
        address = (await d2f(self.account.receiving.get_addresses(1, only_usable=True)))[0]
        sendtxid = await self.blockchain.send_to_address(address, 10)
        await self.confirm_tx(sendtxid)
        await self.generate(5)

        def wallet_maker(component_manager):
            self.wallet_component = WalletComponent(component_manager)
            self.wallet_component.wallet_manager = self.manager
            self.wallet_component._running = True
            return self.wallet_component

        skip = [
            #UPNP_COMPONENT,
            PEER_PROTOCOL_SERVER_COMPONENT,
            REFLECTOR_COMPONENT
        ]
        analytics_manager = FakeAnalytics()
        self.daemon = Daemon(analytics_manager, ComponentManager(
            analytics_manager=analytics_manager,
            skip_components=skip, wallet=wallet_maker,
            dht=FakeDHT, hash_announcer=FakeHashAnnouncerComponent,
            exchange_rate_manager=FakeExchangeRateComponent,
            upnp=FakeUPnP
        ))
        await d2f(self.daemon.setup())
        self.daemon.wallet_manager = self.wallet_component.wallet_manager
        self.manager.old_db = self.daemon.storage

    async def tearDown(self):
        await super().tearDown()
        self.wallet_component._running = False
        await d2f(self.daemon._shutdown())

    async def confirm_tx(self, txid):
        """ Wait for tx to be in mempool, then generate a block, wait for tx to be in a block. """
        await self.on_transaction_id(txid)
        await self.generate(1)
        await self.on_transaction_id(txid)

    def d_confirm_tx(self, txid):
        return defer.Deferred.fromFuture(asyncio.ensure_future(self.confirm_tx(txid)))

    async def generate(self, blocks):
        """ Ask lbrycrd to generate some blocks and wait until ledger has them. """
        await self.blockchain.generate(blocks)
        await self.ledger.on_header.where(self.blockchain.is_expected_block)

    def d_generate(self, blocks):
        return defer.Deferred.fromFuture(asyncio.ensure_future(self.generate(blocks)))

    def out(self, d):
        """ Converts Daemon API call results (dictionary)
            to JSON and then back to a dictionary. """
        d.addCallback(lambda o: json.loads(jsonrpc_dumps_pretty(o, ledger=self.ledger))['result'])
        return d


class EpicAdventuresOfChris45(CommandTestCase):
    VERBOSE = False

    @defer.inlineCallbacks
    def test_no_this_is_not_a_test_its_an_adventure(self):
        # Chris45 is an avid user of LBRY and this is his story. It's fact and fiction
        # and everything in between; it's also the setting of some record setting
        # integration tests.

        # Chris45 starts everyday by checking his balance.
        result = yield self.daemon.jsonrpc_account_balance()
        self.assertEqual(result, 10)
        # "10 LBC, yippy! I can do a lot with that.", he thinks to himself,
        # enthusiastically. But he is hungry so he goes into the kitchen
        # to make himself a spamdwich.

        # While making the spamdwich he wonders... has anyone on LBRY
        # registered the @spam channel yet? "I should do that!" he
        # exclaims and goes back to his computer to do just that!
        channel = yield self.out(self.daemon.jsonrpc_channel_new('@spam', 1))
        self.assertTrue(channel['success'])
        yield self.d_confirm_tx(channel['tx']['txid'])

        # Do we have it locally?
        channels = yield self.out(self.daemon.jsonrpc_channel_list())
        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0]['name'], '@spam')
        self.assertTrue(channels[0]['have_certificate'])

        # As the new channel claim travels through the intertubes and makes its
        # way into the mempool and then a block and then into the claimtrie,
        # Chris doesn't sit idly by: he checks his balance!

        result = yield self.daemon.jsonrpc_account_balance()
        self.assertEqual(result, 0)

        # "Oh! No! It's all gone? Did I make a mistake in entering the amount?"
        # exclaims Chris, then he remembers there is a 6 block confirmation window
        # to make sure the TX is really going to stay in the blockchain. And he only
        # had one UTXO that morning.

        # To get the unconfirmed balance he has to pass the '--include-unconfirmed'
        # flag to lbrynet:
        result = yield self.daemon.jsonrpc_account_balance(include_unconfirmed=True)
        self.assertEqual(result, Decimal('8.989893'))
        # "Well, that's a relief." he thinks to himself as he exhales a sigh of relief.

        # He waits for a block
        yield self.d_generate(1)
        # and checks the confirmed balance again.
        result = yield self.daemon.jsonrpc_account_balance()
        self.assertEqual(result, 0)
        # Still zero.

        # But it's only at 2 confirmations, so he waits another 3
        yield self.d_generate(3)
        # and checks again.
        result = yield self.daemon.jsonrpc_account_balance()
        self.assertEqual(result, 0)
        # Still zero.

        # Just one more confirmation
        yield self.d_generate(1)
        # and it should be 6 total, enough to get the correct balance!
        result = yield self.daemon.jsonrpc_account_balance()
        self.assertEqual(result, Decimal('8.989893'))
        # Like a Swiss watch (right niko?) the blockchain never disappoints! We're
        # at 6 confirmations and the total is correct.

        # And is the channel resolvable and empty?
        response = yield self.out(self.daemon.jsonrpc_resolve(uri='lbry://@spam'))
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
            claim1 = yield self.out(self.daemon.jsonrpc_publish(
                'hovercraft', 1, file_path=file.name, channel_name='@spam', channel_id=channel['claim_id']
            ))
            self.assertTrue(claim1['success'])
            yield self.d_confirm_tx(claim1['tx']['txid'])

        # He quickly checks the unconfirmed balance to make sure everything looks
        # correct.
        result = yield self.daemon.jsonrpc_account_balance(include_unconfirmed=True)
        self.assertEqual(result, Decimal('7.969786'))

        # Also checks that his new story can be found on the blockchain before
        # giving the link to all his friends.
        response = yield self.out(self.daemon.jsonrpc_resolve(uri='lbry://@spam/hovercraft'))
        self.assertIn('lbry://@spam/hovercraft', response)
        self.assertIn('claim', response['lbry://@spam/hovercraft'])

        # He goes to tell everyone about it and in the meantime 5 blocks are confirmed.
        yield self.d_generate(5)
        # When he comes back he verifies the confirmed balance.
        result = yield self.daemon.jsonrpc_account_balance()
        self.assertEqual(result, Decimal('7.969786'))

        # As people start reading his story they discover some typos and notify
        # Chris who explains in despair "Oh! Noooooos!" but then remembers
        # "No big deal! I can update my claim." And so he updates his claim.
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'blah blah blah...')
            file.write(b'[typo fixing sounds being made]')
            file.write(b'yada yada yada!')
            file.flush()
            claim2 = yield self.out(self.daemon.jsonrpc_publish(
                'hovercraft', 1, file_path=file.name, channel_name='@spam', channel_id=channel['claim_id']
            ))
            self.assertTrue(claim2['success'])
            self.assertEqual(claim2['claim_id'], claim1['claim_id'])
            yield self.d_confirm_tx(claim2['tx']['txid'])

        # After some soul searching Chris decides that his story needs more
        # heart and a better ending. He takes down the story and begins the rewrite.
        abandon = yield self.out(self.daemon.jsonrpc_claim_abandon(claim1['claim_id']))
        self.assertTrue(abandon['success'])
        yield self.d_confirm_tx(abandon['tx']['txid'])

        # And now check that the claim doesn't resolve anymore.
        response = yield self.out(self.daemon.jsonrpc_resolve(uri='lbry://@spam/hovercraft'))
        self.assertNotIn('claim', response['lbry://@spam/hovercraft'])

        # After abandoning he just waits for his LBCs to be returned to his account
        yield self.d_generate(5)
        result = yield self.daemon.jsonrpc_account_balance()
        self.assertEqual(result, Decimal('8.9693585'))

        # Amidst all this Chris receives a call from his friend Ramsey
        # who says that it is of utmost urgency that Chris transfer him
        # 1 LBC to which Chris readily obliges
        ramsey_account_id = (yield self.daemon.jsonrpc_account_create("Ramsey"))['id']
        ramsey_account = self.daemon.get_account_or_error('', ramsey_account_id)
        ramsey_address = yield ramsey_account.receiving.get_or_create_usable_address()
        result = yield self.out(self.daemon.jsonrpc_wallet_send(1, ramsey_address))
        self.assertIn("txid", result)
        yield self.d_confirm_tx(result['txid'])

        # Chris then eagerly waits for 6 confirmations to check his balance and then calls Ramsey to verify whether
        # he received it or not
        yield self.d_generate(5)
        result = yield self.daemon.jsonrpc_account_balance()
        # Chris' balance was correct
        self.assertEqual(result, Decimal('7.9692345'))

        # Ramsey too assured him that he had received the 1 LBC and thanks him
        result = yield self.daemon.jsonrpc_account_balance(ramsey_account_id)
        self.assertEqual(result, Decimal('1.0'))

        # After Chris is done with all the "helping other people" stuff he decides that it's time to
        # write a new story and publish it to lbry. All he needed was a fresh start and he came up with:
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'Amazingly Original First Line')
            file.write(b'Super plot for the grand novel')
            file.write(b'Totally un-cliched ending')
            file.write(b'**Audience Gasps**')
            file.flush()
            claim3 = yield self.out(self.daemon.jsonrpc_publish(
                'fresh-start', 1, file_path=file.name, channel_name='@spam', channel_id=channel['claim_id']
            ))
            self.assertTrue(claim3['success'])
            yield self.d_confirm_tx(claim3['tx']['txid'])

        yield self.d_generate(5)

        # He gives the link of his story to all his friends and hopes that this is the much needed break for him
        uri = 'lbry://@spam/fresh-start'

        # And voila, and bravo and encore! His Best Friend Ramsey read the story and immediately knew this was a hit
        # Now to keep this claim winning on the lbry blockchain he immediately supports the claim
        tx = yield self.out(self.daemon.jsonrpc_claim_new_support(
            'fresh-start', claim3['claim_id'], 0.2, account_id=ramsey_account_id
        ))
        yield self.d_confirm_tx(tx['txid'])

        # And check if his support showed up
        resolve_result = yield self.out(self.daemon.jsonrpc_resolve(uri=uri))
        # It obviously did! Because, blockchain baby \O/
        self.assertEqual(resolve_result[uri]['claim']['supports'][0]['amount'], 0.2)
        self.assertEqual(resolve_result[uri]['claim']['supports'][0]['txid'], tx['txid'])
        yield self.d_generate(5)

        # Now he also wanted to support the original creator of the Award Winning Novel
        # So he quickly decides to send a tip to him
        tx = yield self.out(
            self.daemon.jsonrpc_claim_tip(claim3['claim_id'], 0.3, account_id=ramsey_account_id))
        yield self.d_confirm_tx(tx['txid'])

        # And again checks if it went to the just right place
        resolve_result = yield self.out(self.daemon.jsonrpc_resolve(uri=uri))
        # Which it obviously did. Because....?????
        self.assertEqual(resolve_result[uri]['claim']['supports'][1]['amount'], 0.3)
        self.assertEqual(resolve_result[uri]['claim']['supports'][1]['txid'], tx['txid'])
        yield self.d_generate(5)

        # Seeing the ravishing success of his novel Chris adds support to his claim too
        tx = yield self.out(self.daemon.jsonrpc_claim_new_support('fresh-start', claim3['claim_id'], 0.4))
        yield self.d_confirm_tx(tx['txid'])

        # And check if his support showed up
        resolve_result = yield self.out(self.daemon.jsonrpc_resolve(uri=uri))
        # It did!
        self.assertEqual(resolve_result[uri]['claim']['supports'][2]['amount'], 0.4)
        self.assertEqual(resolve_result[uri]['claim']['supports'][2]['txid'], tx['txid'])
        yield self.d_generate(5)


class AccountManagement(CommandTestCase):

    VERBOSE = False

    @defer.inlineCallbacks
    def test_performing_account_management_commands(self):
        # check initial account
        response = yield self.daemon.jsonrpc_account_list()
        self.assertEqual(len(response['lbc_regtest']), 1)

        # change account name and gap
        account_id = response['lbc_regtest'][0]['id']
        yield self.daemon.jsonrpc_account_set(
            account_id=account_id, new_name='test account',
            receiving_gap=95, receiving_max_uses=96,
            change_gap=97, change_max_uses=98
        )
        response = (yield self.daemon.jsonrpc_account_list())['lbc_regtest'][0]
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
        yield self.daemon.jsonrpc_account_create('second account')
        response = yield self.daemon.jsonrpc_account_list()
        self.assertEqual(len(response['lbc_regtest']), 2)
        self.assertEqual(response['lbc_regtest'][1]['name'], 'second account')
        account_id2 = response['lbc_regtest'][1]['id']

        # make new account the default
        self.daemon.jsonrpc_account_set(account_id=account_id2, default=True)
        response = yield self.daemon.jsonrpc_account_list(show_seed=True)
        self.assertEqual(response['lbc_regtest'][0]['name'], 'second account')

        account_seed = response['lbc_regtest'][1]['seed']

        # remove account
        yield self.daemon.jsonrpc_account_remove(response['lbc_regtest'][1]['id'])
        response = yield self.daemon.jsonrpc_account_list()
        self.assertEqual(len(response['lbc_regtest']), 1)

        # add account
        yield self.daemon.jsonrpc_account_add('recreated account', seed=account_seed)
        response = yield self.daemon.jsonrpc_account_list()
        self.assertEqual(len(response['lbc_regtest']), 2)
        self.assertEqual(response['lbc_regtest'][1]['name'], 'recreated account')

        # list specific account
        response = yield self.daemon.jsonrpc_account_list(account_id, include_claims=True)
        self.assertEqual(response['name'], 'recreated account')
