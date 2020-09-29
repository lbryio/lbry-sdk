import binascii
import unittest
from lbry.dht.error import DecodeError
from lbry.dht.serialization.bencoding import _bencode
from lbry.dht.serialization.datagram import RequestDatagram, ResponseDatagram, decode_datagram, ErrorDatagram
from lbry.dht.serialization.datagram import _decode_datagram
from lbry.dht.serialization.datagram import REQUEST_TYPE, RESPONSE_TYPE, ERROR_TYPE
from lbry.dht.serialization.datagram import make_compact_address, decode_compact_address


class TestDatagram(unittest.TestCase):
    def test_ping_request_datagram(self):
        self.assertRaises(ValueError, RequestDatagram.make_ping, b'1' * 48, b'1' * 21)
        self.assertRaises(ValueError, RequestDatagram.make_ping, b'1' * 47, b'1' * 20)
        self.assertEqual(20, len(RequestDatagram.make_ping(b'1' * 48).rpc_id))
        serialized = RequestDatagram.make_ping(b'1' * 48, b'1' * 20).bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, REQUEST_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertEqual(decoded.method, b'ping')
        self.assertListEqual(decoded.args, [{b'protocolVersion': 1}])

    def test_ping_response(self):
        self.assertRaises(ValueError, ResponseDatagram, RESPONSE_TYPE, b'1' * 21, b'1' * 48, b'pong')
        self.assertRaises(ValueError, ResponseDatagram, RESPONSE_TYPE, b'1' * 20, b'1' * 49, b'pong')
        self.assertRaises(ValueError, ResponseDatagram, 5, b'1' * 20, b'1' * 48, b'pong')
        serialized = ResponseDatagram(RESPONSE_TYPE, b'1' * 20, b'1' * 48, b'pong').bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, RESPONSE_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertEqual(decoded.response, b'pong')

    def test_find_node_request_datagram(self):
        self.assertRaises(ValueError, RequestDatagram.make_find_node, b'1' * 49, b'2' * 48, b'1' * 20)
        self.assertRaises(ValueError, RequestDatagram.make_find_node, b'1' * 48, b'2' * 49, b'1' * 20)
        self.assertRaises(ValueError, RequestDatagram.make_find_node, b'1' * 48, b'2' * 48, b'1' * 21)
        self.assertEqual(20, len(RequestDatagram.make_find_node(b'1' * 48, b'2' * 48).rpc_id))

        serialized = RequestDatagram.make_find_node(b'1' * 48, b'2' * 48, b'1' * 20).bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, REQUEST_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertEqual(decoded.method, b'findNode')
        self.assertListEqual(decoded.args, [b'2' * 48, {b'protocolVersion': 1}])

    def test_find_node_response(self):
        closest_response = [(b'3' * 48, '1.2.3.4', 1234)]
        expected = [[b'3' * 48, b'1.2.3.4', 1234]]

        serialized = ResponseDatagram(RESPONSE_TYPE, b'1' * 20, b'1' * 48, closest_response).bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, RESPONSE_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertEqual(decoded.response, expected)

    def test_find_value_request(self):
        self.assertRaises(ValueError, RequestDatagram.make_find_value, b'1' * 49, b'2' * 48, b'1' * 20)
        self.assertRaises(ValueError, RequestDatagram.make_find_value, b'1' * 48, b'2' * 49, b'1' * 20)
        self.assertRaises(ValueError, RequestDatagram.make_find_value, b'1' * 48, b'2' * 48, b'1' * 21)
        self.assertRaises(ValueError, RequestDatagram.make_find_value, b'1' * 48, b'2' * 48, b'1' * 20, -1)
        self.assertEqual(20, len(RequestDatagram.make_find_value(b'1' * 48, b'2' * 48).rpc_id))

        # default page argument
        serialized = RequestDatagram.make_find_value(b'1' * 48, b'2' * 48, b'1' * 20).bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, REQUEST_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertEqual(decoded.method, b'findValue')
        self.assertListEqual(decoded.args, [b'2' * 48, {b'protocolVersion': 1, b'p': 0}])

        # nondefault page argument
        serialized = RequestDatagram.make_find_value(b'1' * 48, b'2' * 48, b'1' * 20, 1).bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, REQUEST_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertEqual(decoded.method, b'findValue')
        self.assertListEqual(decoded.args, [b'2' * 48, {b'protocolVersion': 1, b'p': 1}])

    def test_find_value_response_without_pages_field(self):
        found_value_response = {b'2' * 48: [b'\x7f\x00\x00\x01']}
        serialized = ResponseDatagram(RESPONSE_TYPE, b'1' * 20, b'1' * 48, found_value_response).bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, RESPONSE_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertDictEqual(decoded.response, found_value_response)

    def test_find_value_response_with_pages_field(self):
        found_value_response = {b'2' * 48: [b'\x7f\x00\x00\x01'], b'p': 1}
        serialized = ResponseDatagram(RESPONSE_TYPE, b'1' * 20, b'1' * 48, found_value_response).bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, RESPONSE_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertDictEqual(decoded.response, found_value_response)

    def test_store_request(self):
        self.assertRaises(ValueError, RequestDatagram.make_store, b'1' * 47, b'2' * 48, b'3' * 48, 3333, b'1' * 20)
        self.assertRaises(ValueError, RequestDatagram.make_store, b'1' * 48, b'2' * 49, b'3' * 48, 3333, b'1' * 20)
        self.assertRaises(ValueError, RequestDatagram.make_store, b'1' * 48, b'2' * 48, b'3' * 47, 3333, b'1' * 20)
        self.assertRaises(ValueError, RequestDatagram.make_store, b'1' * 48, b'2' * 48, b'3' * 48, -3333, b'1' * 20)
        self.assertRaises(ValueError, RequestDatagram.make_store, b'1' * 48, b'2' * 48, b'3' * 48, 3333, b'1' * 21)

        serialized = RequestDatagram.make_store(b'1' * 48, b'2' * 48, b'3' * 48, 3333, b'1' * 20).bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, REQUEST_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertEqual(decoded.method, b'store')

    def test_error_datagram(self):
        serialized = ErrorDatagram(ERROR_TYPE, b'1' * 20, b'1' * 48, b'FakeErrorType', b'more info').bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, ERROR_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertEqual(decoded.exception_type, 'FakeErrorType')
        self.assertEqual(decoded.response, 'more info')

    def test_invalid_datagram_type(self):
        serialized = b'di0ei5ei1e20:11111111111111111111i2e48:11111111111111111111' \
                     b'1111111111111111111111111111i3e13:FakeErrorTypei4e9:more infoe'
        self.assertRaises(ValueError, decode_datagram, serialized)
        self.assertRaises(DecodeError, decode_datagram, _bencode([1, 2, 3, 4]))

    def test_optional_field_backwards_compatible(self):
        datagram = decode_datagram(_bencode({
            0: 0,
            1: b'\n\xbc\xb5&\x9dl\xfc\x1e\x87\xa0\x8e\x92\x0b\xf3\x9f\xe9\xdf\x8e\x92\xfc',
            2: b'111111111111111111111111111111111111111111111111',
            3: b'ping',
            4: [{b'protocolVersion': 1}],
            5: b'should not error'
        }))
        self.assertEqual(datagram.packet_type, REQUEST_TYPE)
        self.assertEqual(b'ping', datagram.method)

    def test_str_or_int_keys(self):
        datagram = decode_datagram(_bencode({
            b'0': 0,
            b'1': b'\n\xbc\xb5&\x9dl\xfc\x1e\x87\xa0\x8e\x92\x0b\xf3\x9f\xe9\xdf\x8e\x92\xfc',
            b'2': b'111111111111111111111111111111111111111111111111',
            b'3': b'ping',
            b'4': [{b'protocolVersion': 1}],
            b'5': b'should not error'
        }))
        self.assertEqual(datagram.packet_type, REQUEST_TYPE)
        self.assertEqual(b'ping', datagram.method)

    def test_mixed_str_or_int_keys(self):
        # datagram, _ = _bencode({
        #     b'0': 0,
        #     1: b'\n\xbc\xb5&\x9dl\xfc\x1e\x87\xa0\x8e\x92\x0b\xf3\x9f\xe9\xdf\x8e\x92\xfc',
        #     b'2': b'111111111111111111111111111111111111111111111111',
        #     3: b'ping',
        #     b'4': [{b'protocolVersion': 1}],
        #     b'5': b'should not error'
        # }))
        encoded = binascii.unhexlify(b"64313a3069306569316532303a0abcb5269d6cfc1e87a08e920bf39fe9df8e92fc313a3234383a313131313131313131313131313131313131313131313131313131313131313131313131313131313131313131313131693365343a70696e67313a346c6431353a70726f746f636f6c56657273696f6e6931656565313a3531363a73686f756c64206e6f74206572726f7265")
        self.assertDictEqual(
            {
             'packet_type': 0,
             'rpc_id': b'\n\xbc\xb5&\x9dl\xfc\x1e\x87\xa0\x8e\x92\x0b\xf3\x9f\xe9\xdf\x8e\x92\xfc',
             'node_id': b'111111111111111111111111111111111111111111111111',
             'method': b'ping',
             'args': [{b'protocolVersion': 1}]
            }, _decode_datagram(encoded)[0]
        )


class TestCompactAddress(unittest.TestCase):
    def test_encode_decode(self, address='1.2.3.4', port=4444, node_id=b'1' * 48):
        decoded = decode_compact_address(make_compact_address(node_id, address, port))
        self.assertEqual((node_id, address, port), decoded)

    def test_errors(self):
        self.assertRaises(ValueError, make_compact_address, b'1' * 48, '1.2.3.4', 0)
        self.assertRaises(ValueError, make_compact_address, b'1' * 48, '1.2.3.4', 65536)
        self.assertRaises(
            ValueError, decode_compact_address,
            b'\x01\x02\x03\x04\x00\x00111111111111111111111111111111111111111111111111'
        )

        self.assertRaises(ValueError, make_compact_address, b'1' * 48, '1.2.3.4.5', 4444)
        self.assertRaises(ValueError, make_compact_address, b'1' * 47, '1.2.3.4', 4444)
        self.assertRaises(
            ValueError, decode_compact_address,
            b'\x01\x02\x03\x04\x11\\11111111111111111111111111111111111111111111111'
        )
