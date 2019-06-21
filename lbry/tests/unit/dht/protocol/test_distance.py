import unittest
from lbry.dht.protocol.distance import Distance


class DistanceTests(unittest.TestCase):
    def test_invalid_key_length(self):
        self.assertRaises(ValueError, Distance, b'1' * 47)
        self.assertRaises(ValueError, Distance, b'1' * 49)
        self.assertRaises(ValueError, Distance, b'')

        self.assertRaises(ValueError, Distance(b'0' * 48), b'1' * 47)
        self.assertRaises(ValueError, Distance(b'0' * 48), b'1' * 49)
        self.assertRaises(ValueError, Distance(b'0' * 48), b'')
