import unittest
from lbrynet.dht.serialization.bencoding import _bencode, bencode, bdecode, DecodeError


class EncodeDecodeTest(unittest.TestCase):
    def test_fail_with_not_dict(self):
        with self.assertRaises(TypeError):
            bencode(1)
        with self.assertRaises(TypeError):
            bencode(b'derp')
        with self.assertRaises(TypeError):
            bencode('derp')
        with self.assertRaises(TypeError):
            bencode([b'derp'])
        with self.assertRaises(TypeError):
            bencode([object()])
        with self.assertRaises(TypeError):
            bencode({b'derp': object()})

    def test_integer(self):
        self.assertEqual(_bencode(42), b'i42e')
        self.assertEqual(bdecode(b'i42e', True), 42)

    def test_bytes(self):
        self.assertEqual(_bencode(b''), b'0:')
        self.assertEqual(_bencode(b'spam'), b'4:spam')
        self.assertEqual(_bencode(b'4:spam'), b'6:4:spam')
        self.assertEqual(_bencode(bytearray(b'spam')), b'4:spam')

        self.assertEqual(bdecode(b'0:', True), b'')
        self.assertEqual(bdecode(b'4:spam', True), b'spam')
        self.assertEqual(bdecode(b'6:4:spam', True), b'4:spam')

    def test_string(self):
        self.assertEqual(_bencode(''), b'0:')
        self.assertEqual(_bencode('spam'), b'4:spam')
        self.assertEqual(_bencode('4:spam'), b'6:4:spam')

    def test_list(self):
        self.assertEqual(_bencode([b'spam', 42]), b'l4:spami42ee')
        self.assertEqual(bdecode(b'l4:spami42ee', True), [b'spam', 42])

    def test_dict(self):
        self.assertEqual(bencode({b'foo': 42, b'bar': b'spam'}), b'd3:bar4:spam3:fooi42ee')
        self.assertEqual(bdecode(b'd3:bar4:spam3:fooi42ee'), {b'foo': 42, b'bar': b'spam'})

    def test_mixed(self):
        self.assertEqual(_bencode(
            [[b'abc', b'127.0.0.1', 1919], [b'def', b'127.0.0.1', 1921]]),
            b'll3:abc9:127.0.0.1i1919eel3:def9:127.0.0.1i1921eee'
        )

        self.assertEqual(bdecode(
            b'll3:abc9:127.0.0.1i1919eel3:def9:127.0.0.1i1921eee', True),
            [[b'abc', b'127.0.0.1', 1919], [b'def', b'127.0.0.1', 1921]]
        )

    def test_decode_error(self):
        self.assertRaises(DecodeError, bdecode, b'abcdefghijklmnopqrstuvwxyz', True)
        self.assertRaises(DecodeError, bdecode, b'', True)
