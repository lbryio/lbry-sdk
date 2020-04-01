import logging
import asyncio
from lbry.testcase import CommandTestCase
from lbry.wallet.server.prometheus import REORG_COUNT


class BlockchainReorganizationTests(CommandTestCase):

    VERBOSITY = logging.WARN

    async def assertBlockHash(self, height):
        self.assertEqual(
            (await self.ledger.headers.hash(height)).decode(),
            await self.blockchain.get_block_hash(height)
        )

    async def test_reorg(self):
        REORG_COUNT.set(0)
        # invalidate current block, move forward 2
        self.assertEqual(self.ledger.headers.height, 206)
        await self.assertBlockHash(206)
        await self.blockchain.invalidate_block((await self.ledger.headers.hash(206)).decode())
        await self.blockchain.generate(2)
        await self.ledger.on_header.where(lambda e: e.height == 207)
        self.assertEqual(self.ledger.headers.height, 207)
        await self.assertBlockHash(206)
        await self.assertBlockHash(207)
        self.assertEqual(1, REORG_COUNT._samples()[0][2])

        # invalidate current block, move forward 3
        await self.blockchain.invalidate_block((await self.ledger.headers.hash(206)).decode())
        await self.blockchain.generate(3)
        await self.ledger.on_header.where(lambda e: e.height == 208)
        self.assertEqual(self.ledger.headers.height, 208)
        await self.assertBlockHash(206)
        await self.assertBlockHash(207)
        await self.assertBlockHash(208)
        self.assertEqual(2, REORG_COUNT._samples()[0][2])

    async def test_reorg_dropping_claim(self):
        # sanity check
        txos, _, _, _ = await self.ledger.claim_search([], name='hovercraft')
        self.assertListEqual(txos, [])

        # create a claim and verify it's returned by claim_search
        self.assertEqual(self.ledger.headers.height, 206)
        broadcast_tx = await self.daemon.jsonrpc_stream_create(
            'hovercraft', '1.0', file_path=self.create_upload_file(data=b'hi!')
        )
        await self.ledger.wait(broadcast_tx)
        await self.generate(1)
        await self.ledger.wait(broadcast_tx, self.blockchain.block_expected)
        self.assertEqual(self.ledger.headers.height, 207)
        txos, _, _, _ = await self.ledger.claim_search([], name='hovercraft')
        self.assertEqual(1, len(txos))
        txo = txos[0]
        self.assertEqual(txo.tx_ref.id, broadcast_tx.id)

        # check that our tx is in block 207 as returned by lbrycrdd
        invalidated_block_hash = (await self.ledger.headers.hash(207)).decode()
        block_207 = await self.blockchain.get_block(invalidated_block_hash)
        self.assertIn(txo.tx_ref.id, block_207['tx'])

        # reorg the last block dropping our claim tx
        await self.blockchain.invalidate_block(invalidated_block_hash)
        await self.blockchain.clear_mempool()
        await self.blockchain.generate(2)

        # verify the claim was dropped from block 207 as returned by lbrycrdd
        reorg_block_hash = await self.blockchain.get_block_hash(207)
        self.assertNotEqual(invalidated_block_hash, reorg_block_hash)
        block_207 = await self.blockchain.get_block(reorg_block_hash)
        self.assertNotIn(txo.tx_ref.id, block_207['tx'])

        # wait for the client to catch up and verify the reorg
        await asyncio.wait_for(self.on_header(208), 3.0)
        await self.assertBlockHash(206)
        await self.assertBlockHash(207)
        await self.assertBlockHash(208)
        client_reorg_block_hash = (await self.ledger.headers.hash(207)).decode()
        self.assertEqual(client_reorg_block_hash, reorg_block_hash)

        # verify the dropped claim is no longer returned by claim search
        txos, _, _, _ = await self.ledger.claim_search([], name='hovercraft')
        self.assertListEqual(txos, [])
