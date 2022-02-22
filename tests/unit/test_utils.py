import unittest
from lbry import utils


class UtilsTestCase(unittest.TestCase):

    def test_get_colliding_prefix_bits(self):
        self.assertEqual(
            0, utils.get_colliding_prefix_bits(0xffffff.to_bytes(4, "big"), 0x00000000.to_bytes(4, "big"), 32))
        self.assertEqual(
            1, utils.get_colliding_prefix_bits(0xefffff.to_bytes(4, "big"), 0x00000000.to_bytes(4, "big"), 32))
        self.assertEqual(
            8, utils.get_colliding_prefix_bits(0x00ffff.to_bytes(4, "big"), 0x00000000.to_bytes(4, "big"), 16))
        self.assertEqual(
            8, utils.get_colliding_prefix_bits(0x00ffff.to_bytes(4, "big"), 0x00000000.to_bytes(4, "big"), 8))
        self.assertEqual(
            1, utils.get_colliding_prefix_bits(0xefffff.to_bytes(4, "big"), 0x00000000.to_bytes(4, "big"), 16))
        self.assertEqual(
            1, utils.get_colliding_prefix_bits(0xefffff.to_bytes(4, "big"), 0x00000000.to_bytes(4, "big"), 8))
