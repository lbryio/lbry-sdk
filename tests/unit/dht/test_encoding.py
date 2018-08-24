from twisted.trial import unittest
from lbrynet.dht.encoding import bencode, bdecode, DecodeError


class EncodeDecodeTest(unittest.TestCase):

    def test_integer(self):
        self.assertEqual(bencode(42), b'i42e')

        self.assertEqual(bdecode(b'i42e'), 42)

    def test_bytes(self):
        self.assertEqual(bencode(b''), b'0:')
        self.assertEqual(bencode(b'spam'), b'4:spam')
        self.assertEqual(bencode(b'4:spam'), b'6:4:spam')
        self.assertEqual(bencode(bytearray(b'spam')), b'4:spam')

        self.assertEqual(bdecode(b'0:'), b'')
        self.assertEqual(bdecode(b'4:spam'), b'spam')
        self.assertEqual(bdecode(b'6:4:spam'), b'4:spam')

    def test_string(self):
        self.assertEqual(bencode(''), b'0:')
        self.assertEqual(bencode('spam'), b'4:spam')
        self.assertEqual(bencode('4:spam'), b'6:4:spam')

    def test_list(self):
        self.assertEqual(bencode([b'spam', 42]), b'l4:spami42ee')

        self.assertEqual(bdecode(b'l4:spami42ee'), [b'spam', 42])

    def test_dict(self):
        self.assertEqual(bencode({b'foo': 42, b'bar': b'spam'}), b'd3:bar4:spam3:fooi42ee')

        self.assertEqual(bdecode(b'd3:bar4:spam3:fooi42ee'), {b'foo': 42, b'bar': b'spam'})

    def test_mixed(self):
        self.assertEqual(bencode(
            [[b'abc', b'127.0.0.1', 1919], [b'def', b'127.0.0.1', 1921]]),
            b'll3:abc9:127.0.0.1i1919eel3:def9:127.0.0.1i1921eee'
        )

        self.assertEqual(bdecode(
            b'll3:abc9:127.0.0.1i1919eel3:def9:127.0.0.1i1921eee'),
            [[b'abc', b'127.0.0.1', 1919], [b'def', b'127.0.0.1', 1921]]
        )

    def test_decode_error(self):
        self.assertRaises(DecodeError, bdecode, b'abcdefghijklmnopqrstuvwxyz')
        self.assertRaises(DecodeError, bdecode, b'')
