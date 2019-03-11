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
            'czo4MTkyOjE2OjE6uZSVTe/9fjPSxqUDKRKNmVUh9RU3cJfYIrfQVHd2XoE8i79xEuBiPqDAtvmGudg1GswdPv17k3'
            'MOMu0TeKSg1UibPxc6X2Hv/RHI1W0LPVD4wgm9J4p3WS7tPE4+ROpDtbyd8X6S2AMnjHRGvcSZHuV5/Xm6roljn+/d'
            'TSkBSt4obzzmyMeglP2ZP933u4WGhcwODtEUKwbjlNpea5fwsrBcJRiQ5tOJlnFBdCNwcaqS217eP5IP6Opul/f+EF'
            'MuoiaJYzv75hZJbqUOjwBWI5aSMPThct3NfZvSJElnXp8kGN6dfsE/ipTYolmMZPoEOg/Y41hW9NoLLqMa2zisbDtd'
            'a1LagrOCvswmAifAYwfQ8b3KfgC9OXRGFjIoYk+kDb8w2NOoJ2rb72p35KqcpVbCDlLKsTl2JHMsb7LMpktu48Tg6v'
            '86u3m8AFf4sbMnAZQNcvKNFo6lXK7Fuv7ql22t9cu08ehf2PF2/0an1YFmI4Yxg5qR3JQn3ubjfFQi9k6XcVHUkyGQ'
            'rOnhetLpvORFuJ2ydTrUTW0U8zJ96pgugWWEOeEVBnhvjxJvbBZSrRf7YVhxzmxYIDttZj15FTlI0fukDA8323kEdh'
            'TifEQL+Q3djzblJQ1MqAq1YBSD87Np4iQHINQztuLguA5fJHexWoHH60K037Th8HXco1d/qprlu2I/KyJERFHoq+r6'
            'La9oRL/r9re7qOu6TkC36Q=='
        )
        self.assertEqual(self.daemon.jsonrpc_sync_apply('password', data=add_cert)['hash'], hash_w_cert)
        self.assertEqual(self.daemon.jsonrpc_sync_hash(), hash_w_cert)
        self.assertEqual(self.account.certificates, {'abcdefg1234:0': '---PRIVATE KEY---'})

        # applying the same diff is idempotent
        self.assertEqual(self.daemon.jsonrpc_sync_apply('password', data=add_cert)['hash'], hash_w_cert)
        self.assertEqual(self.daemon.jsonrpc_sync_hash(), hash_w_cert)
        self.assertEqual(self.account.certificates, {'abcdefg1234:0': '---PRIVATE KEY---'})
