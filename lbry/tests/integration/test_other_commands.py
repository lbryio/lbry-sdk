from lbry.testcase import CommandTestCase


class AddressManagement(CommandTestCase):

    async def test_address_list(self):
        addresses = await self.out(self.daemon.jsonrpc_address_list())
        self.assertItemCount(addresses, 27)

        single = await self.out(self.daemon.jsonrpc_address_list(addresses['items'][11]['address']))
        self.assertItemCount(single, 1)
        self.assertEqual(single['items'][0], addresses['items'][11])

    async def test_settings(self):
        settings = self.daemon.jsonrpc_settings_get()
        self.assertNotEqual(settings['lbryum_servers'][0],('127.0.0.1', 50002))
        self.assertEqual(settings['lbryum_servers'][0],('127.0.0.1', 50001))

        servers = ['server:50001', 'server2:50001']
        self.daemon.jsonrpc_settings_set('lbryum_servers', servers)
        self.daemon.jsonrpc_settings_set('use_upnp', True)
        settings2 = self.daemon.jsonrpc_settings_get()
        self.assertEqual(settings2['lbryum_servers'][0], ('server', 50001))
        self.assertEqual(settings2['use_upnp'], True)

        self.daemon.jsonrpc_settings_clear('lbryum_servers')
        settings3 = self.daemon.jsonrpc_settings_get()
        self.assertNotEqual(settings3['lbryum_servers'][0], ('spv1.lbry.com', 50002))
        self.assertEqual(settings3['lbryum_servers'][0], ('spv1.lbry.com', 50001))
