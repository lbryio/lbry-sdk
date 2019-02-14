import asyncio
import logging
import os

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

    async def wait_files_to_complete(self):
        while self.daemon.jsonrpc_file_list(status='running'):
            await asyncio.sleep(0.01)

    async def test_filename_conflicts_management_on_resume_download(self):
        await self.make_claim('foo', '0.01', data=bytes([0]*(1<<23)))
        file_info = self.daemon.jsonrpc_file_list()[0]
        original_path = os.path.join(self.daemon.conf.download_dir, file_info['file_name'])
        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        await self.daemon.jsonrpc_get('lbry://foo')
        with open(original_path, 'wb') as handle:
            handle.write(b'some other stuff was there instead')
        self.daemon.stream_manager.stop()
        await self.daemon.stream_manager.start()
        await asyncio.wait_for(self.wait_files_to_complete(), timeout=5)  # if this hangs, file didnt get set completed
        # check that internal state got through up to the file list API
        downloader = self.daemon.stream_manager.get_stream_by_stream_hash(file_info['stream_hash']).downloader
        file_info = self.daemon.jsonrpc_file_list()[0]
        self.assertEqual(downloader.output_file_name, file_info['file_name'])
        # checks if what the API shows is what he have at the very internal level.
        self.assertEqual(downloader.output_path, file_info['download_path'])
        # if you got here refactoring just change above, but ensure what gets set internally gets reflected externally!
        self.assertTrue(downloader.output_path.endswith(downloader.output_file_name))
        # this used to be inconsistent, if it becomes again it would create weird bugs, so worth checking

    async def test_incomplete_downloads_erases_output_file_on_stop(self):
        claim = await self.make_claim('foo', '0.01')
        sd_hash = claim['output']['value']['stream']['source']['source']
        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        all_except_sd = [
            blob_hash for blob_hash in self.server.blob_manager.completed_blob_hashes if blob_hash != sd_hash
        ]
        await self.server.blob_manager.delete_blobs(all_except_sd)

        resp = await self.daemon.jsonrpc_get('lbry://foo', timeout=2)
        self.assertIn('error', resp)
        file_info = self.daemon.jsonrpc_file_list()[0]
        self.assertTrue(os.path.isfile(os.path.join(file_info['download_path'])))
        await self.daemon.jsonrpc_file_set_status('stop', sd_hash=sd_hash)
        self.assertFalse(os.path.isfile(os.path.join(file_info['download_path'])))
