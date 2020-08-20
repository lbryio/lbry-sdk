from unittest import TestCase

from lbry.db.query_context import Event


class TestDBEvents(TestCase):

    def test_enum(self):
        self.assertEqual(Event.get_by_id(1).name, "client.sync.claims.insert")
        self.assertEqual(Event.get_by_name("client.sync.claims.insert").id, 1)
