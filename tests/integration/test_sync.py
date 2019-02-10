from unittest import mock

from lbrynet.schema.claim import ClaimDict

from torba.orchstr8.node import WalletNode, SPVNode
from torba.testcase import AsyncioTestCase

import lbrynet.schema
lbrynet.schema.BLOCKCHAIN_NAME = 'lbrycrd_regtest'

from lbrynet.conf import Config
from lbrynet.extras.daemon.Daemon import Daemon
from lbrynet.extras.wallet import LbryWalletManager, RegTestLedger
from lbrynet.extras.daemon.Components import WalletComponent
from lbrynet.extras.daemon.Components import (
    DHT_COMPONENT, HASH_ANNOUNCER_COMPONENT, PEER_PROTOCOL_SERVER_COMPONENT,
    UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT
)
from lbrynet.extras.daemon.ComponentManager import ComponentManager


class AccountSynchronization(AsyncioTestCase):

    async def asyncSetUp(self):
        self.wallet_node = WalletNode(LbryWalletManager, RegTestLedger)
        await self.wallet_node.start(
            SPVNode(None),
            "carbon smart garage balance margin twelve chest sword toast envelope bottom stomach absent",
            False
        )
        self.account = self.wallet_node.account

        conf = Config()
        conf.data_dir = self.wallet_node.data_path
        conf.wallet_dir = self.wallet_node.data_path
        conf.download_dir = self.wallet_node.data_path
        conf.share_usage_data = False
        conf.use_upnp = False
        conf.reflect_streams = False
        conf.blockchain_name = 'lbrycrd_regtest'
        conf.lbryum_servers = [('localhost', 50001)]
        conf.reflector_servers = []
        conf.known_dht_nodes = []

        def wallet_maker(component_manager):
            self.wallet_component = WalletComponent(component_manager)
            self.wallet_component.wallet_manager = self.wallet_node.manager
            self.wallet_component._running = True
            return self.wallet_component

        conf.components_to_skip = [
            DHT_COMPONENT, UPNP_COMPONENT, HASH_ANNOUNCER_COMPONENT,
            PEER_PROTOCOL_SERVER_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT
        ]
        self.daemon = Daemon(conf, ComponentManager(
            conf, skip_components=conf.components_to_skip, wallet=wallet_maker
        ))
        await self.daemon.initialize()

    async def asyncTearDown(self):
        self.wallet_component._running = False
        await self.daemon.stop()

    @mock.patch('time.time', mock.Mock(return_value=12345))
    def test_manifest(self):
        self.account.certificates['abcdefg1234:0'] = '---PRIVATE KEY---'
        self.assertEqual({
            'type': 'manifest',
            'generated': 12345,
            'status': b'880fd3bef17c02d02710af94dcb69877407636432ad8cf17db2689be36fc52e4',
            'accounts': [{
                'account_id': 'n4ZRwP4QjKwsmXCfqUPqnx133i83Ha7GbW',
                'timestamp': 12345,
                'hash-data': b'c9a0e30c9cccd995e0c241a5d6e34308a291581dd858ffe51b307094fa621f8a',
                'hash-certificates': [
                    b'IQlU7wyFap5scPGm4OgYOBa5bXx9Fy0KJOfeX2QbTN4='
                ]
            }]
        }, self.daemon.jsonrpc_account_manifest('password'))
