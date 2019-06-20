import typing
from functools import reduce
from lbrynet.dht import constants
from lbrynet.dht.serialization.bencoding import bencode, bdecode

REQUEST_TYPE = 0
RESPONSE_TYPE = 1
ERROR_TYPE = 2

# bencode representation of argument keys
PAGE_KEY = b'p'


class KademliaDatagramBase:
    """
    field names are used to unwrap/wrap the argument names to index integers that replace them in a datagram
    all packets have an argument dictionary when bdecoded starting with {0: <int>, 1: <bytes>, 2: <bytes>, ...}
    these correspond to the packet_type, rpc_id, and node_id args
    """

    fields = [
        'packet_type',
        'rpc_id',
        'node_id'
    ]

    expected_packet_type = -1

    def __init__(self, packet_type: int, rpc_id: bytes, node_id: bytes):
        self.packet_type = packet_type
        if self.expected_packet_type != packet_type:
            raise ValueError(f"invalid packet type: {packet_type}, expected {self.expected_packet_type}")
        if len(rpc_id) != constants.rpc_id_length:
            raise ValueError(f"invalid rpc node_id: {len(rpc_id)} bytes (expected 20)")
        if not len(node_id) == constants.hash_length:
            raise ValueError(f"invalid node node_id: {len(node_id)} bytes (expected 48)")
        self.rpc_id = rpc_id
        self.node_id = node_id

    def bencode(self) -> bytes:
        return bencode({
           i: getattr(self, k) for i, k in enumerate(self.fields)
        })


class RequestDatagram(KademliaDatagramBase):
    fields = [
        'packet_type',
        'rpc_id',
        'node_id',
        'method',
        'args'
    ]

    expected_packet_type = REQUEST_TYPE

    def __init__(self, packet_type: int, rpc_id: bytes, node_id: bytes, method: bytes,
                 args: typing.Optional[typing.List] = None):
        super().__init__(packet_type, rpc_id, node_id)
        self.method = method
        self.args = args or []
        if not self.args:
            self.args.append({})
        if isinstance(self.args[-1], dict):
            self.args[-1][b'protocolVersion'] = 1
        else:
            self.args.append({b'protocolVersion': 1})

    @classmethod
    def make_ping(cls, from_node_id: bytes, rpc_id: typing.Optional[bytes] = None) -> 'RequestDatagram':
        rpc_id = rpc_id or constants.generate_id()[:constants.rpc_id_length]
        return cls(REQUEST_TYPE, rpc_id, from_node_id, b'ping')

    @classmethod
    def make_store(cls, from_node_id: bytes, blob_hash: bytes, token: bytes, port: int,
                   rpc_id: typing.Optional[bytes] = None) -> 'RequestDatagram':
        rpc_id = rpc_id or constants.generate_id()[:constants.rpc_id_length]
        if len(blob_hash) != constants.hash_bits // 8:
            raise ValueError(f"invalid blob hash length: {len(blob_hash)}")
        if not 0 < port < 65536:
            raise ValueError(f"invalid port: {port}")
        if len(token) != constants.hash_bits // 8:
            raise ValueError(f"invalid token length: {len(token)}")
        store_args = [blob_hash, token, port, from_node_id, 0]
        return cls(REQUEST_TYPE, rpc_id, from_node_id, b'store', store_args)

    @classmethod
    def make_find_node(cls, from_node_id: bytes, key: bytes,
                       rpc_id: typing.Optional[bytes] = None) -> 'RequestDatagram':
        rpc_id = rpc_id or constants.generate_id()[:constants.rpc_id_length]
        if len(key) != constants.hash_bits // 8:
            raise ValueError(f"invalid key length: {len(key)}")
        return cls(REQUEST_TYPE, rpc_id, from_node_id, b'findNode', [key])

    @classmethod
    def make_find_value(cls, from_node_id: bytes, key: bytes,
                        rpc_id: typing.Optional[bytes] = None, page: int = 0) -> 'RequestDatagram':
        rpc_id = rpc_id or constants.generate_id()[:constants.rpc_id_length]
        if len(key) != constants.hash_bits // 8:
            raise ValueError(f"invalid key length: {len(key)}")
        if page < 0:
            raise ValueError(f"cannot request a negative page ({page})")
        return cls(REQUEST_TYPE, rpc_id, from_node_id, b'findValue', [key, {PAGE_KEY: page}])


class ResponseDatagram(KademliaDatagramBase):
    fields = [
        'packet_type',
        'rpc_id',
        'node_id',
        'response'
    ]

    expected_packet_type = RESPONSE_TYPE

    def __init__(self, packet_type: int, rpc_id: bytes, node_id: bytes, response):
        super().__init__(packet_type, rpc_id, node_id)
        self.response = response


class ErrorDatagram(KademliaDatagramBase):
    fields = [
        'packet_type',
        'rpc_id',
        'node_id',
        'exception_type',
        'response',
    ]

    expected_packet_type = ERROR_TYPE

    def __init__(self, packet_type: int, rpc_id: bytes, node_id: bytes, exception_type: bytes, response: bytes):
        super().__init__(packet_type, rpc_id, node_id)
        self.exception_type = exception_type.decode()
        self.response = response.decode()


def decode_datagram(datagram: bytes) -> typing.Union[RequestDatagram, ResponseDatagram, ErrorDatagram]:
    msg_types = {
        REQUEST_TYPE: RequestDatagram,
        RESPONSE_TYPE: ResponseDatagram,
        ERROR_TYPE: ErrorDatagram
    }

    primitive: typing.Dict = bdecode(datagram)
    if primitive[0] in [REQUEST_TYPE, ERROR_TYPE, RESPONSE_TYPE]:  # pylint: disable=unsubscriptable-object
        datagram_type = primitive[0]  # pylint: disable=unsubscriptable-object
    else:
        raise ValueError("invalid datagram type")
    datagram_class = msg_types[datagram_type]
    return datagram_class(**{
            k: primitive[i]  # pylint: disable=unsubscriptable-object
            for i, k in enumerate(datagram_class.fields)
            if i in primitive  # pylint: disable=unsupported-membership-test
        }
    )


def make_compact_ip(address: str) -> bytearray:
    compact_ip = reduce(lambda buff, x: buff + bytearray([int(x)]), address.split('.'), bytearray())
    if len(compact_ip) != 4:
        raise ValueError(f"invalid IPv4 length")
    return compact_ip


def make_compact_address(node_id: bytes, address: str, port: int) -> bytearray:
    compact_ip = make_compact_ip(address)
    if not 0 < port < 65536:
        raise ValueError(f'Invalid port: {port}')
    if len(node_id) != constants.hash_bits // 8:
        raise ValueError(f"invalid node node_id length")
    return compact_ip + port.to_bytes(2, 'big') + node_id


def decode_compact_address(compact_address: bytes) -> typing.Tuple[bytes, str, int]:
    address = "{}.{}.{}.{}".format(*compact_address[:4])
    port = int.from_bytes(compact_address[4:6], 'big')
    node_id = compact_address[6:]
    if not 0 < port < 65536:
        raise ValueError(f'Invalid port: {port}')
    if len(node_id) != constants.hash_bits // 8:
        raise ValueError(f"invalid node node_id length")
    return node_id, address, port
