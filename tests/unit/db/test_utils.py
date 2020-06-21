import unittest
from lbry.db.utils import chunk


class TestChunk(unittest.TestCase):

    def test_chunk(self):
        self.assertEqual(list(chunk([], 3)), [])
        self.assertEqual(list(chunk(['a'], 3)), [['a']])
        self.assertEqual(list(chunk(['a', 'b', 'c'], 3)), [['a', 'b', 'c']])
        self.assertEqual(list(chunk(['a', 'b', 'c', 'd'], 3)), [['a', 'b', 'c'], ['d']])
        self.assertEqual(
            list(chunk(['a', 'b', 'c', 'd', 'e', 'f', 'g'], 3)),
            [['a', 'b', 'c'], ['d', 'e', 'f'], ['g']]
        )
