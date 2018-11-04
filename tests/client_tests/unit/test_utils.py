import unittest

from torba.client.util import ArithUint256


class TestArithUint256(unittest.TestCase):

    def test_arithunit256(self):
        # https://github.com/bitcoin/bitcoin/blob/master/src/test/arith_uint256_tests.cpp

        from_compact = ArithUint256.from_compact
        eq = self.assertEqual

        eq(from_compact(0).value, 0)
        eq(from_compact(0x00123456).value, 0)
        eq(from_compact(0x01003456).value, 0)
        eq(from_compact(0x02000056).value, 0)
        eq(from_compact(0x03000000).value, 0)
        eq(from_compact(0x04000000).value, 0)
        eq(from_compact(0x00923456).value, 0)
        eq(from_compact(0x01803456).value, 0)
        eq(from_compact(0x02800056).value, 0)
        eq(from_compact(0x03800000).value, 0)
        eq(from_compact(0x04800000).value, 0)

        # Make sure that we don't generate compacts with the 0x00800000 bit set
        uint = ArithUint256(0x80)
        eq(uint.compact,  0x02008000)

        uint = from_compact(0x01123456)
        eq(uint.value, 0x12)
        eq(uint.compact, 0x01120000)

        uint = from_compact(0x01fedcba)
        eq(uint.value, 0x7e)
        eq(uint.negative, 0x01fe0000)

        uint = from_compact(0x02123456)
        eq(uint.value, 0x1234)
        eq(uint.compact, 0x02123400)

        uint = from_compact(0x03123456)
        eq(uint.value, 0x123456)
        eq(uint.compact, 0x03123456)

        uint = from_compact(0x04123456)
        eq(uint.value, 0x12345600)
        eq(uint.compact, 0x04123456)

        uint = from_compact(0x04923456)
        eq(uint.value, 0x12345600)
        eq(uint.negative, 0x04923456)

        uint = from_compact(0x05009234)
        eq(uint.value, 0x92340000)
        eq(uint.compact, 0x05009234)

        uint = from_compact(0x20123456)
        eq(uint.value, 0x1234560000000000000000000000000000000000000000000000000000000000)
        eq(uint.compact, 0x20123456)
