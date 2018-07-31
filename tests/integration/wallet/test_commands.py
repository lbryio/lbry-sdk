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
from lbrynet.daemon.Components import REFLECTOR_COMPONENT, HASH_ANNOUNCER_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT
from lbrynet.daemon.Components import UPNP_COMPONENT
from lbrynet.daemon.ComponentManager import ComponentManager


log = logging.getLogger(__name__)


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

        def wallet_maker(component_manager):
            self.wallet_component = WalletComponent(component_manager)
            self.wallet_component.wallet = self.manager
            self.wallet_component._running = True
            return self.wallet_component

        analytics_manager = FakeAnalytics()
        self.daemon = Daemon(analytics_manager, ComponentManager(
            analytics_manager,
            skip_components=[
                #UPNP_COMPONENT,
                REFLECTOR_COMPONENT,
                #HASH_ANNOUNCER_COMPONENT,
                #EXCHANGE_RATE_MANAGER_COMPONENT
            ],
            dht=FakeDHT, wallet=wallet_maker,
            hash_announcer=FakeHashAnnouncerComponent,
            exchange_rate_manager=FakeExchangeRateComponent
        ))
        await d2f(self.daemon.setup())
        self.manager.old_db = self.daemon.session.storage

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


class CommonWorkflowTests(CommandTestCase):

    VERBOSE = False

    @defer.inlineCallbacks
    def test_user_creating_channel_and_publishing_file(self):

        # User checks their balance.
        result = yield self.daemon.jsonrpc_wallet_balance(include_unconfirmed=True)
        self.assertEqual(result, 10)

        # Decides to get a cool new channel.
        channel = yield self.daemon.jsonrpc_channel_new('@spam', 1)
        self.assertTrue(channel['success'])
        yield self.d_confirm_tx(channel['txid'])

        # Check balance, include utxos with less than 6 confirmations (unconfirmed).
        result = yield self.daemon.jsonrpc_wallet_balance(include_unconfirmed=True)
        self.assertEqual(result, 8.99)

        # Check confirmed balance, only includes utxos with 6+ confirmations.
        result = yield self.daemon.jsonrpc_wallet_balance()
        self.assertEqual(result, 0)

        # Add some confirmations (there is already 1 confirmation, so we add 5 to equal 6 total).
        yield self.d_generate(5)

        # Check balance again after some confirmations, should be correct again.
        result = yield self.daemon.jsonrpc_wallet_balance()
        self.assertEqual(result, 8.99)

        # Now lets publish a hello world file to the channel.
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'hello world!')
            file.flush()
            claim = yield self.daemon.jsonrpc_publish(
                'hovercraft', 1, file_path=file.name, channel_name='@spam', channel_id=channel['claim_id']
            )
            self.assertTrue(claim['success'])
            yield self.d_confirm_tx(claim['txid'])

        # Check unconfirmed balance.
        result = yield self.daemon.jsonrpc_wallet_balance(include_unconfirmed=True)
        self.assertEqual(round(result, 2), 7.97)

        # Resolve our claim.
        response = yield self.ledger.resolve(0, 10, 'lbry://@spam/hovercraft')
        self.assertIn('lbry://@spam/hovercraft', response)

        # A few confirmations before trying to spend again.
        yield self.d_generate(5)

        # Verify confirmed balance.
        result = yield self.daemon.jsonrpc_wallet_balance()
        self.assertEqual(round(result, 2), 7.97)

        # Now lets update an existing claim.
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'hello world x2!')
            file.flush()
            claim = yield self.daemon.jsonrpc_publish(
                'hovercraft', 1, file_path=file.name, channel_name='@spam', channel_id=channel['claim_id']
            )
            self.assertTrue(claim['success'])
            yield self.d_confirm_tx(claim['txid'])
