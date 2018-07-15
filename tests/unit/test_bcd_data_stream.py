from twisted.trial import unittest

from torba.bcd_data_stream import BCDataStream


class TestBCDataStream(unittest.TestCase):

    def test_write_read(self):
        s = BCDataStream()
        s.write_string(b'a'*252)
        s.write_string(b'b'*254)
        s.write_string(b'c'*(0xFFFF + 1))
        # s.write_string(b'd'*(0xFFFFFFFF + 1))
        s.write_boolean(True)
        s.write_boolean(False)
        s.reset()

        self.assertEqual(s.read_string(), b'a'*252)
        self.assertEqual(s.read_string(), b'b'*254)
        self.assertEqual(s.read_string(), b'c'*(0xFFFF + 1))
        # self.assertEqual(s.read_string(), b'd'*(0xFFFFFFFF + 1))
        self.assertEqual(s.read_boolean(), True)
        self.assertEqual(s.read_boolean(), False)
