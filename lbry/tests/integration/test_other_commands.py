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
        self.assertEqual(setting['lbryum_servers'][0], ('spv1.lbry.com', 50001))
        self.assertEqual(self.daemon.jsonrpc_settings_get()['lbryum_servers'][0], ('spv1.lbry.com', 50001))
