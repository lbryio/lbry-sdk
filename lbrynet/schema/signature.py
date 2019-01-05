from collections import namedtuple

LEGACY = namedtuple('Legacy', 'payload')
NAMED_SECP256K1 = namedtuple('NamedSECP256k1', 'raw_signature certificate_id payload')
FLAGS = {
    LEGACY: 0x80,
    NAMED_SECP256K1: 0x01
}

class Signature:

    def __init__(self, data: namedtuple):
        assert isinstance(data, (LEGACY, NAMED_SECP256K1))
        self.data = data

    @property
    def payload(self):
        return self.data.payload

    @property
    def certificate_id(self):
        if type(self.data) == NAMED_SECP256K1:
            return self.data.certificate_id

    @property
    def raw_signature(self):
        if type(self.data) == NAMED_SECP256K1:
            return self.data.raw_signature

    @classmethod
    def flagged_parse(cls, binary: bytes):
        flag = binary[0]
        if flag == FLAGS[NAMED_SECP256K1]:
            return cls(NAMED_SECP256K1(binary[1:65], binary[65:85], binary[85:]))
        else:
            return cls(LEGACY(binary))

    @property
    def serialized(self):
        if isinstance(self.data, NAMED_SECP256K1):
            return (bytes([FLAGS[type(self.data)]]) + self.data.raw_signature + self.data.certificate_id + self.payload)
        elif isinstance(self.data, LEGACY):
            return self.payload
