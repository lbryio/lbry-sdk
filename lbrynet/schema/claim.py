import json
import binascii
from copy import deepcopy
from collections import OrderedDict

import google.protobuf.json_format as json_pb  # pylint: disable=no-name-in-module
from google.protobuf import json_format  # pylint: disable=no-name-in-module
from google.protobuf.message import DecodeError as DecodeError_pb  # pylint: disable=no-name-in-module,import-error
from google.protobuf.message import Message  # pylint: disable=no-name-in-module,import-error

from lbrynet.schema.types.v2 import claim_pb2 as claim_pb
from torba.client.constants import COIN

from lbrynet.schema.types.v1 import legacy_claim_pb2
from lbrynet.schema.signature import Signature
from lbrynet.schema.validator import get_validator
from lbrynet.schema.signer import get_signer
from lbrynet.schema.legacy_schema_v1.claim import Claim as LegacyClaim
from lbrynet.schema.legacy_schema_v1 import CLAIM_TYPE_NAMES
from lbrynet.schema.constants import CURVE_NAMES, SECP256k1
from lbrynet.schema.encoding import decode_fields, decode_b64_fields, encode_fields
from lbrynet.schema.error import DecodeError
from lbrynet.schema.fee import Fee


class ClaimDict(OrderedDict):
    def __init__(self, claim_dict=None, detached_signature: Signature=None):
        if isinstance(claim_dict, legacy_claim_pb2.Claim):
            raise Exception("To initialize %s with a Claim protobuf use %s.load_protobuf" %
                            (self.__class__.__name__, self.__class__.__name__))
        self.detached_signature = detached_signature
        OrderedDict.__init__(self, claim_dict or [])

    @property
    def protobuf_dict(self):
        """Claim dictionary using base64 to represent bytes"""

        return json.loads(json_format.MessageToJson(self.protobuf, True))

    @property
    def protobuf(self):
        """Claim message object"""

        return LegacyClaim.load(self)

    @property
    def serialized(self):
        """Serialized Claim protobuf"""
        if self.detached_signature:
            return self.detached_signature.serialized
        return self.protobuf.SerializeToString()

    @property
    def serialized_no_signature(self):
        """Serialized Claim protobuf without publisherSignature field"""
        claim = self.protobuf
        claim.ClearField("publisherSignature")
        return ClaimDict.load_protobuf(claim).serialized

    @property
    def has_signature(self):
        return self.protobuf.HasField("publisherSignature") or (
                self.detached_signature and self.detached_signature.raw_signature
        )

    @property
    def is_certificate(self):
        claim = self.protobuf
        return CLAIM_TYPE_NAMES[claim.claimType] == "certificate"

    @property
    def is_stream(self):
        claim = self.protobuf
        return CLAIM_TYPE_NAMES[claim.claimType] == "stream"

    @property
    def source_hash(self):
        claim = self.protobuf
        if not CLAIM_TYPE_NAMES[claim.claimType] == "stream":
            return None
        return binascii.hexlify(claim.stream.source.source)

    @property
    def has_fee(self):
        claim = self.protobuf
        if not CLAIM_TYPE_NAMES[claim.claimType] == "stream":
            return None
        if claim.stream.metadata.HasField("fee"):
            return True
        return False

    @property
    def source_fee(self):
        claim = self.protobuf
        if not CLAIM_TYPE_NAMES[claim.claimType] == "stream":
            return None
        if claim.stream.metadata.HasField("fee"):
            return Fee.load_protobuf(claim.stream.metadata.fee)
        return None

    @property
    def certificate_id(self) -> str:
        if self.protobuf.HasField("publisherSignature"):
            return binascii.hexlify(self.protobuf.publisherSignature.certificateId).decode()
        if self.detached_signature and self.detached_signature.certificate_id:
            return binascii.hexlify(self.detached_signature.certificate_id).decode()

    @property
    def signature(self):
        if not self.has_signature:
            return None
        return binascii.hexlify(self.protobuf.publisherSignature.signature)

    @property
    def protobuf_len(self):
        """Length of serialized string"""

        return self.protobuf.ByteSize()

    @property
    def json_len(self):
        """Length of json encoded string"""

        return len(json.dumps(self.claim_dict))

    @property
    def claim_dict(self):
        """Claim dictionary with bytes represented as hex and base58"""

        return dict(encode_fields(self, self.detached_signature))

    @classmethod
    def load_protobuf_dict(cls, protobuf_dict, detached_signature=None):
        """
        Load a ClaimDict from a dictionary with base64 encoded bytes
        (as returned by the protobuf json formatter)
        """

        return cls(decode_b64_fields(protobuf_dict), detached_signature=detached_signature)

    @classmethod
    def load_protobuf(cls, protobuf_claim, detached_signature=None):
        """Load ClaimDict from a protobuf Claim message"""
        return cls.load_protobuf_dict(json.loads(json_format.MessageToJson(protobuf_claim, True)), detached_signature)

    @classmethod
    def load_dict(cls, claim_dict):
        """Load ClaimDict from a dictionary with hex and base58 encoded bytes"""
        try:
            claim_dict, detached_signature = decode_fields(claim_dict)
            return cls.load_protobuf(cls(claim_dict).protobuf, detached_signature)
        except json_format.ParseError as err:
            raise DecodeError(str(err))

    @classmethod
    def deserialize(cls, serialized):
        """Load a ClaimDict from a serialized protobuf string"""
        detached_signature = Signature.flagged_parse(serialized)

        temp_claim = legacy_claim_pb2.Claim()
        try:
            temp_claim.ParseFromString(detached_signature.payload)
        except DecodeError_pb:
            raise DecodeError(DecodeError_pb)
        return cls.load_protobuf(temp_claim, detached_signature=detached_signature)

    @classmethod
    def generate_certificate(cls, private_key, curve=SECP256k1):
        signer = get_signer(curve).load_pem(private_key)
        return cls.load_protobuf(signer.certificate)

    def sign(self, private_key, claim_address, cert_claim_id, curve=SECP256k1, name=None, force_detached=False):
        signer = get_signer(curve).load_pem(private_key)
        signed, signature = signer.sign_stream_claim(self, claim_address, cert_claim_id, name, force_detached)
        return ClaimDict.load_protobuf(signed, signature)

    def validate_signature(self, claim_address, certificate, name=None):
        if isinstance(certificate, ClaimDict):
            certificate = certificate.protobuf
        curve = CURVE_NAMES[certificate.certificate.keyType]
        validator = get_validator(curve).load_from_certificate(certificate, self.certificate_id)
        return validator.validate_claim_signature(self, claim_address, name)

    def validate_private_key(self, private_key, certificate_id):
        certificate = self.protobuf
        if CLAIM_TYPE_NAMES[certificate.claimType] != "certificate":
            return
        curve = CURVE_NAMES[certificate.certificate.keyType]
        validator = get_validator(curve).load_from_certificate(certificate, certificate_id)
        signing_key = validator.signing_key_from_pem(private_key)
        return validator.validate_private_key(signing_key)

    def get_validator(self, certificate_id):
        """
        Get a lbrynet.schema.validator.Validator object for a certificate claim

        :param certificate_id: claim id of this certificate claim
        :return: None or lbrynet.schema.validator.Validator object
        """

        claim = self.protobuf
        if CLAIM_TYPE_NAMES[claim.claimType] != "certificate":
            return
        curve = CURVE_NAMES[claim.certificate.keyType]
        return get_validator(curve).load_from_certificate(claim, certificate_id)


