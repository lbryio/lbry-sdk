from copy import deepcopy

from lbrynet.schema.proto import claim_pb2 as claim_pb
from lbrynet.schema.schema import VERSION_MAP
from lbrynet.schema.schema.signature import Signature
from lbrynet.schema.schema.certificate import Certificate
from lbrynet.schema.schema.schema import Schema
from lbrynet.schema.schema.stream import Stream


class Claim(Schema):
    CLAIM_TYPE_STREAM = 1
    CLAIM_TYPE_CERT = 2

    @classmethod
    def load(cls, message):
        _claim = deepcopy(message)
        _message_pb = claim_pb.Claim()
        _message_pb.version = VERSION_MAP[_claim.pop("version")]

        if "certificate" in _claim:
            _cert = _claim.pop("certificate")
            if isinstance(_cert, dict):
                cert = Certificate.load(_cert)
            else:
                cert = _cert
            claim_type = Claim.CLAIM_TYPE_CERT
            _message_pb.certificate.MergeFrom(cert)

        elif "stream" in _claim:
            _stream = _claim.pop("stream")
            if isinstance(_stream, dict):
                stream = Stream.load(_stream)
            else:
                stream = _stream
            claim_type = Claim.CLAIM_TYPE_STREAM
            _message_pb.stream.MergeFrom(stream)
        else:
            raise AttributeError

        _message_pb.claimType = claim_type

        if "publisherSignature" in _claim:
            _publisherSignature = _claim.pop("publisherSignature")
            if isinstance(_publisherSignature, dict):
                publisherSignature = Signature.load(_publisherSignature)
            else:
                publisherSignature = _publisherSignature
            _message_pb.publisherSignature.MergeFrom(publisherSignature)

        return cls._load(_claim, _message_pb)
