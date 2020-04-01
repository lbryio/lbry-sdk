import logging
import asyncio
from binascii import unhexlify
from lbry.testcase import CommandTestCase
from lbry.wallet.server.prometheus import REORG_COUNT
from lbry.wallet.transaction import Transaction


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
        result_txs, _, _, _ = await self.ledger.claim_search([], name='hovercraft')
        self.assertListEqual(result_txs, [])

        # create a claim and verify it is returned by claim_search
        self.assertEqual(self.ledger.headers.height, 206)
        broadcast_tx = Transaction(unhexlify((await self.stream_create(name='hovercraft'))['hex'].encode()))
        self.assertEqual(self.ledger.headers.height, 207)
        result_txs, _, _, _ = await self.ledger.claim_search([], name='hovercraft')
        self.assertEqual(1, len(result_txs))
        tx = result_txs[0]
        self.assertEqual(tx.tx_ref.id, broadcast_tx.id)

        # check that our tx is in block 207 as returned by lbrycrdd
        invalidated_block_hash = (await self.ledger.headers.hash(207)).decode()
        block_207 = await self.blockchain.get_block(invalidated_block_hash)
        self.assertIn(tx.tx_ref.id, block_207['tx'])

        # reorg the last block dropping our claim tx
        await self.blockchain.invalidate_block(invalidated_block_hash)
        await self.blockchain.clear_mempool()
        await self.blockchain.generate(2)

        # verify the claim was dropped from block 207 as returned by lbrycrdd
        reorg_block_hash = await self.blockchain.get_block_hash(207)
        self.assertNotEqual(invalidated_block_hash, reorg_block_hash)
        block_207 = await self.blockchain.get_block(reorg_block_hash)
        self.assertNotIn(tx.tx_ref.id, block_207['tx'])

        # wait for the client to catch up and verify the reorg
        await asyncio.wait_for(self.on_header(208), 3.0)
        await self.assertBlockHash(206)
        await self.assertBlockHash(207)
        await self.assertBlockHash(208)
        client_reorg_block_hash = (await self.ledger.headers.hash(207)).decode()
        self.assertEqual(client_reorg_block_hash, reorg_block_hash)

        result_txs, _, _, _ = await self.ledger.claim_search([], name='hovercraft')
        self.assertListEqual(result_txs, [])
