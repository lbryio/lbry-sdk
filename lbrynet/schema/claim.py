import json
import binascii
from google.protobuf import json_format  # pylint: disable=no-name-in-module
from google.protobuf.message import DecodeError as DecodeError_pb  # pylint: disable=no-name-in-module,import-error

from collections import OrderedDict

from lbryschema.schema.claim import Claim
from lbryschema.proto import claim_pb2
from lbryschema.validator import get_validator
from lbryschema.signer import get_signer
from lbryschema.schema import NIST256p, CURVE_NAMES, CLAIM_TYPE_NAMES
from lbryschema.encoding import decode_fields, decode_b64_fields, encode_fields
from lbryschema.error import DecodeError
from lbryschema.fee import Fee


class ClaimDict(OrderedDict):
    def __init__(self, claim_dict=None):
        if isinstance(claim_dict, claim_pb2.Claim):
            raise Exception("To initialize %s with a Claim protobuf use %s.load_protobuf" %
                            (self.__class__.__name__, self.__class__.__name__))
        OrderedDict.__init__(self, claim_dict or [])

    @property
    def protobuf_dict(self):
        """Claim dictionary using base64 to represent bytes"""

        return json.loads(json_format.MessageToJson(self.protobuf, True))

    @property
    def protobuf(self):
        """Claim message object"""

        return Claim.load(self)

    @property
    def serialized(self):
        """Serialized Claim protobuf"""

        return self.protobuf.SerializeToString()

    @property
    def serialized_no_signature(self):
        """Serialized Claim protobuf without publisherSignature field"""
        claim = self.protobuf
        claim.ClearField("publisherSignature")
        return ClaimDict.load_protobuf(claim).serialized

    @property
    def has_signature(self):
        claim = self.protobuf
        if claim.HasField("publisherSignature"):
            return True
        return False

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
    def certificate_id(self):
        if not self.has_signature:
            return None
        return binascii.hexlify(self.protobuf.publisherSignature.certificateId)

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

        return dict(encode_fields(self))

    @classmethod
    def load_protobuf_dict(cls, protobuf_dict):
        """
        Load a ClaimDict from a dictionary with base64 encoded bytes
        (as returned by the protobuf json formatter)
        """

        return cls(decode_b64_fields(protobuf_dict))

    @classmethod
    def load_protobuf(cls, protobuf_claim):
        """Load ClaimDict from a protobuf Claim message"""
        return cls.load_protobuf_dict(json.loads(json_format.MessageToJson(protobuf_claim, True)))

    @classmethod
    def load_dict(cls, claim_dict):
        """Load ClaimDict from a dictionary with hex and base58 encoded bytes"""
        try:
            return cls.load_protobuf(cls(decode_fields(claim_dict)).protobuf)
        except json_format.ParseError as err:
            raise DecodeError(str(err))

    @classmethod
    def deserialize(cls, serialized):
        """Load a ClaimDict from a serialized protobuf string"""

        temp_claim = claim_pb2.Claim()
        try:
            temp_claim.ParseFromString(serialized)
        except DecodeError_pb:
            raise DecodeError(DecodeError_pb)
        return cls.load_protobuf(temp_claim)

    @classmethod
    def generate_certificate(cls, private_key, curve=NIST256p):
        signer = get_signer(curve).load_pem(private_key)
        return cls.load_protobuf(signer.certificate)

    def sign(self, private_key, claim_address, cert_claim_id, curve=NIST256p):
        signer = get_signer(curve).load_pem(private_key)
        signed = signer.sign_stream_claim(self, claim_address, cert_claim_id)
        return ClaimDict.load_protobuf(signed)

    def validate_signature(self, claim_address, certificate):
        if isinstance(certificate, ClaimDict):
            certificate = certificate.protobuf
        curve = CURVE_NAMES[certificate.certificate.keyType]
        validator = get_validator(curve).load_from_certificate(certificate, self.certificate_id)
        return validator.validate_claim_signature(self, claim_address)

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
        Get a lbryschema.validator.Validator object for a certificate claim

        :param certificate_id: claim id of this certificate claim
        :return: None or lbryschema.validator.Validator object
        """

        claim = self.protobuf
        if CLAIM_TYPE_NAMES[claim.claimType] != "certificate":
            return
        curve = CURVE_NAMES[claim.certificate.keyType]
        return get_validator(curve).load_from_certificate(claim, certificate_id)