class Schema(Message):
    @classmethod
    def load(cls, message):
        raise NotImplementedError

    @classmethod
    def _load(cls, data, message):
        if isinstance(data, dict):
            data = json.dumps(data)
        return json_pb.Parse(data, message)


class Claim(Schema):
    CLAIM_TYPE_STREAM = 0  #fixme: 0 is unset, should be fixed on proto file to be 1 and 2!
    CLAIM_TYPE_CERT = 1

    @classmethod
    def load(cls, message: dict):
        _claim = deepcopy(message)
        _message_pb = claim_pb.Claim()

        if "certificate" in _claim:  # old protobuf, migrate
            _cert = _claim.pop("certificate")
            assert isinstance(_cert, dict)
            _message_pb.type = Claim.CLAIM_TYPE_CERT
            _message_pb.channel.MergeFrom(claim_pb.Channel(public_key=_cert.pop("publicKey")))
            _claim = {}  # so we dont need to know what other fields we ignored
        elif "channel" in _claim:
            _channel = _claim.pop("channel")
            _message_pb.type = Claim.CLAIM_TYPE_CERT
            _message_pb.channel = claim_pb.Channel(**_channel)
        elif "stream" in _claim:
            _message_pb.type = Claim.CLAIM_TYPE_STREAM
            _stream = _claim.pop("stream")
            if "source" in _stream:
                _source = _stream.pop("source")
                _message_pb.stream.hash = _source.get("source", b'')  # fixme: fail if empty?
                _message_pb.stream.media_type = _source.pop("contentType")
            if "metadata" in _stream:
                _metadata = _stream.pop("metadata")
                _message_pb.stream.license = _metadata.get("license")
                _message_pb.stream.description = _metadata.get("description")
                _message_pb.stream.language = _metadata.get("language")
                _message_pb.stream.title = _metadata.get("title")
                _message_pb.stream.author = _metadata.get("author")
                _message_pb.stream.license_url = _metadata.get("licenseUrl")
                _message_pb.stream.thumbnail_url = _metadata.get("thumbnail")
                if _metadata.get("nsfw"):
                    _message_pb.stream.tags.append("nsfw")
                if "fee" in _metadata:
                    _message_pb.stream.fee.address = _metadata["fee"]["address"]
                    _message_pb.stream.fee.currency = {
                        "LBC": 0,
                        "USD": 1
                    }[_metadata["fee"]["currency"]]
                    multiplier = COIN if _metadata["fee"]["currency"] == "LBC" else 100
                    total = int(_metadata["fee"]["amount"]*multiplier)
                    _message_pb.stream.fee.amount = total if total >= 0 else 0
            _claim = {}
        else:
            raise AttributeError

        return cls._load(_claim, _message_pb)
