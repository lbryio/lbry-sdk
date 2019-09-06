from unittest import mock

from torba.orchstr8.node import WalletNode, SPVNode
from torba.testcase import AsyncioTestCase

from lbry.conf import Config
from lbry.wallet import LbryWalletManager, RegTestLedger
from lbry.extras.daemon.Daemon import Daemon
from lbry.extras.daemon.Components import WalletComponent
from lbry.extras.daemon.Components import (
    DHT_COMPONENT, HASH_ANNOUNCER_COMPONENT, PEER_PROTOCOL_SERVER_COMPONENT,
    UPNP_COMPONENT, EXCHANGE_RATE_MANAGER_COMPONENT
)
from lbry.extras.daemon.ComponentManager import ComponentManager


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
        await self.daemon.stop(shutdown_runner=False)

    @mock.patch('time.time', mock.Mock(return_value=12345))
    def test_sync(self):
        starting_hash = '69afcd60a300f47933917d77ef011beeeb4decfafebbda91c144c84282c6814f'
        self.account.modified_on = 123.456
        self.assertEqual(self.daemon.jsonrpc_sync_hash(), starting_hash)
        self.assertEqual(self.daemon.jsonrpc_sync_apply('password')['hash'], starting_hash)
        self.assertFalse(self.account.channel_keys)

        hash_w_cert = '974721f42dab42657b5911b7caf4af98ce4d3879eea6ac23d50c1d79bc5020ef'
        add_cert = (
            'czo4MTkyOjE2OjE6qs3JRvS/bhX8p1JD68sqyA2Qhx3EVTqskhqEAwtfAUfUsQqeJ1rtMdRf40vkGKnpt4NT0b'
            'XEqb5O+lba4nkLF7vZENhc2zuOrjobCPVbiVHNwOfH56Ayrh1ts5LMcnl5+Mk1BUyGCwXcqEg2KiUkd3YZpiHQ'
            'T7WfcODcU6l7IRivb8iawCebZJx9waVyQoqEDKwZUY1i5HA0VLC+s5cV7it1AWbewiyWOQtZdEPzNY44oXLJex'
            'SirElQqDqNZyl3Hjy8YqacBbSYoejIRnmXpC9y25keP6hep3f9i1K2HDNwhwns1W1vhuzuO2Gy9+a0JlVm5mwc'
            'N2pqO4tCZr6tE3aym2FaSAunOi7QYVFMI6arb9Gvn9P+T+WRiFYfzwDFVR+j5ZPmUDXxHisy5OF163jH61wbBY'
            'pPienjlVtDOxoZmA8+AwWXKRdINsRcull9pu7EVCq5yQmrmxoPbLxNh5pRGrBB0JwCCOMIf+KPwS+7Z6dDbiwO'
            '2NUpk8USJMTmXmFDCr2B0PJiG6Od2dD2oGN0F7aYZvUuKbqj8eDrJMe/zLbhq47jUjkJFCvtxUioo63ORk1pzH'
            'S0/X4/6/95PRSMaXm4DcZ9BdyxR2E/AKc8UN6AL5rrn6quXkC6R3ZhKgN3Si2S9y6EGFsL7dgzX331U08ZviLj'
            'NsrG0EKUnf+TGQ42MqnLQBOiO/ZoAwleOzNZnCYOQQ14Mm8y17xUpmdWRDiRKpAOJU22jKnxtqQ='
        )
        self.daemon.jsonrpc_sync_apply('password', data=add_cert)
        self.assertEqual(self.daemon.jsonrpc_sync_hash(), hash_w_cert)
        self.assertEqual(self.account.channel_keys, {'abcdefg1234:0': '---PRIVATE KEY---'})

        # applying the same diff is idempotent
        self.daemon.jsonrpc_sync_apply('password', data=add_cert)
        self.assertEqual(self.daemon.jsonrpc_sync_hash(), hash_w_cert)
        self.assertEqual(self.account.channel_keys, {'abcdefg1234:0': '---PRIVATE KEY---'})

    @mock.patch('time.time', mock.Mock(return_value=12345))
    def test_account_preferences_syncing(self):
        starting_hash = '69afcd60a300f47933917d77ef011beeeb4decfafebbda91c144c84282c6814f'
        self.account.modified_on = 123.456
        self.assertEqual(self.daemon.jsonrpc_sync_hash(), starting_hash)
        self.assertEqual(self.daemon.jsonrpc_sync_apply('password')['hash'], starting_hash)
        self.assertFalse(self.daemon.jsonrpc_preference_get())

        hash_w_pref = '2fe43f0b2f8bbf1fbb55537f862d8bcb0823791019a7151c848bd5f5bd32d336'
        add_pref = (
            'czo4MTkyOjE2OjE6Jgn3nAGrfYP2usMA4KQ/73+YHAwMyiGdSWuxCmgZKlpwSpnfQv8R7R0tum/n2oTSBQxjdL'
            'OlTW+tv/G5L2GfQ5op3xaT89gN+F/JJnvf3cdWvYH7Nc+uTUMb7cKhJP7hQvFW5bb1Y3jX3EBBY00Jkqyj9RCR'
            'XPtbLVu71KbVRvCAR/oAnMEsgD+ITsC3WkXMwE3BS2LjJDQmeqbH4YXNdcjJN/JzQ6fxOmr3Uk1GqnpuhFsta8'
            'H14ViRilq1pLKOSZIN80rrm5cKq45nFO5kFeoqBCEaal4u2/OkX9nOnpQlO3E95wD8hkCmZ3i20aSte6nqwqXx'
            'ZKVRZqR2a0TjwVWB8kPXPA2ewKvPILaj190bXPl8EVu+TAnTCQwMgytinYjtcKNZmMz3ENJyI2mCANwpWlX7xl'
            'y/J+qLi5b9N+agghTxggs5rVJ/hkaue7GS542dXDrwMrw9nwGqNw3dS/lcU+1wRUQ0fnHwb/85XbbwyO2aDj2i'
            'DFNkdyLyUIiIUvB1JfWAnWqX3vQcL1REK1ePgUei7dCHJ3WyWdsRx3cVXzlK8yOPkf0N6d3AKrZQWVebwDC7Nd'
            'eL4sDW8AkaXuBIrbuZw6XUHd6WI0NvU/q10j2qMm0YoXSu+dExou1/1THwx5g86MxcX5nwodKUEVCOTzKMyrLz'
            'CRsitH/+dAXhZNRp/FbnDCGBMyD3MOYCjZvAFbCZUasoRwqponxILw=='
        )
        self.daemon.jsonrpc_sync_apply('password', data=add_pref)
        self.assertEqual(self.daemon.jsonrpc_sync_hash(), hash_w_pref)
        self.assertEqual(self.daemon.jsonrpc_preference_get(), {"fruit": ["apple", "orange"]})

        self.daemon.jsonrpc_preference_set("fruit", ["peach", "apricot"])
        self.assertEqual(self.daemon.jsonrpc_preference_get(), {"fruit": ["peach", "apricot"]})
        self.assertNotEqual(self.daemon.jsonrpc_sync_hash(), hash_w_pref)
