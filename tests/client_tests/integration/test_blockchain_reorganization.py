import logging
from torba.testcase import IntegrationTestCase


class BlockchainReorganizationTests(IntegrationTestCase):

    VERBOSITY = logging.WARN

    async def test_reorg(self):
        # invalidate current block, move forward 2
        self.assertEqual(self.ledger.headers.height, 200)
        self.assertEqual(
            self.ledger.headers.hash(200).decode(),
            await self.blockchain.get_block_hash(200)
        )
        await self.blockchain.invalidate_block(self.ledger.headers.hash(200).decode())
        await self.blockchain.generate(2)
        await self.ledger.on_header.where(lambda e: e.height == 201)
        self.assertEqual(self.ledger.headers.height, 201)
        self.assertEqual(
            self.ledger.headers.hash(200).decode(),
            await self.blockchain.get_block_hash(200)
        )

        # invalidate current block, move forward 3
        await self.blockchain.invalidate_block(self.ledger.headers.hash(200).decode())
        await self.blockchain.generate(3)
        await self.ledger.on_header.where(lambda e: e.height == 202)
        self.assertEqual(self.ledger.headers.height, 202)
