import unittest
from lbry import utils


class UtilsTestCase(unittest.TestCase):

    def test_get_colliding_prefix_bits(self):
        self.assertEqual(
            0, utils.get_colliding_prefix_bits(0xffffffff.to_bytes(4, "big"), 0x0000000000.to_bytes(4, "big")))
        self.assertEqual(
            1, utils.get_colliding_prefix_bits(0x7fffffff.to_bytes(4, "big"), 0x0000000000.to_bytes(4, "big")))
        self.assertEqual(
            8, utils.get_colliding_prefix_bits(0x00ffffff.to_bytes(4, "big"), 0x0000000000.to_bytes(4, "big")))
        self.assertEqual(
            8, utils.get_colliding_prefix_bits(0x00ffffff.to_bytes(4, "big"), 0x0000000000.to_bytes(4, "big")))
        self.assertEqual(
            1, utils.get_colliding_prefix_bits(0x7fffffff.to_bytes(4, "big"), 0x0000000000.to_bytes(4, "big")))
        self.assertEqual(
            1, utils.get_colliding_prefix_bits(0x7fffffff.to_bytes(4, "big"), 0x0000000000.to_bytes(4, "big")))
