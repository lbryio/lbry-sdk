import logging
from integration.testcase import CommandTestCase


class FileCommands(CommandTestCase):

    VERBOSITY = logging.INFO

    async def test_file_management(self):
        await self.make_claim('foo', '0.01')
        await self.make_claim('foo2', '0.01')

        file1, file2 = self.daemon.jsonrpc_file_list('claim_name')
        self.assertEqual(file1['claim_name'], 'foo')
        self.assertEqual(file2['claim_name'], 'foo2')

        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        self.assertEqual(len(self.daemon.jsonrpc_file_list()), 1)
        await self.daemon.jsonrpc_file_delete(claim_name='foo2')
        self.assertEqual(len(self.daemon.jsonrpc_file_list()), 0)

        await self.daemon.jsonrpc_get('lbry://foo')
        self.assertEqual(len(self.daemon.jsonrpc_file_list()), 1)

    async def test_download_different_timeouts(self):
        claim = await self.make_claim('foo', '0.01')
        sd_hash = claim['output']['value']['stream']['source']['source']
        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        all_except_sd = [
            blob_hash for blob_hash in self.server.blob_manager.completed_blob_hashes if blob_hash != sd_hash
        ]
        await self.server.blob_manager.delete_blobs(all_except_sd)
        resp = await self.daemon.jsonrpc_get('lbry://foo', timeout=2)
        self.assertIn('error', resp)
        self.assertEquals('Failed to download data blobs for sd hash %s within timeout' % sd_hash, resp['error'])
        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        await self.server.blob_manager.delete_blob(sd_hash)
        resp = await self.daemon.jsonrpc_get('lbry://foo', timeout=2)
        self.assertIn('error', resp)
        self.assertEquals('Failed to download sd blob %s within timeout' % sd_hash, resp['error'])
