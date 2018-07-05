import types

from orchstr8.testcase import IntegrationTestCase, d2f
from torba.constants import COIN

import lbryschema
lbryschema.BLOCKCHAIN_NAME = 'lbrycrd_regtest'

from lbrynet import conf as lbry_conf
from lbrynet.daemon.Daemon import Daemon
from lbrynet.wallet.manager import LbryWalletManager


class FakeAnalytics:
    def send_new_channel(self):
        pass


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
        self.daemon.session = types.SimpleNamespace()
        self.daemon.session.wallet = self.manager


class DaemonCommandsTests(CommandTestCase):

    VERBOSE = True

    async def test_new_channel(self):
        result = await d2f(self.daemon.jsonrpc_channel_new('@bar', 1*COIN))
        self.assertIn('txid', result)
        await self.on_transaction_id(result['txid'])

