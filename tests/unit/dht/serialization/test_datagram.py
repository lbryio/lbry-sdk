import unittest
from lbrynet.dht.serialization.datagram import RequestDatagram, ResponseDatagram, decode_datagram
from lbrynet.dht.serialization.datagram import REQUEST_TYPE, RESPONSE_TYPE


class TestDatagram(unittest.TestCase):
    def test_ping_request_datagram(self):
        serialized = RequestDatagram(REQUEST_TYPE, b'1' * 20, b'1' * 48, b'ping', []).bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, REQUEST_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertEqual(decoded.method, b'ping')
        self.assertListEqual(decoded.args, [{b'protocolVersion': 1}])

    def test_ping_response(self):
        serialized = ResponseDatagram(RESPONSE_TYPE, b'1' * 20, b'1' * 48, b'pong').bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, RESPONSE_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertEqual(decoded.response, b'pong')

    def test_find_node_request_datagram(self):
        serialized = RequestDatagram(REQUEST_TYPE, b'1' * 20, b'1' * 48, b'findNode', [b'2' * 48]).bencode()
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
        serialized = RequestDatagram(REQUEST_TYPE, b'1' * 20, b'1' * 48, b'findValue', [b'2' * 48]).bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, REQUEST_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertEqual(decoded.method, b'findValue')
        self.assertListEqual(decoded.args, [b'2' * 48, {b'protocolVersion': 1}])

    def test_find_value_response(self):
        found_value_response = {b'2' * 48: [b'\x7f\x00\x00\x01']}
        serialized = ResponseDatagram(RESPONSE_TYPE, b'1' * 20, b'1' * 48, found_value_response).bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, RESPONSE_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertDictEqual(decoded.response, found_value_response)
