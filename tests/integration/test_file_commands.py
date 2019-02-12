import logging
from integration.testcase import CommandTestCase


class FileCommands(CommandTestCase):

    VERBOSITY = logging.INFO

    async def test_file_management(self):
        await self.make_claim('foo', '0.01')
        await self.make_claim('foo2', '0.01')

        file1, file2 = self.daemon.jsonrpc_file_list()
        self.assertEqual(file1['claim_name'], 'foo')
        self.assertEqual(file2['claim_name'], 'foo2')

        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        self.assertEqual(len(self.daemon.jsonrpc_file_list()), 1)
        await self.daemon.jsonrpc_file_delete(claim_name='foo2')
        self.assertEqual(len(self.daemon.jsonrpc_file_list()), 0)

        await self.daemon.jsonrpc_get('lbry://foo')
        self.assertEqual(len(self.daemon.jsonrpc_file_list()), 1)
