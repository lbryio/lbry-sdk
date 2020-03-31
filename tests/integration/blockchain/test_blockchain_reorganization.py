import logging
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
