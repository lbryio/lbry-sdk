import typing
from lbrynet.dht import constants
from lbrynet.dht.serialization import bencoding

REQUEST_TYPE = 0
RESPONSE_TYPE = 1
ERROR_TYPE = 2


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

    def __init__(self, packet_type: int, rpc_id: bytes, node_id: bytes):
        self.packet_type = packet_type
        if len(rpc_id) != constants.rpc_id_length:
            raise ValueError("invalid rpc node_id: %i bytes (expected 20)" % len(rpc_id))
        if not len(node_id) == constants.hash_length:
            raise ValueError("invalid node node_id: %i bytes (expected 48)" % len(node_id))
        self.rpc_id = rpc_id
        self.node_id = node_id

    def bencode(self) -> bytes:
        return bencoding.bencode({
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

    def __init__(self, packet_type: int, rpc_id: bytes, node_id: bytes, method: str,
                 args: typing.Optional[typing.List] = None):
        super().__init__(packet_type, rpc_id, node_id)
        self.method = method
        self.args = args
        if self.packet_type != REQUEST_TYPE:
            raise ValueError


class ResponseDatagram(KademliaDatagramBase):
    fields = [
        'packet_type',
        'rpc_id',
        'node_id',
        'response'
    ]

    packet_type = RESPONSE_TYPE

    def __init__(self, packet_type: int, rpc_id, node_id, response):
        super().__init__(packet_type, rpc_id, node_id)
        self.response = response
        if self.packet_type != RESPONSE_TYPE:
            raise ValueError


class ErrorDatagram(ResponseDatagram):
    fields = [
        'packet_type',
        'rpc_id',
        'node_id',
        'response',
        'exception_type'
    ]

    def __init__(self, packet_type, rpc_id, node_id, exception_type, response):
        super().__init__(packet_type, rpc_id, node_id, response)
        self.exception_type = exception_type
        if self.packet_type != ERROR_TYPE:
            raise ValueError


msg_types = {
    REQUEST_TYPE: RequestDatagram,
    RESPONSE_TYPE: ResponseDatagram,
    ERROR_TYPE: ErrorDatagram
}


def decode_datagram(datagram: bytes) -> typing.Union[RequestDatagram, ResponseDatagram, ErrorDatagram]:
    msg_types = {
        REQUEST_TYPE: RequestDatagram,
        RESPONSE_TYPE: ResponseDatagram,
        ERROR_TYPE: ErrorDatagram
    }
    primative = bencoding.bdecode(datagram)
    if primative[0] in msg_types:
        dgram_class = msg_types[primative[0]]
        kw = {}
        for i, k in enumerate(dgram_class.fields):
            if i in primative:
                kw[k] = primative[i]
        result = dgram_class(**kw)
        return result
    raise ValueError
