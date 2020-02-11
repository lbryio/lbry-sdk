import asyncio
import os
from binascii import hexlify

from lbry.schema import Claim
from lbry.testcase import CommandTestCase
from lbry.torrent.session import TorrentSession
from lbry.torrent.torrent_manager import TorrentManager
from lbry.wallet import Transaction


class FileCommands(CommandTestCase):
    async def initialize_torrent(self):
        self.seeder_session = TorrentSession(self.loop, None)
        self.addCleanup(self.seeder_session.stop)
        await self.seeder_session.bind('localhost', 4040)
        self.btih = await self.seeder_session.add_fake_torrent()
        address = await self.account.receiving.get_or_create_usable_address()
        claim = Claim()
        claim.stream.update(bt_infohash=self.btih)
        tx = await Transaction.claim_create(
            'torrent', claim, 1, address, [self.account], self.account)
        await tx.sign([self.account])
        await self.broadcast(tx)
        await self.confirm_tx(tx.id)
        client_session = TorrentSession(self.loop, None)
        self.daemon.file_manager.source_managers['torrent'] = TorrentManager(
            self.loop, self.daemon.conf, client_session, self.daemon.storage, self.daemon.analytics_manager
        )
        await self.daemon.file_manager.source_managers['torrent'].start()
        await client_session.bind('localhost', 4041)
        client_session._session.add_dht_node(('localhost', 4040))

    async def test_download_torrent(self):
        await self.initialize_torrent()
        await self.out(self.daemon.jsonrpc_get('torrent'))
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 1)

    async def create_streams_in_range(self, *args, **kwargs):
        self.stream_claim_ids = []
        for i in range(*args, **kwargs):
            t = await self.stream_create(f'Stream_{i}', '0.00001')
            self.stream_claim_ids.append(t['outputs'][0]['claim_id'])

    async def test_file_management(self):
        await self.stream_create('foo', '0.01')
        await self.stream_create('foo2', '0.01')

        file1, file2 = await self.file_list('claim_name')
        self.assertEqual(file1['claim_name'], 'foo')
        self.assertEqual(file2['claim_name'], 'foo2')

        self.assertItemCount(await self.daemon.jsonrpc_file_list(claim_id=[file1['claim_id'], file2['claim_id']]), 2)
        self.assertItemCount(await self.daemon.jsonrpc_file_list(claim_id=file1['claim_id']), 1)
        self.assertItemCount(await self.daemon.jsonrpc_file_list(outpoint=[file1['outpoint'], file2['outpoint']]), 2)
        self.assertItemCount(await self.daemon.jsonrpc_file_list(outpoint=file1['outpoint']), 1)

        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 1)
        await self.daemon.jsonrpc_file_delete(claim_name='foo2')
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 0)

        await self.daemon.jsonrpc_get('lbry://foo')
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 1)

    async def test_announces(self):
        # announces on publish
        self.assertEqual(await self.daemon.storage.get_blobs_to_announce(), [])
        await self.stream_create('foo', '0.01')
        stream = (await self.daemon.jsonrpc_file_list())["items"][0]
        self.assertSetEqual(
            set(await self.daemon.storage.get_blobs_to_announce()),
            {stream.sd_hash, stream.descriptor.blobs[0].blob_hash}
        )
        self.assertTrue(await self.daemon.jsonrpc_file_delete(delete_all=True))
        # announces on download
        self.assertEqual(await self.daemon.storage.get_blobs_to_announce(), [])
        stream = await self.daemon.jsonrpc_get('foo')
        self.assertSetEqual(
            set(await self.daemon.storage.get_blobs_to_announce()),
            {stream.sd_hash, stream.descriptor.blobs[0].blob_hash}
        )

    async def _purge_file(self, claim_name, full_path):
        self.assertTrue(
            await self.daemon.jsonrpc_file_delete(claim_name=claim_name, delete_from_download_dir=True)
        )
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 0)
        self.assertFalse(os.path.isfile(full_path))

    async def test_publish_with_illegal_chars(self):
        def check_prefix_suffix(name, prefix, suffix):
            self.assertTrue(name.startswith(prefix))
            self.assertTrue(name.endswith(suffix))

        # Stream a file with file name containing invalid chars
        claim_name = 'lolwindows'
        prefix, suffix = 'derp?', '.ext.'
        san_prefix, san_suffix = 'derp', '.ext'
        tx = await self.stream_create(claim_name, '0.01', prefix=prefix, suffix=suffix)
        stream = (await self.daemon.jsonrpc_file_list())["items"][0]
        claim_id = self.get_claim_id(tx)

        # Assert that file list and source contains the local unsanitized name, but suggested name is sanitized
        full_path = (await self.daemon.jsonrpc_get('lbry://' + claim_name)).full_path
        stream_file_name = os.path.basename(full_path)
        source_file_name = tx['outputs'][0]['value']['source']['name']
        file_list_name = stream.file_name
        suggested_file_name = stream.descriptor.suggested_file_name

        self.assertTrue(os.path.isfile(full_path))
        check_prefix_suffix(stream_file_name, prefix, suffix)
        self.assertEqual(stream_file_name, source_file_name)
        self.assertEqual(stream_file_name, file_list_name)
        check_prefix_suffix(suggested_file_name, san_prefix, san_suffix)
        await self._purge_file(claim_name, full_path)

        # Re-download deleted file and assert that the file name is sanitized
        full_path = (await self.daemon.jsonrpc_get('lbry://' + claim_name, save_file=True)).full_path
        stream_file_name = os.path.basename(full_path)
        stream = (await self.daemon.jsonrpc_file_list())["items"][0]
        file_list_name = stream.file_name
        suggested_file_name = stream.descriptor.suggested_file_name

        self.assertTrue(os.path.isfile(full_path))
        check_prefix_suffix(stream_file_name, san_prefix, san_suffix)
        self.assertEqual(stream_file_name, file_list_name)
        self.assertEqual(stream_file_name, suggested_file_name)
        await self._purge_file(claim_name, full_path)

        # Assert that the downloaded file name is not sanitized when user provides custom file name
        custom_name = 'cust*m_name'
        full_path = (await self.daemon.jsonrpc_get(
            'lbry://' + claim_name, file_name=custom_name, save_file=True)).full_path
        file_name_on_disk = os.path.basename(full_path)
        self.assertTrue(os.path.isfile(full_path))
        self.assertEqual(custom_name, file_name_on_disk)

        # Update the stream and assert the file name is not sanitized, but the suggested file name is
        prefix, suffix = 'derpyderp?', '.ext.'
        san_prefix, san_suffix = 'derpyderp', '.ext'
        tx = await self.stream_update(claim_id, data=b'amazing content', prefix=prefix, suffix=suffix)
        full_path = (await self.daemon.jsonrpc_get('lbry://' + claim_name, save_file=True)).full_path
        updated_stream = (await self.daemon.jsonrpc_file_list())["items"][0]

        stream_file_name = os.path.basename(full_path)
        source_file_name = tx['outputs'][0]['value']['source']['name']
        file_list_name = updated_stream.file_name
        suggested_file_name = updated_stream.descriptor.suggested_file_name

        self.assertTrue(os.path.isfile(full_path))
        check_prefix_suffix(stream_file_name, prefix, suffix)
        self.assertEqual(stream_file_name, source_file_name)
        self.assertEqual(stream_file_name, file_list_name)
        check_prefix_suffix(suggested_file_name, san_prefix, san_suffix)

    async def test_file_list_fields(self):
        await self.stream_create('foo', '0.01')
        file_list = await self.file_list()
        self.assertEqual(
            file_list[0]['timestamp'],
            self.ledger.headers.estimated_timestamp(file_list[0]['height'])
        )
        self.assertEqual(file_list[0]['confirmations'], -1)
        await self.daemon.jsonrpc_resolve('foo')
        file_list = await self.file_list()
        self.assertEqual(
            file_list[0]['timestamp'],
            self.ledger.headers.estimated_timestamp(file_list[0]['height'])
        )
        self.assertEqual(file_list[0]['confirmations'], 1)

    async def test_get_doesnt_touch_user_written_files_between_calls(self):
        await self.stream_create('foo', '0.01', data=bytes([0] * (2 << 23)))
        self.assertTrue(await self.daemon.jsonrpc_file_delete(claim_name='foo'))
        first_path = (await self.daemon.jsonrpc_get('lbry://foo', save_file=True)).full_path
        await self.wait_files_to_complete()
        self.assertTrue(await self.daemon.jsonrpc_file_delete(claim_name='foo'))
        with open(first_path, 'wb') as f:
            f.write(b' ')
            f.flush()
        second_path = await self.daemon.jsonrpc_get('lbry://foo', save_file=True)
        await self.wait_files_to_complete()
        self.assertNotEqual(first_path, second_path)

    async def test_file_list_updated_metadata_on_resolve(self):
        await self.stream_create('foo', '0.01')
        txo = (await self.daemon.resolve(self.wallet.accounts, ['lbry://foo']))['lbry://foo']
        claim = txo.claim
        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        txid = await self.blockchain_claim_name('bar', hexlify(claim.to_bytes()).decode(), '0.01')
        await self.daemon.jsonrpc_get('lbry://bar')
        claim.stream.description = "fix typos, fix the world"
        await self.blockchain_update_name(txid, hexlify(claim.to_bytes()).decode(), '0.01')
        await self.daemon.jsonrpc_resolve('lbry://bar')
        file_list = (await self.daemon.jsonrpc_file_list())['items']
        self.assertEqual(file_list[0].stream_claim_info.claim.stream.description, claim.stream.description)

    async def test_file_list_paginated_output(self):
        await self.create_streams_in_range(0, 20)

        page = await self.file_list(page_size=20)
        page_claim_ids = [item['claim_id'] for item in page]
        self.assertListEqual(page_claim_ids, self.stream_claim_ids)

        page = await self.file_list(page_size=6)
        page_claim_ids = [item['claim_id'] for item in page]
        self.assertListEqual(page_claim_ids, self.stream_claim_ids[:6])

        page = await self.file_list(page_size=6, page=2)
        page_claim_ids = [item['claim_id'] for item in page]
        self.assertListEqual(page_claim_ids, self.stream_claim_ids[6:12])

        out_of_bounds = await self.file_list(page=5, page_size=6)
        self.assertEqual(out_of_bounds, [])

        complete = await self.daemon.jsonrpc_file_list()
        self.assertEqual(complete['total_pages'], 1)
        self.assertEqual(complete['total_items'], 20)

        page = await self.daemon.jsonrpc_file_list(page_size=10, page=1)
        self.assertEqual(page['total_pages'], 2)
        self.assertEqual(page['total_items'], 20)
        self.assertEqual(page['page'], 1)

        full = await self.out(self.daemon.jsonrpc_file_list(page_size=20, page=1))
        page1 = await self.file_list(page=1, page_size=10)
        page2 = await self.file_list(page=2, page_size=10)
        self.assertEqual(page1 + page2, full['items'])

    async def test_download_different_timeouts(self):
        tx = await self.stream_create('foo', '0.01')
        sd_hash = tx['outputs'][0]['value']['source']['sd_hash']
        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        all_except_sd = [
            blob_hash for blob_hash in self.server.blob_manager.completed_blob_hashes if blob_hash != sd_hash
        ]
        await self.server.blob_manager.delete_blobs(all_except_sd)
        resp = await self.daemon.jsonrpc_get('lbry://foo', timeout=2, save_file=True)
        self.assertIn('error', resp)
        self.assertEqual('Failed to download data blobs for sd hash %s within timeout.' % sd_hash, resp['error'])
        self.assertTrue(await self.daemon.jsonrpc_file_delete(claim_name='foo'), "data timeout didn't create a file")
        await self.server.blob_manager.delete_blobs([sd_hash])
        resp = await self.daemon.jsonrpc_get('lbry://foo', timeout=2, save_file=True)
        self.assertIn('error', resp)
        self.assertEqual('Failed to download sd blob %s within timeout.' % sd_hash, resp['error'])

    async def wait_files_to_complete(self):
        while await self.file_list(status='running'):
            await asyncio.sleep(0.01)

    async def test_filename_conflicts_management_on_resume_download(self):
        await self.stream_create('foo', '0.01', data=bytes([0] * (1 << 23)))
        file_info = (await self.file_list())[0]
        original_path = os.path.join(self.daemon.conf.download_dir, file_info['file_name'])
        await self.daemon.jsonrpc_file_delete(claim_name='foo')
        await self.daemon.jsonrpc_get('lbry://foo')
        with open(original_path, 'wb') as handle:
            handle.write(b'some other stuff was there instead')
        self.daemon.file_manager.stop()
        await self.daemon.file_manager.start()
        await asyncio.wait_for(self.wait_files_to_complete(), timeout=5)  # if this hangs, file didn't get set completed
        # check that internal state got through up to the file list API
        stream = self.daemon.file_manager.get_filtered(stream_hash=file_info['stream_hash'])[0]
        file_info = (await self.file_list())[0]
        self.assertEqual(stream.file_name, file_info['file_name'])
        # checks if what the API shows is what he have at the very internal level.
        self.assertEqual(stream.full_path, file_info['download_path'])

    async def test_incomplete_downloads_erases_output_file_on_stop(self):
        tx = await self.stream_create('foo', '0.01', data=b'deadbeef' * 1000000)
        sd_hash = tx['outputs'][0]['value']['source']['sd_hash']
        file_info = (await self.file_list())[0]
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
        self.daemon.file_manager.stop()
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
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 1)
        self.assertEqual('running', (await self.file_list())[0]['status'])
        await self.daemon.jsonrpc_file_set_status('stop', claim_name='foo')

        # recover blobs
        for blob_hash in all_except_sd_and_head:
            blob = self.server_blob_manager.get_blob(blob_hash)
            os.rename(blob.file_path + '__', blob.file_path)
            self.server_blob_manager.blobs.clear()
            await self.server_blob_manager.blob_completed(self.server_blob_manager.get_blob(blob_hash))

        await self.daemon.jsonrpc_file_set_status('start', claim_name='foo')
        await asyncio.wait_for(self.wait_files_to_complete(), timeout=5)
        file_info = (await self.file_list())[0]
        self.assertEqual(file_info['blobs_completed'], file_info['blobs_in_stream'])
        self.assertEqual('finished', file_info['status'])

    async def test_paid_download(self):
        target_address = await self.blockchain.get_raw_change_address()

        # FAIL: beyond available balance
        await self.stream_create(
            'expensive', '0.01', data=b'pay me if you can',
            fee_currency='LBC', fee_amount='11.0', fee_address=target_address
        )
        await self.daemon.jsonrpc_file_delete(claim_name='expensive')
        response = await self.out(self.daemon.jsonrpc_get('lbry://expensive'))
        self.assertEqual(response['error'], 'Not enough funds to cover this transaction.')
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 0)

        # FAIL: beyond maximum key fee
        await self.stream_create(
            'maxkey', '0.01', data=b'no pay me, no',
            fee_currency='LBC', fee_amount='111.0', fee_address=target_address
        )
        await self.daemon.jsonrpc_file_delete(claim_name='maxkey')
        response = await self.out(self.daemon.jsonrpc_get('lbry://maxkey'))
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 0)
        self.assertEqual(
            response['error'], 'Purchase price of 111.0 LBC exceeds maximum configured price of 100.0 LBC (50.0 USD).'
        )

        # PASS: purchase is successful
        await self.stream_create(
            'icanpay', '0.01', data=b'I got the power!',
            fee_currency='LBC', fee_amount='1.0', fee_address=target_address
        )
        await self.daemon.jsonrpc_file_delete(claim_name='icanpay')
        await self.assertBalance(self.account, '9.925679')
        response = await self.daemon.jsonrpc_get('lbry://icanpay')
        raw_content_fee = response.content_fee.raw
        await self.ledger.wait(response.content_fee)
        await self.assertBalance(self.account, '8.925538')
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 1)

        await asyncio.wait_for(self.wait_files_to_complete(), timeout=1)

        # check that the fee was received
        starting_balance = await self.blockchain.get_balance()
        await self.generate(1)
        block_reward_and_claim_fee = 2.0
        self.assertEqual(
            await self.blockchain.get_balance(), starting_balance + block_reward_and_claim_fee
        )

        # restart the daemon and make sure the fee is still there

        self.daemon.file_manager.stop()
        await self.daemon.file_manager.start()
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 1)
        self.assertEqual((await self.daemon.jsonrpc_file_list())['items'][0].content_fee.raw, raw_content_fee)
        await self.daemon.jsonrpc_file_delete(claim_name='icanpay')

        # PASS: no fee address --> use the claim address to pay
        tx = await self.stream_create(
            'nofeeaddress', '0.01', data=b'free stuff?',
        )
        await self.__raw_value_update_no_fee_address(
            tx, fee_amount='2.0', fee_currency='LBC', claim_address=target_address
        )
        await self.daemon.jsonrpc_file_delete(claim_name='nofeeaddress')
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 0)

        response = await self.out(self.daemon.jsonrpc_get('lbry://nofeeaddress'))
        self.assertIsNone((await self.daemon.jsonrpc_file_list())['items'][0].stream_claim_info.claim.stream.fee.address)
        self.assertIsNotNone(response['content_fee'])
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 1)
        self.assertEqual(response['content_fee']['outputs'][0]['amount'], '2.0')
        self.assertEqual(response['content_fee']['outputs'][0]['address'], target_address)

    async def test_null_max_key_fee(self):
        target_address = await self.blockchain.get_raw_change_address()
        self.daemon.conf.max_key_fee = None

        await self.stream_create(
            'somename', '0.5', data=b'Yes, please',
            fee_currency='LBC', fee_amount='1.0', fee_address=target_address
        )
        self.assertTrue(await self.daemon.jsonrpc_file_delete(claim_name='somename'))
        # Assert the fee and bid are subtracted
        await self.assertBalance(self.account, '9.483893')
        response = await self.daemon.jsonrpc_get('lbry://somename')
        await self.ledger.wait(response.content_fee)
        await self.assertBalance(self.account, '8.483752')

        # Assert the file downloads
        await asyncio.wait_for(self.wait_files_to_complete(), timeout=1)
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 1)

        # Assert the transaction is recorded to the blockchain
        starting_balance = await self.blockchain.get_balance()
        await self.generate(1)
        block_reward_and_claim_fee = 2.0
        self.assertEqual(
            await self.blockchain.get_balance(), starting_balance + block_reward_and_claim_fee
        )

    async def test_null_fee(self):
        target_address = await self.blockchain.get_raw_change_address()
        tx = await self.stream_create(
            'nullfee', '0.01', data=b'no pay me, no',
            fee_currency='LBC', fee_address=target_address, fee_amount='1.0'
        )
        await self.__raw_value_update_no_fee_amount(tx, target_address)
        await self.daemon.jsonrpc_file_delete(claim_name='nullfee')
        response = await self.daemon.jsonrpc_get('lbry://nullfee')
        self.assertItemCount(await self.daemon.jsonrpc_file_list(), 1)
        self.assertIsNone(response.content_fee)
        self.assertTrue(response.stream_claim_info.claim.stream.has_fee)
        self.assertDictEqual(
            response.stream_claim_info.claim.stream.to_dict()['fee'],
            {'currency': 'LBC', 'address': target_address}
        )
        await self.daemon.jsonrpc_file_delete(claim_name='nullfee')

    async def __raw_value_update_no_fee_address(self, tx, claim_address, **kwargs):
        tx = await self.daemon.jsonrpc_stream_update(
            self.get_claim_id(tx), preview=True, claim_address=claim_address, **kwargs
        )
        tx.outputs[0].claim.stream.fee.address_bytes = b''
        tx.outputs[0].script.generate()
        await tx.sign([self.account])
        await self.broadcast(tx)
        await self.confirm_tx(tx.id)

    async def __raw_value_update_no_fee_amount(self, tx, claim_address):
        tx = await self.daemon.jsonrpc_stream_update(
            self.get_claim_id(tx), preview=True, fee_currency='LBC', fee_amount='1.0', fee_address=claim_address,
            claim_address=claim_address
        )
        tx.outputs[0].claim.stream.fee.message.ClearField('amount')
        tx.outputs[0].script.generate()
        await tx.sign([self.account])
        await self.broadcast(tx)
        await self.confirm_tx(tx.id)
