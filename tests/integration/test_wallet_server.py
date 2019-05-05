from lbrynet.testcase import CommandTestCase


class TestClaimtrie(CommandTestCase):

    def get_claim_id(self, tx):
        return tx['outputs'][0]['claim_id']

    async def assertWinningClaim(self, name, tx):
        other = (await self.resolve(name))[name]
        self.assertEqual(self.get_claim_id(tx), other['claim_id'])

    async def test_designed_edge_cases(self):
        tx1 = await self.channel_create('@foo', allow_duplicate_name=True)
        await self.assertWinningClaim('@foo', tx1)
        tx2 = await self.channel_create('@foo', allow_duplicate_name=True)
        await self.assertWinningClaim('@foo', tx1)
        tx3 = await self.channel_create('@foo', allow_duplicate_name=True)
        await self.assertWinningClaim('@foo', tx1)
        await self.support_create(self.get_claim_id(tx3), '0.09')
        await self.assertWinningClaim('@foo', tx3)
        await self.support_create(self.get_claim_id(tx2), '0.19')
        await self.assertWinningClaim('@foo', tx2)
        await self.support_create(self.get_claim_id(tx1), '0.19')
        await self.assertWinningClaim('@foo', tx1)
