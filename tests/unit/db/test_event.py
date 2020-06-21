from unittest import TestCase

from lbry.db.query_context import Event


class TestDBEvents(TestCase):

    def test_enum(self):
        self.assertEqual(Event.BLOCK_READ.value, 1)
        self.assertEqual(Event.BLOCK_READ.label, "blockchain.sync.block.read")
        self.assertEqual(Event(1).label, "blockchain.sync.block.read")
