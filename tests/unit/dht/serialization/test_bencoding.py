import unittest
from lbrynet.dht.serialization.bencoding import bencode, bdecode


class EncodeDecodeTest(unittest.TestCase):
    def test_dict(self):
        self.assertEqual(bencode({b'foo': 42, b'bar': b'spam', b'baz': [b'derp', b'wurp']}),
                         b'd3:bar4:spam3:bazl4:derp4:wurpe3:fooi42ee')
        self.assertEqual(bdecode(b'd3:bar4:spam3:bazl4:derp4:wurpe3:fooi42ee'),
                         {b'foo': 42, b'bar': b'spam', b'baz': [b'derp', b'wurp']})

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
