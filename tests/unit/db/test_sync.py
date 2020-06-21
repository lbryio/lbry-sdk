from lbry.testcase import UnitDBTestCase


class TestClientDBSync(UnitDBTestCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.add(self.coinbase())

    async def test_process_inputs(self):
        await self.add(self.tx())
        await self.add(self.tx())
        txo1, txo2a, txo2b, txo3a, txo3b = self.outputs
        self.assertEqual([
            (txo1.id, None),
            (txo2b.id, None),
        ], await self.get_txis())
        self.assertEqual([
            (txo1.id, False),
            (txo2a.id, False),
            (txo2b.id, False),
            (txo3a.id, False),
            (txo3b.id, False),
        ], await self.get_txos())
        await self.db.process_all_things_after_sync()
        self.assertEqual([
            (txo1.id, txo1.get_address(self.ledger)),
            (txo2b.id, txo2b.get_address(self.ledger)),
        ], await self.get_txis())
        self.assertEqual([
            (txo1.id, True),
            (txo2a.id, False),
            (txo2b.id, True),
            (txo3a.id, False),
            (txo3b.id, False),
        ], await self.get_txos())

    async def test_process_claims(self):
        claim1 = await self.add(self.create_claim())
        await self.db.process_all_things_after_sync()
        self.assertEqual([claim1.claim_id], await self.get_claims())

        claim2 = await self.add(self.create_claim())
        self.assertEqual([claim1.claim_id], await self.get_claims())
        await self.db.process_all_things_after_sync()
        self.assertEqual([claim1.claim_id, claim2.claim_id], await self.get_claims())

        claim3 = await self.add(self.create_claim())
        claim4 = await self.add(self.create_claim())
        await self.db.process_all_things_after_sync()
        self.assertEqual([
            claim1.claim_id,
            claim2.claim_id,
            claim3.claim_id,
            claim4.claim_id,
        ], await self.get_claims())

        await self.add(self.abandon_claim(claim4))
        await self.db.process_all_things_after_sync()
        self.assertEqual([
            claim1.claim_id, claim2.claim_id, claim3.claim_id
        ], await self.get_claims())

        # create and abandon in same block
        claim5 = await self.add(self.create_claim())
        await self.add(self.abandon_claim(claim5))
        await self.db.process_all_things_after_sync()
        self.assertEqual([
            claim1.claim_id, claim2.claim_id, claim3.claim_id
        ], await self.get_claims())

        # create and abandon in different blocks but with bulk sync
        claim6 = await self.add(self.create_claim())
        await self.add(self.abandon_claim(claim6))
        await self.db.process_all_things_after_sync()
        self.assertEqual([
            claim1.claim_id, claim2.claim_id, claim3.claim_id
        ], await self.get_claims())
