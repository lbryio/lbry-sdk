import logging
from unittest import skip
from torba.testcase import IntegrationTestCase


class BlockchainReorganizationTests(IntegrationTestCase):

    VERBOSITY = logging.WARN

    async def test_reorg(self):
        self.assertEqual(self.ledger.headers.height, 200)

        await self.blockchain.generate(1)
        await self.on_header(201)
        self.assertEqual(self.ledger.headers.height, 201)
        height = 201

        # simple fork (rewind+advance to immediate best)
        height = await self._simulate_reorg(height, 1, 1, 2)
        height = await self._simulate_reorg(height, 2, 1, 10)
        height = await self._simulate_reorg(height, 4, 1, 3)
        # lagged fork (rewind+batch catch up with immediate best)
        height = await self._simulate_reorg(height, 4, 2, 3)
        await self._simulate_reorg(height, 4, 4, 3)

    async def _simulate_reorg(self, height, rewind, winners, progress):
        for i in range(rewind):
            await self.blockchain.invalidateblock(self.ledger.headers.hash(height - i).decode())
        await self.blockchain.generate(rewind + winners)
        height = height + winners
        await self.on_header(height)
        for i in range(progress):
            await self.blockchain.generate(1)
            height += 1
            await self.on_header(height)
        self.assertEqual(height, self.ledger.headers.height)
        return height
