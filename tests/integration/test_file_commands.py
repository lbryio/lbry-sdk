import asyncio
import logging
import os
from binascii import unhexlify, hexlify

from lbrynet.schema import Claim
from lbrynet.testcase import CommandTestCase
from lbrynet.blob_exchange.downloader import BlobDownloader


class FileCommands(CommandTestCase):

    VERBOSITY = logging.WARN

    async def test_file_management(self):
        await self.stream_create('foo', '0.01')
        await self.stream_create('foo2', '0.01')

        file1, file2 = self.sout(self.daemon.jsonrpc_file_list('claim_name'))
        self.assertEqual(file1['claim_name'], 'foo')
        self.assertEqual(file2['claim_name'], 'foo2')

        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        self.assertEqual(len(self.daemon.jsonrpc_file_list()), 1)
        await self.daemon.jsonrpc_file_delete(claim_name='foo2')
        self.assertEqual(len(self.daemon.jsonrpc_file_list()), 0)

        await self.daemon.jsonrpc_get('lbry://foo')
        self.assertEqual(len(self.daemon.jsonrpc_file_list()), 1)

    async def test_file_list_updated_metadata_on_resolve(self):
        await self.stream_create('foo', '0.01')
        claim = await self.daemon.resolve('lbry://foo')
        claim = claim['lbry://foo']['claim']['protobuf'].decode()
        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        txid = await self.blockchain_claim_name('bar', claim, '0.01')
        await self.daemon.jsonrpc_get('lbry://bar')
        claim = Claim.from_bytes(unhexlify(claim))
        claim.stream.description = "fix typos, fix the world"
        await self.blockchain_update_name(txid, hexlify(claim.to_bytes()).decode(), '0.01')
        await self.daemon.jsonrpc_resolve('lbry://bar')
        file_list = self.daemon.jsonrpc_file_list()
        self.assertEqual(file_list[0].stream_claim_info.claim.stream.description, claim.stream.description)

    async def test_download_different_timeouts(self):
        tx = await self.stream_create('foo', '0.01')
        sd_hash = tx['outputs'][0]['value']['source']['sd_hash']
        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        all_except_sd = [
            blob_hash for blob_hash in self.server.blob_manager.completed_blob_hashes if blob_hash != sd_hash
        ]
        await self.server.blob_manager.delete_blobs(all_except_sd)
        resp = await self.daemon.jsonrpc_get('lbry://foo', timeout=2)
        self.assertIn('error', resp)
        self.assertEqual('Failed to download data blobs for sd hash %s within timeout' % sd_hash, resp['error'])
        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        await self.server.blob_manager.delete_blobs([sd_hash])
        resp = await self.daemon.jsonrpc_get('lbry://foo', timeout=2)
        self.assertIn('error', resp)
        self.assertEqual('Failed to download sd blob %s within timeout' % sd_hash, resp['error'])

    async def wait_files_to_complete(self):
        while self.sout(self.daemon.jsonrpc_file_list(status='running')):
            await asyncio.sleep(0.01)

    async def test_filename_conflicts_management_on_resume_download(self):
        await self.stream_create('foo', '0.01', data=bytes([0] * (1 << 23)))
        file_info = self.sout(self.daemon.jsonrpc_file_list())[0]
        original_path = os.path.join(self.daemon.conf.download_dir, file_info['file_name'])
        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        await self.daemon.jsonrpc_get('lbry://foo')
        with open(original_path, 'wb') as handle:
            handle.write(b'some other stuff was there instead')
        self.daemon.stream_manager.stop()
        await self.daemon.stream_manager.start()
        await asyncio.wait_for(self.wait_files_to_complete(), timeout=5)  # if this hangs, file didnt get set completed
        # check that internal state got through up to the file list API
        stream = self.daemon.stream_manager.get_stream_by_stream_hash(file_info['stream_hash'])
        file_info = self.sout(self.daemon.jsonrpc_file_list()[0])
        self.assertEqual(stream.file_name, file_info['file_name'])
        # checks if what the API shows is what he have at the very internal level.
        self.assertEqual(stream.full_path, file_info['download_path'])

    async def test_incomplete_downloads_erases_output_file_on_stop(self):
        tx = await self.stream_create('foo', '0.01', data=b'deadbeef' * 1000000)
        sd_hash = tx['outputs'][0]['value']['source']['sd_hash']
        file_info = self.sout(self.daemon.jsonrpc_file_list())[0]
        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        blobs = await self.server_storage.get_blobs_for_stream(
            await self.server_storage.get_stream_hash_for_sd_hash(sd_hash)
        )
        all_except_sd_and_head = [
            blob.blob_hash for blob in blobs[1:-1]
        ]
        await self.server.blob_manager.delete_blobs(all_except_sd_and_head)
        path = os.path.join(self.daemon.conf.download_dir, file_info['file_name'])
        self.assertFalse(os.path.isfile(path))
        resp = await self.out(self.daemon.jsonrpc_get('lbry://foo', timeout=2))
        self.assertNotIn('error', resp)
        self.assertTrue(os.path.isfile(path))
        self.daemon.stream_manager.stop()
        await asyncio.sleep(0.01, loop=self.loop)  # FIXME: this sleep should not be needed
        self.assertFalse(os.path.isfile(path))

    async def test_incomplete_downloads_retry(self):
        tx = await self.stream_create('foo', '0.01', data=b'deadbeef' * 1000000)
        sd_hash = tx['outputs'][0]['value']['source']['sd_hash']
        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        blobs = await self.server_storage.get_blobs_for_stream(
            await self.server_storage.get_stream_hash_for_sd_hash(sd_hash)
        )
        all_except_sd_and_head = [
            blob.blob_hash for blob in blobs[1:-1]
        ]

        # backup server blobs
        for blob_hash in all_except_sd_and_head:
            blob = self.server_blob_manager.get_blob(blob_hash)
            os.rename(blob.file_path, blob.file_path + '__')

        # erase all except sd blob
        await self.server.blob_manager.delete_blobs(all_except_sd_and_head)

        # start the download
        resp = await self.out(self.daemon.jsonrpc_get('lbry://foo', timeout=2))
        self.assertNotIn('error', resp)
        self.assertEqual(len(self.daemon.jsonrpc_file_list()), 1)
        self.assertEqual('running', self.sout(self.daemon.jsonrpc_file_list())[0]['status'])
        await self.daemon.jsonrpc_file_set_status('stop', claim_name='foo')

        # recover blobs
        for blob_hash in all_except_sd_and_head:
            blob = self.server_blob_manager.get_blob(blob_hash)
            os.rename(blob.file_path + '__', blob.file_path)
            self.server_blob_manager.blobs.clear()
            await self.server_blob_manager.blob_completed(self.server_blob_manager.get_blob(blob_hash))

        await self.daemon.jsonrpc_file_set_status('start', claim_name='foo')
        await asyncio.wait_for(self.wait_files_to_complete(), timeout=5)
        file_info = self.sout(self.daemon.jsonrpc_file_list())[0]
        self.assertEqual(file_info['blobs_completed'], file_info['blobs_in_stream'])
        self.assertEqual('finished', file_info['status'])

    async def test_unban_recovers_stream(self):
        BlobDownloader.BAN_TIME = .5  # fixme: temporary field, will move to connection manager or a conf
        tx = await self.stream_create('foo', '0.01', data=bytes([0] * (1 << 23)))
        sd_hash = tx['outputs'][0]['value']['source']['sd_hash']
        missing_blob_hash = (await self.daemon.jsonrpc_blob_list(sd_hash=sd_hash))[-2]
        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        # backup blob
        missing_blob = self.server_blob_manager.get_blob(missing_blob_hash)
        os.rename(missing_blob.file_path, missing_blob.file_path + '__')
        self.server_blob_manager.delete_blob(missing_blob_hash)
        await self.daemon.jsonrpc_get('lbry://foo')
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(self.wait_files_to_complete(), timeout=1)
        # restore blob
        os.rename(missing_blob.file_path + '__', missing_blob.file_path)
        self.server_blob_manager.blobs.clear()
        missing_blob = self.server_blob_manager.get_blob(missing_blob_hash)
        self.server_blob_manager.blob_completed(missing_blob)
        await asyncio.wait_for(self.wait_files_to_complete(), timeout=1)

    async def test_paid_download(self):
        target_address = await self.blockchain.get_raw_change_address()

        # FAIL: beyond available balance
        await self.stream_create(
            'expensive', '0.01', data=b'pay me if you can',
            fee_currency='LBC', fee_amount='11.0', fee_address=target_address
        )
        await self.daemon.jsonrpc_file_delete(claim_name='expensive')
        response = await self.out(self.daemon.jsonrpc_get('lbry://expensive'))
        self.assertEqual(response['error'], 'fee of 11.00000 exceeds max available balance')
        self.assertEqual(len(self.daemon.jsonrpc_file_list()), 0)

        # FAIL: beyond maximum key fee
        await self.stream_create(
            'maxkey', '0.01', data=b'no pay me, no',
            fee_currency='LBC', fee_amount='111.0', fee_address=target_address
        )
        await self.daemon.jsonrpc_file_delete(claim_name='maxkey')
        response = await self.out(self.daemon.jsonrpc_get('lbry://maxkey'))
        self.assertEqual(len(self.daemon.jsonrpc_file_list()), 0)
        self.assertEqual(response['error'], 'fee of 111.00000 exceeds max configured to allow of 50.00000')

        # PASS: purchase is successful
        await self.stream_create(
            'icanpay', '0.01', data=b'I got the power!',
            fee_currency='LBC', fee_amount='1.0', fee_address=target_address
        )
        await self.daemon.jsonrpc_file_delete(claim_name='icanpay')
        await self.assertBalance(self.account, '9.925679')
        response = await self.daemon.jsonrpc_get('lbry://icanpay')
        await self.ledger.wait(response.content_fee)
        await self.assertBalance(self.account, '8.925555')
        self.assertEqual(len(self.daemon.jsonrpc_file_list()), 1)

        await asyncio.wait_for(self.wait_files_to_complete(), timeout=1)

        # check that the fee was received
        starting_balance = await self.blockchain.get_balance()
        await self.generate(1)
        block_reward_and_claim_fee = 2.0
        self.assertEqual(
            await self.blockchain.get_balance(), starting_balance + block_reward_and_claim_fee
        )
