# Flags
LEGACY = 0x80  # Everything is contained in the protobuf.
NAMED_SECP256K1 = 0x01  # ECDSA SECP256k1 64 bytes. Claim name is also signed.


class Signature:

    def __init__(self, raw_signature: bytes, certificate_id: bytes, flag: int=NAMED_SECP256K1):
        self.flag = flag
        assert len(raw_signature) == 64, f"signature must be 64 bytes, not: {len(raw_signature)}"
        self.raw_signature = raw_signature
        assert len(certificate_id) == 20, f"certificate_id must be 20 bytes, not: {len(certificate_id)}"
        self.certificate_id = certificate_id

    @classmethod
    def flagged_parse(cls, binary: bytes):
        if binary[0] == NAMED_SECP256K1:
            return binary[85:], cls(binary[1:65], binary[65:85], NAMED_SECP256K1)
        else:
            return binary, None

    @property
    def serialized(self):
        return (bytes([self.flag]) + self.raw_signature + self.certificate_id) if self.flag != LEGACY else b''
