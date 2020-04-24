import logging
import asyncio
from binascii import hexlify
from lbry.testcase import CommandTestCase
from lbry.wallet.server import prometheus


class BlockchainReorganizationTests(CommandTestCase):

    VERBOSITY = logging.WARN

    async def assertBlockHash(self, height):
        self.assertEqual(
            (await self.ledger.headers.hash(height)).decode(),
            await self.blockchain.get_block_hash(height)
        )

    async def test_reorg(self):
        prometheus.METRICS.REORG_COUNT.set(0)
        # invalidate current block, move forward 2
        self.assertEqual(self.ledger.headers.height, 206)
        await self.assertBlockHash(206)
        await self.blockchain.invalidate_block((await self.ledger.headers.hash(206)).decode())
        await self.blockchain.generate(2)
        await self.ledger.on_header.where(lambda e: e.height == 207)
        self.assertEqual(self.ledger.headers.height, 207)
        await self.assertBlockHash(206)
        await self.assertBlockHash(207)
        self.assertEqual(1, prometheus.METRICS.REORG_COUNT._samples()[0][2])

        # invalidate current block, move forward 3
        await self.blockchain.invalidate_block((await self.ledger.headers.hash(206)).decode())
        await self.blockchain.generate(3)
        await self.ledger.on_header.where(lambda e: e.height == 208)
        self.assertEqual(self.ledger.headers.height, 208)
        await self.assertBlockHash(206)
        await self.assertBlockHash(207)
        await self.assertBlockHash(208)
        self.assertEqual(2, prometheus.METRICS.REORG_COUNT._samples()[0][2])

    async def test_reorg_change_claim_height(self):
        # sanity check
        txos, _, _, _ = await self.ledger.claim_search([], name='hovercraft')
        self.assertListEqual(txos, [])

        still_valid = await self.daemon.jsonrpc_stream_create(
            'still-valid', '1.0', file_path=self.create_upload_file(data=b'hi!')
        )
        await self.ledger.wait(still_valid)
        await self.generate(1)

        # create a claim and verify it's returned by claim_search
        self.assertEqual(self.ledger.headers.height, 207)
        broadcast_tx = await self.daemon.jsonrpc_stream_create(
            'hovercraft', '1.0', file_path=self.create_upload_file(data=b'hi!')
        )
        await self.ledger.wait(broadcast_tx)
        await self.generate(1)
        await self.ledger.wait(broadcast_tx, self.blockchain.block_expected)
        self.assertEqual(self.ledger.headers.height, 208)
        txos, _, _, _ = await self.ledger.claim_search([], name='hovercraft')
        self.assertEqual(1, len(txos))
        txo = txos[0]
        self.assertEqual(txo.tx_ref.id, broadcast_tx.id)
        self.assertEqual(txo.tx_ref.height, 208)

        # check that our tx is in block 208 as returned by lbrycrdd
        invalidated_block_hash = (await self.ledger.headers.hash(208)).decode()
        block_207 = await self.blockchain.get_block(invalidated_block_hash)
        self.assertIn(txo.tx_ref.id, block_207['tx'])
        self.assertEqual(208, txos[0].tx_ref.height)

        # reorg the last block dropping our claim tx
        await self.blockchain.invalidate_block(invalidated_block_hash)
        await self.blockchain.clear_mempool()
        await self.blockchain.generate(2)

        # verify the claim was dropped from block 208 as returned by lbrycrdd
        reorg_block_hash = await self.blockchain.get_block_hash(208)
        self.assertNotEqual(invalidated_block_hash, reorg_block_hash)
        block_207 = await self.blockchain.get_block(reorg_block_hash)
        self.assertNotIn(txo.tx_ref.id, block_207['tx'])

        # wait for the client to catch up and verify the reorg
        await asyncio.wait_for(self.on_header(209), 3.0)
        await self.assertBlockHash(207)
        await self.assertBlockHash(208)
        await self.assertBlockHash(209)
        client_reorg_block_hash = (await self.ledger.headers.hash(208)).decode()
        self.assertEqual(client_reorg_block_hash, reorg_block_hash)

        # verify the dropped claim is no longer returned by claim search
        txos, _, _, _ = await self.ledger.claim_search([], name='hovercraft')
        self.assertListEqual(txos, [])

        # verify the claim published a block earlier wasn't also reverted
        txos, _, _, _ = await self.ledger.claim_search([], name='still-valid')
        self.assertEqual(1, len(txos))
        self.assertEqual(207, txos[0].tx_ref.height)

        # broadcast the claim in a different block
        new_txid = await self.blockchain.sendrawtransaction(hexlify(broadcast_tx.raw).decode())
        self.assertEqual(broadcast_tx.id, new_txid)
        await self.blockchain.generate(1)

        # wait for the client to catch up
        await asyncio.wait_for(self.on_header(210), 1.0)

        # verify the claim is in the new block and that it is returned by claim_search
        block_210 = await self.blockchain.get_block((await self.ledger.headers.hash(210)).decode())
        self.assertIn(txo.tx_ref.id, block_210['tx'])
        txos, _, _, _ = await self.ledger.claim_search([], name='hovercraft')
        self.assertEqual(1, len(txos))
        self.assertEqual(txos[0].tx_ref.id, new_txid)
        self.assertEqual(210, txos[0].tx_ref.height)

        # this should still be unchanged
        txos, _, _, _ = await self.ledger.claim_search([], name='still-valid')
        self.assertEqual(1, len(txos))
        self.assertEqual(207, txos[0].tx_ref.height)
