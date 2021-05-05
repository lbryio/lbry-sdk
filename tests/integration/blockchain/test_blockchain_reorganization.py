import logging
import asyncio
from binascii import hexlify
from lbry.testcase import CommandTestCase


class BlockchainReorganizationTests(CommandTestCase):

    VERBOSITY = logging.WARN

    async def assertBlockHash(self, height):
        bp = self.conductor.spv_node.server.bp

        def get_txids():
            return [
                bp.db.fs_tx_hash(tx_num)[0][::-1].hex()
                for tx_num in range(bp.db.tx_counts[height - 1], bp.db.tx_counts[height])
            ]

        block_hash = await self.blockchain.get_block_hash(height)

        self.assertEqual(block_hash, (await self.ledger.headers.hash(height)).decode())
        self.assertEqual(block_hash, (await bp.db.fs_block_hashes(height, 1))[0][::-1].hex())

        txids = await asyncio.get_event_loop().run_in_executor(bp.db.executor, get_txids)
        txs = await bp.db.fs_transactions(txids)
        block_txs = (await bp.daemon.deserialised_block(block_hash))['tx']
        self.assertSetEqual(set(block_txs), set(txs.keys()), msg='leveldb/lbrycrd is missing transactions')
        self.assertListEqual(block_txs, list(txs.keys()), msg='leveldb/lbrycrd transactions are of order')

    async def test_reorg(self):
        bp = self.conductor.spv_node.server.bp
        bp.reorg_count_metric.set(0)
        # invalidate current block, move forward 2
        height = 206
        self.assertEqual(self.ledger.headers.height, height)
        await self.assertBlockHash(height)
        await self.blockchain.invalidate_block((await self.ledger.headers.hash(206)).decode())
        await self.blockchain.generate(2)
        await self.ledger.on_header.where(lambda e: e.height == 207)
        self.assertEqual(self.ledger.headers.height, 207)
        await self.assertBlockHash(206)
        await self.assertBlockHash(207)
        self.assertEqual(1, bp.reorg_count_metric._samples()[0][2])

        # invalidate current block, move forward 3
        await self.blockchain.invalidate_block((await self.ledger.headers.hash(206)).decode())
        await self.blockchain.generate(3)
        await self.ledger.on_header.where(lambda e: e.height == 208)
        self.assertEqual(self.ledger.headers.height, 208)
        await self.assertBlockHash(206)
        await self.assertBlockHash(207)
        await self.assertBlockHash(208)
        self.assertEqual(2, bp.reorg_count_metric._samples()[0][2])
        await self.blockchain.generate(3)
        await self.ledger.on_header.where(lambda e: e.height == 211)
        await self.assertBlockHash(209)
        await self.assertBlockHash(210)
        await self.assertBlockHash(211)
        still_valid = await self.daemon.jsonrpc_stream_create(
            'still-valid', '1.0', file_path=self.create_upload_file(data=b'hi!')
        )
        await self.ledger.wait(still_valid)
        await self.blockchain.generate(1)
        await self.ledger.on_header.where(lambda e: e.height == 212)
        claim_id = still_valid.outputs[0].claim_id
        c1 = (await self.resolve(f'still-valid#{claim_id}'))['claim_id']
        c2 = (await self.resolve(f'still-valid#{claim_id[:2]}'))['claim_id']
        c3 = (await self.resolve(f'still-valid'))['claim_id']
        self.assertTrue(c1 == c2 == c3)

        abandon_tx = await self.daemon.jsonrpc_stream_abandon(claim_id=claim_id)
        await self.blockchain.generate(1)
        await self.ledger.on_header.where(lambda e: e.height == 213)
        c1 = await self.resolve(f'still-valid#{still_valid.outputs[0].claim_id}')
        c2 = await self.daemon.jsonrpc_resolve([f'still-valid#{claim_id[:2]}'])
        c3 = await self.daemon.jsonrpc_resolve([f'still-valid'])

    async def test_reorg_change_claim_height(self):
        # sanity check
        result = await self.resolve('hovercraft')  # TODO: do these for claim_search and resolve both
        self.assertIn('error', result)

        still_valid = await self.daemon.jsonrpc_stream_create(
            'still-valid', '1.0', file_path=self.create_upload_file(data=b'hi!')
        )
        await self.ledger.wait(still_valid)
        await self.generate(1)

        # create a claim and verify it's returned by claim_search
        self.assertEqual(self.ledger.headers.height, 207)
        await self.assertBlockHash(207)

        broadcast_tx = await self.daemon.jsonrpc_stream_create(
            'hovercraft', '1.0', file_path=self.create_upload_file(data=b'hi!')
        )
        await self.ledger.wait(broadcast_tx)
        await self.generate(1)
        await self.ledger.wait(broadcast_tx, self.blockchain.block_expected)
        self.assertEqual(self.ledger.headers.height, 208)
        await self.assertBlockHash(208)

        claim = await self.resolve('hovercraft')
        self.assertEqual(claim['txid'], broadcast_tx.id)
        self.assertEqual(claim['height'], 208)

        # check that our tx is in block 208 as returned by lbrycrdd
        invalidated_block_hash = (await self.ledger.headers.hash(208)).decode()
        block_207 = await self.blockchain.get_block(invalidated_block_hash)
        self.assertIn(claim['txid'], block_207['tx'])
        self.assertEqual(208, claim['height'])

        # reorg the last block dropping our claim tx
        await self.blockchain.invalidate_block(invalidated_block_hash)
        await self.blockchain.clear_mempool()
        await self.blockchain.generate(2)

        # wait for the client to catch up and verify the reorg
        await asyncio.wait_for(self.on_header(209), 3.0)
        await self.assertBlockHash(207)
        await self.assertBlockHash(208)
        await self.assertBlockHash(209)

        # verify the claim was dropped from block 208 as returned by lbrycrdd
        reorg_block_hash = await self.blockchain.get_block_hash(208)
        self.assertNotEqual(invalidated_block_hash, reorg_block_hash)
        block_207 = await self.blockchain.get_block(reorg_block_hash)
        self.assertNotIn(claim['txid'], block_207['tx'])

        client_reorg_block_hash = (await self.ledger.headers.hash(208)).decode()
        self.assertEqual(client_reorg_block_hash, reorg_block_hash)

        # verify the dropped claim is no longer returned by claim search
        self.assertDictEqual(
            {'error': {'name': 'NOT_FOUND', 'text': 'Could not find claim at "hovercraft".'}},
            await self.resolve('hovercraft')
        )

        # verify the claim published a block earlier wasn't also reverted
        self.assertEqual(207, (await self.resolve('still-valid'))['height'])

        # broadcast the claim in a different block
        new_txid = await self.blockchain.sendrawtransaction(hexlify(broadcast_tx.raw).decode())
        self.assertEqual(broadcast_tx.id, new_txid)
        await self.blockchain.generate(1)

        # wait for the client to catch up
        await asyncio.wait_for(self.on_header(210), 1.0)

        # verify the claim is in the new block and that it is returned by claim_search
        republished = await self.resolve('hovercraft')
        self.assertEqual(210, republished['height'])
        self.assertEqual(claim['claim_id'], republished['claim_id'])

        # this should still be unchanged
        self.assertEqual(207, (await self.resolve('still-valid'))['height'])

    async def test_reorg_drop_claim(self):
        # sanity check
        result = await self.resolve('hovercraft')  # TODO: do these for claim_search and resolve both
        self.assertIn('error', result)

        still_valid = await self.daemon.jsonrpc_stream_create(
            'still-valid', '1.0', file_path=self.create_upload_file(data=b'hi!')
        )
        await self.ledger.wait(still_valid)
        await self.generate(1)

        # create a claim and verify it's returned by claim_search
        self.assertEqual(self.ledger.headers.height, 207)
        await self.assertBlockHash(207)

        broadcast_tx = await self.daemon.jsonrpc_stream_create(
            'hovercraft', '1.0', file_path=self.create_upload_file(data=b'hi!')
        )
        await self.ledger.wait(broadcast_tx)
        await self.generate(1)
        await self.ledger.wait(broadcast_tx, self.blockchain.block_expected)
        self.assertEqual(self.ledger.headers.height, 208)
        await self.assertBlockHash(208)

        claim = await self.resolve('hovercraft')
        self.assertEqual(claim['txid'], broadcast_tx.id)
        self.assertEqual(claim['height'], 208)

        # check that our tx is in block 208 as returned by lbrycrdd
        invalidated_block_hash = (await self.ledger.headers.hash(208)).decode()
        block_207 = await self.blockchain.get_block(invalidated_block_hash)
        self.assertIn(claim['txid'], block_207['tx'])
        self.assertEqual(208, claim['height'])

        # reorg the last block dropping our claim tx
        await self.blockchain.invalidate_block(invalidated_block_hash)
        await self.blockchain.clear_mempool()
        await self.blockchain.generate(2)

        # wait for the client to catch up and verify the reorg
        await asyncio.wait_for(self.on_header(209), 3.0)
        await self.assertBlockHash(207)
        await self.assertBlockHash(208)
        await self.assertBlockHash(209)

        # verify the claim was dropped from block 208 as returned by lbrycrdd
        reorg_block_hash = await self.blockchain.get_block_hash(208)
        self.assertNotEqual(invalidated_block_hash, reorg_block_hash)
        block_207 = await self.blockchain.get_block(reorg_block_hash)
        self.assertNotIn(claim['txid'], block_207['tx'])

        client_reorg_block_hash = (await self.ledger.headers.hash(208)).decode()
        self.assertEqual(client_reorg_block_hash, reorg_block_hash)

        # verify the dropped claim is no longer returned by claim search
        self.assertDictEqual(
            {'error': {'name': 'NOT_FOUND', 'text': 'Could not find claim at "hovercraft".'}},
            await self.resolve('hovercraft')
        )

        # verify the claim published a block earlier wasn't also reverted
        self.assertEqual(207, (await self.resolve('still-valid'))['height'])

        # broadcast the claim in a different block
        new_txid = await self.blockchain.sendrawtransaction(hexlify(broadcast_tx.raw).decode())
        self.assertEqual(broadcast_tx.id, new_txid)
        await self.blockchain.generate(1)

        # wait for the client to catch up
        await asyncio.wait_for(self.on_header(210), 1.0)

        # verify the claim is in the new block and that it is returned by claim_search
        republished = await self.resolve('hovercraft')
        self.assertEqual(210, republished['height'])
        self.assertEqual(claim['claim_id'], republished['claim_id'])

        # this should still be unchanged
        self.assertEqual(207, (await self.resolve('still-valid'))['height'])
