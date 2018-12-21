import unittest
from lbrynet.dht.serialization.datagram import RequestDatagram, ResponseDatagram, ErrorDatagram, decode_datagram
from lbrynet.dht.serialization.datagram import REQUEST_TYPE, RESPONSE_TYPE, ERROR_TYPE


class TestDatagram(unittest.TestCase):
    def test_ping_request_datagram(self):
        serialized = RequestDatagram(REQUEST_TYPE, b'1' * 20, b'1' * 48, 'ping', []).bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, REQUEST_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertEqual(decoded.method, b'ping')
        self.assertListEqual(decoded.args, [])

    def test_ping_response(self):
        serialized = ResponseDatagram(RESPONSE_TYPE, b'1' * 20, b'1' * 48, b'pong').bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, RESPONSE_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertEqual(decoded.response, b'pong')

    def test_find_node_request_datagram(self):
        serialized = RequestDatagram(REQUEST_TYPE, b'1' * 20, b'1' * 48, 'findNode', [b'2' * 48]).bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, REQUEST_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertEqual(decoded.method, b'findNode')
        self.assertListEqual(decoded.args, [b'2' * 48])

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
        serialized = RequestDatagram(REQUEST_TYPE, b'1' * 20, b'1' * 48, 'findValue', [b'2' * 48]).bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, REQUEST_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertEqual(decoded.method, b'findValue')
        self.assertListEqual(decoded.args, [b'2' * 48])

    def test_find_value_response(self):
        found_value_response = {b'2' * 48: [b'\x7f\x00\x00\x01']}
        serialized = ResponseDatagram(RESPONSE_TYPE, b'1' * 20, b'1' * 48, found_value_response).bencode()
        decoded = decode_datagram(serialized)
        self.assertEqual(decoded.packet_type, RESPONSE_TYPE)
        self.assertEqual(decoded.rpc_id, b'1' * 20)
        self.assertEqual(decoded.node_id, b'1' * 48)
        self.assertDictEqual(decoded.response, found_value_response)


#
# ((RequestMessage('1' * 48, 'rpcMethod',
#                                       {'arg1': 'a string', 'arg2': 123}, '1' * 20),
#                        {DefaultFormat.headerType: DefaultFormat.typeRequest,
#                         DefaultFormat.headerNodeID: '1' * 48,
#                         DefaultFormat.headerMsgID: '1' * 20,
#                         DefaultFormat.headerPayload: 'rpcMethod',
#                         DefaultFormat.headerArgs: {'arg1': 'a string', 'arg2': 123}}),
#
#                       (ResponseMessage('2' * 20, '2' * 48, 'response'),
#                        {DefaultFormat.headerType: DefaultFormat.typeResponse,
#                         DefaultFormat.headerNodeID: '2' * 48,
#                         DefaultFormat.headerMsgID: '2' * 20,
#                         DefaultFormat.headerPayload: 'response'}),
#
#                       (ErrorMessage('3' * 20, '3' * 48,
#                                     "<type 'exceptions.ValueError'>", 'this is a test exception'),
#                        {DefaultFormat.headerType: DefaultFormat.typeError,
#                         DefaultFormat.headerNodeID: '3' * 48,
#                         DefaultFormat.headerMsgID: '3' * 20,
#                         DefaultFormat.headerPayload: "<type 'exceptions.ValueError'>",
#                         DefaultFormat.headerArgs: 'this is a test exception'}),
#
#                       (ResponseMessage(
#                           '4' * 20, '4' * 48,
#                           [('H\x89\xb0\xf4\xc9\xe6\xc5`H>\xd5\xc2\xc5\xe8Od\xf1\xca\xfa\x82',
#                             '127.0.0.1', 1919),
#                            ('\xae\x9ey\x93\xdd\xeb\xf1^\xff\xc5\x0f\xf8\xac!\x0e\x03\x9fY@{',
#                             '127.0.0.1', 1921)]),
#                        {DefaultFormat.headerType: DefaultFormat.typeResponse,
#                         DefaultFormat.headerNodeID: '4' * 48,
#                         DefaultFormat.headerMsgID: '4' * 20,
#                         DefaultFormat.headerPayload:
#                             [('H\x89\xb0\xf4\xc9\xe6\xc5`H>\xd5\xc2\xc5\xe8Od\xf1\xca\xfa\x82',
#                               '127.0.0.1', 1919),
#                              ('\xae\x9ey\x93\xdd\xeb\xf1^\xff\xc5\x0f\xf8\xac!\x0e\x03\x9fY@{',
#                               '127.0.0.1', 1921)]})
#                       )
