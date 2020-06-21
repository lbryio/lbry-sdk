import unittest
from binascii import unhexlify
from lbry.blockchain.database import FindShortestID


class FindShortestIDTest(unittest.TestCase):

    def test_canonical_find_shortest_id(self):
        new_hash = unhexlify('abcdef0123456789beef')[::-1]
        other0 = unhexlify('1bcdef0123456789beef')[::-1]
        other1 = unhexlify('ab1def0123456789beef')[::-1]
        other2 = unhexlify('abc1ef0123456789beef')[::-1]
        other3 = unhexlify('abcdef0123456789bee1')[::-1]
        f = FindShortestID()
        f.step(other0, new_hash)
        self.assertEqual('a', f.finalize())
        f.step(other1, new_hash)
        self.assertEqual('abc', f.finalize())
        f.step(other2, new_hash)
        self.assertEqual('abcd', f.finalize())
        f.step(other3, new_hash)
        self.assertEqual('abcdef0123456789beef', f.finalize())
