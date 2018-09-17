import struct
from collections import namedtuple
from .flags import SignatureSerializationFlag


class Signature(namedtuple("Signature", "flags signature certificate_id")):
    def deserialize(cls, payload):
        flag = struct.unpack("<b", payload[0])[0]
        if not SignatureSerializationFlag.is_flag_valid(flag):
            return Signature(SignatureSerializationFlag.ECDSA_LEGACY, )
        certificate