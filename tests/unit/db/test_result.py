from unittest import TestCase

from lbry.db import Result


class TestResult(TestCase):

    def test_result(self):
        result = Result([], 0)
        self.assertFalse(result)
        self.assertEqual(0, len(result))
        self.assertEqual(0, result.total)

        result = Result(['a', 'b', 'c'], 100)
        self.assertTrue(result)
        self.assertEqual(3, len(result))
        self.assertEqual(100, result.total)
        self.assertEqual('b', result[1])
        self.assertEqual(['a', 'b', 'c'], [o for o in result])
        self.assertEqual(['a', 'b', 'c'], list(result))
        self.assertEqual("['a', 'b', 'c']", repr(result))
