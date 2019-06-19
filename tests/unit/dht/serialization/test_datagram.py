import unittest
from lbrynet.dht.error import DecodeError
from lbrynet.dht.serialization.bencoding import _bencode
from lbrynet.dht.serialization.datagram import RequestDatagram, ResponseDatagram, decode_datagram, ErrorDatagram
from lbrynet.dht.serialization.datagram import REQUEST_TYPE, RESPONSE_TYPE, ERROR_TYPE
from lbrynet.dht.serialization.datagram import make_compact_address, decode_compact_address


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
        self.assertListEqual(decoded.args, [b'2' * 48, 0, {b'protocolVersion': 1}])

        # nondefault page argument
        serialized = RequestDatagram.make_find_value(b'1' * 48, b'2' * 48, b'1' * 20, 1).bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, REQUEST_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertEqual(decoded.method, b'findValue')
        self.assertListEqual(decoded.args, [b'2' * 48, 1, {b'protocolVersion': 1}])

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
