import json
import tempfile
import logging
import asyncio
from types import SimpleNamespace

from twisted.internet import defer
from orchstr8.testcase import IntegrationTestCase, d2f

import lbryschema
lbryschema.BLOCKCHAIN_NAME = 'lbrycrd_regtest'

from lbrynet import conf as lbry_conf
from lbrynet.dht.node import Node
from lbrynet.daemon.Daemon import Daemon
from lbrynet.wallet.manager import LbryWalletManager
from lbrynet.daemon.Components import WalletComponent, DHTComponent, HashAnnouncerComponent, ExchangeRateManagerComponent
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


class CommandTestCase(IntegrationTestCase):

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
        #for component in skip:
        #    self.daemon.component_attributes.pop(component, None)
        await d2f(self.daemon.setup())
        self.daemon.wallet_manager = self.wallet_component.wallet
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
        result = yield self.daemon.jsonrpc_wallet_balance()
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

        result = yield self.daemon.jsonrpc_wallet_balance()
        self.assertEqual(result, 0)

        # "Oh! No! It's all gone? Did I make a mistake in entering the amount?"
        # exclaims Chris, then he remembers there is a 6 block confirmation window
        # to make sure the TX is really going to stay in the blockchain. And he only
        # had one UTXO that morning.

        # To get the unconfirmed balance he has to pass the '--include-unconfirmed'
        # flag to lbrynet:
        result = yield self.daemon.jsonrpc_wallet_balance(include_unconfirmed=True)
        self.assertEqual(result, 8.99)
        # "Well, that's a relief." he thinks to himself as he exhales a sigh of relief.

        # He waits for a block
        yield self.d_generate(1)
        # and checks the confirmed balance again.
        result = yield self.daemon.jsonrpc_wallet_balance()
        self.assertEqual(result, 0)
        # Still zero.

        # But it's only at 2 confirmations, so he waits another 3
        yield self.d_generate(3)
        # and checks again.
        result = yield self.daemon.jsonrpc_wallet_balance()
        self.assertEqual(result, 0)
        # Still zero.

        # Just one more confirmation
        yield self.d_generate(1)
        # and it should be 6 total, enough to get the correct balance!
        result = yield self.daemon.jsonrpc_wallet_balance()
        self.assertEqual(result, 8.99)
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
        result = yield self.daemon.jsonrpc_wallet_balance(include_unconfirmed=True)
        self.assertEqual(round(result, 2), 7.97)

        # Also checks that his new story can be found on the blockchain before
        # giving the link to all his friends.
        response = yield self.out(self.daemon.jsonrpc_resolve(uri='lbry://@spam/hovercraft'))
        self.assertIn('lbry://@spam/hovercraft', response)
        self.assertIn('claim', response['lbry://@spam/hovercraft'])

        # He goes to tell everyone about it and in the meantime 5 blocks are confirmed.
        yield self.d_generate(5)
        # When he comes back he verifies the confirmed balance.
        result = yield self.daemon.jsonrpc_wallet_balance()
        self.assertEqual(round(result, 2), 7.97)

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
