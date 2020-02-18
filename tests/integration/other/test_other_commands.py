from lbry.extras.daemon.loggly_handler import get_loggly_handler
from lbry.testcase import CommandTestCase


class AddressManagement(CommandTestCase):

    async def test_address_list(self):
        addresses = await self.out(self.daemon.jsonrpc_address_list())
        self.assertItemCount(addresses, 27)

        single = await self.out(self.daemon.jsonrpc_address_list(addresses['items'][11]['address']))
        self.assertItemCount(single, 1)
        self.assertEqual(single['items'][0], addresses['items'][11])


class SettingsManagement(CommandTestCase):

    async def test_settings(self):
        self.assertEqual(self.daemon.jsonrpc_settings_get()['lbryum_servers'][0], ('127.0.0.1', 50001))

        setting = self.daemon.jsonrpc_settings_set('lbryum_servers', ['server:50001'])
        self.assertEqual(setting['lbryum_servers'][0], ('server', 50001))
        self.assertEqual(self.daemon.jsonrpc_settings_get()['lbryum_servers'][0], ('server', 50001))

        setting = self.daemon.jsonrpc_settings_clear('lbryum_servers')
        self.assertEqual(setting['lbryum_servers'][0], ('spv11.lbry.com', 50001))
        self.assertEqual(self.daemon.jsonrpc_settings_get()['lbryum_servers'][0], ('spv11.lbry.com', 50001))

        # test_privacy_settings (merged for reducing test time, unmerge when its fast)
        # tests that changing share_usage_data propagates to the relevant properties
        self.assertFalse(self.daemon.jsonrpc_settings_get()['share_usage_data'])
        loggly = get_loggly_handler(lambda: self.daemon.conf.share_usage_data)
        self.addCleanup(loggly.close)
        self.assertFalse(self.daemon.analytics_manager.enabled)
        self.assertFalse(loggly.enabled)
        self.daemon.jsonrpc_settings_set('share_usage_data', True)
        self.assertTrue(self.daemon.jsonrpc_settings_get()['share_usage_data'])
        self.assertTrue(self.daemon.analytics_manager.enabled)
        self.assertTrue(loggly.enabled)
        self.daemon.jsonrpc_settings_set('share_usage_data', False)
