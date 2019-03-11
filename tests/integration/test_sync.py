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
    def test_sync(self):
        starting_hash = 'fcafbb9bd3943d8d425a4c00d3982a4c6aaff763d5289f7852296f8ea882214f'
        self.assertEqual(self.daemon.jsonrpc_sync_hash(), starting_hash)
        self.assertEqual(self.daemon.jsonrpc_sync_apply('password')['hash'], starting_hash)
        self.assertFalse(self.account.certificates)

        hash_w_cert = 'ef748d7777bb01ce9be6f87d3e46aeb31abbbe1648b1f2ddfa5aa9bcf0736a2d'
        add_cert = (
            '5sx5Q4ruPFDSftJ3+5l0rKDEacDE7npsee2Pz+jsYTiNSBtDXt/fbvpKELpn6BWYDM1rqDCHDgZoy6609KbTCu'
            'TqlYnrtMVpSz8QXc/Gzry2zXgtuuG6CAAvhntfELfwiJW4r1wvKDq30+IDrX8HIM5TiErLsLqfvfhc4t9Qfn5Y'
            'IgJk9pYxu+xC7rJh+kYra+zu6JtEI9hdq+peXX6uAnqEKlRQCTLDPA6Z9Pk9Hdbhl9QJ3TVTNeTkMQyCZZ49SJ'
            'PtOghGXIA9Gtkp86nKvuzV7rKpVEJEe/mcUsBkQ/W9W/7bok3tOXBs7SCis0MMyYFbCQ1LVDy6RUD28UHp/P5O'
            '4kbxptuRzGKrkrQX00QEqzPuQwbbxuOMarGWUBP4USX6GmtK0e3AL1bUJzdJEuy937DdcvbhrzfxT0Jphjal5s'
            'BSDufxZaQcHLHOhjQ8DDnFscjbAChcjxCLgcYMtdxYGM0WmCU7vdKyWK7sULi+LSqPTf/75lYoW1FxXt3v/blX'
            'I3nJF5owVEZPx/5dNy95WDVCpQyDNd/Zw9ke2P+4d6hyMXbsz9Oei0q4BlKDM3MNGHd+MNSiX23xZq+FtTQdbw'
            'ZOBhRTcQRB8VoR9M27acQApcdd2AXj0ZKrj/T+p8O0tuM0kWYOOAt6P/WxbU16im+WoR+4OTPggxu8r8SFFsXZ'
            'EXYXT3tUSNzpU32OH2jXzo7P4Wa69s8u+X8RgA=='
        )
        self.assertEqual(self.daemon.jsonrpc_sync_apply('password', data=add_cert)['hash'], hash_w_cert)
        self.assertEqual(self.daemon.jsonrpc_sync_hash(), hash_w_cert)
        self.assertEqual(self.account.certificates, {'abcdefg1234:0': '---PRIVATE KEY---'})

        # applying the same diff is idempotent
        self.assertEqual(self.daemon.jsonrpc_sync_apply('password', data=add_cert)['hash'], hash_w_cert)
        self.assertEqual(self.daemon.jsonrpc_sync_hash(), hash_w_cert)
        self.assertEqual(self.account.certificates, {'abcdefg1234:0': '---PRIVATE KEY---'})
