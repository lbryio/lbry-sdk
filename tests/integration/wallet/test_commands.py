import types

from twisted.internet import defer
from orchstr8.testcase import IntegrationTestCase, d2f
from torba.constants import COIN

import lbryschema
lbryschema.BLOCKCHAIN_NAME = 'lbrycrd_regtest'

from lbrynet import conf as lbry_conf
from lbrynet.daemon.Daemon import Daemon
from lbrynet.wallet.manager import LbryWalletManager
from lbrynet.daemon.Components import WalletComponent, FileManager, SessionComponent
from lbrynet.file_manager.EncryptedFileManager import EncryptedFileManager


class FakeAnalytics:
    def send_new_channel(self):
        pass

    def shutdown(self):
        pass


class FakeSession:
    storage = None


class CommandTestCase(IntegrationTestCase):

    WALLET_MANAGER = LbryWalletManager

    async def setUp(self):
        await super().setUp()

        lbry_conf.settings = None
        lbry_conf.initialize_settings(load_conf_file=False)
        lbry_conf.settings['data_dir'] = self.stack.wallet.data_path
        lbry_conf.settings['lbryum_wallet_dir'] = self.stack.wallet.data_path
        lbry_conf.settings['download_directory'] = self.stack.wallet.data_path
        lbry_conf.settings['use_upnp'] = False
        lbry_conf.settings['blockchain_name'] = 'lbrycrd_regtest'
        lbry_conf.settings['lbryum_servers'] = [('localhost', 50001)]
        lbry_conf.settings['known_dht_nodes'] = []
        lbry_conf.settings.node_id = None

        await d2f(self.account.ensure_address_gap())
        address = (await d2f(self.account.receiving.get_usable_addresses(1)))[0]
        sendtxid = await self.blockchain.send_to_address(address.decode(), 10)
        await self.on_transaction_id(sendtxid)
        await self.blockchain.generate(1)
        await self.on_transaction_id(sendtxid)
        self.daemon = Daemon(FakeAnalytics())
        self.daemon.wallet = self.manager
        wallet_component = WalletComponent(self.daemon.component_manager)
        wallet_component.wallet = self.manager
        wallet_component._running = True
        self.daemon.component_manager.components.add(wallet_component)
        session_component = SessionComponent(self.daemon.component_manager)
        session_component.session = FakeSession()
        session_component._running = True
        self.daemon.component_manager.components.add(session_component)
        file_manager = FileManager(self.daemon.component_manager)
        file_manager.file_manager = EncryptedFileManager(session_component.session, True)
        file_manager._running = True
        self.daemon.component_manager.components.add(file_manager)


class ChannelNewCommandTests(CommandTestCase):

    VERBOSE = True

    @defer.inlineCallbacks
    def test_new_channel(self):
        result = yield self.daemon.jsonrpc_channel_new('@bar', 1*COIN)
        self.assertIn('txid', result)
        yield self.ledger.on_transaction.deferred_where(
            lambda e: e.tx.hex_id.decode() == result['txid']
        )


class WalletBalanceCommandTests(CommandTestCase):

    VERBOSE = True

    @defer.inlineCallbacks
    def test_wallet_balance(self):
        result = yield self.daemon.jsonrpc_wallet_balance()
        self.assertEqual(result, 10*COIN)


class PublishCommandTests(CommandTestCase):

    VERBOSE = True

    @defer.inlineCallbacks
    def test_publish(self):
        result = yield self.daemon.jsonrpc_publish('foo', 1)
        print(result)
