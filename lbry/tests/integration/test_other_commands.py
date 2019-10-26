from lbry.testcase import CommandTestCase


class AddressManagement(CommandTestCase):

    async def test_address_list(self):
        addresses = await self.out(self.daemon.jsonrpc_address_list())
        self.assertItemCount(addresses, 27)

        single = await self.out(self.daemon.jsonrpc_address_list(addresses['items'][11]['address']))
        self.assertItemCount(single, 1)
        self.assertEqual(single['items'][0], addresses['items'][11])
