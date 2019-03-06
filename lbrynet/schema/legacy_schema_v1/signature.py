from copy import deepcopy

from lbrynet.schema.proto2 import signature_pb2 as signature_pb
from lbrynet.schema.legacy_schema_v1 import VERSION_MAP
from lbrynet.schema.constants import ECDSA_CURVES
from lbrynet.schema.baseschema import Schema


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
