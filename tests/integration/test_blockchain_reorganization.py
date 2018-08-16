from orchstr8.testcase import IntegrationTestCase


class BlockchainReorganizationTests(IntegrationTestCase):

    VERBOSE = True

    async def test(self):
        self.assertEqual(self.ledger.headers.height, 200)

        await self.blockchain.generate(1)
        await self.on_header(201)
        self.assertEqual(self.ledger.headers.height, 201)

        await self.blockchain.invalidateblock(self.ledger.headers.hash(201).decode())
        await self.blockchain.generate(2)
        await self.on_header(203)
