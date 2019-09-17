from lbry.testcase import CommandTestCase


class AddressManagement(CommandTestCase):

    async def test_address_list(self):
        addresses = await self.daemon.jsonrpc_address_list()
        self.assertEqual(27, len(addresses))

        single = await self.daemon.jsonrpc_address_list(addresses[11]['address'])
        self.assertEqual(1, len(single))
        self.assertEqual(single[0], addresses[11])
