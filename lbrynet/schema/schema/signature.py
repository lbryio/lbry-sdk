from copy import deepcopy

from lbryschema.proto import signature_pb2 as signature_pb
from lbryschema.schema import VERSION_MAP, ECDSA_CURVES
from lbryschema.schema.schema import Schema


class Signature(Schema):
    @classmethod
    def load(cls, message):
        _signature = deepcopy(message)
        _message_pb = signature_pb.Signature()
        _message_pb.version = VERSION_MAP[_signature.pop("version")]
        _message_pb.signatureType = ECDSA_CURVES[_signature.pop("signatureType")]
        _message_pb.certificateId = _signature.pop("certificateId")
        _message_pb.signature = _signature.pop("signature")
        return cls._load(_signature, _message_pb)
