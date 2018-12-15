from string import hexdigits
import ecdsa
import hashlib
import binascii

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.serialization import load_der_public_key
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from cryptography.exceptions import InvalidSignature
from ecdsa.util import sigencode_der

from lbrynet.schema.address import decode_address
from lbrynet.schema.schema import NIST256p, NIST384p, SECP256k1, ECDSA_CURVES, CURVE_NAMES


def validate_claim_id(claim_id):
    if not len(claim_id) == 40:
        raise Exception("Incorrect claimid length: %i" % len(claim_id))
    if isinstance(claim_id, bytes):
        claim_id = claim_id.decode('utf-8')
    if set(claim_id).difference(hexdigits):
        raise Exception("Claim id is not hex encoded")


class Validator:
    CURVE_NAME = None
    HASHFUNC = hashlib.sha256

    def __init__(self, public_key, certificate_claim_id):
        validate_claim_id(certificate_claim_id)
        if CURVE_NAMES.get(get_key_type_from_dem(public_key)) != self.CURVE_NAME:
            raise Exception("Curve mismatch")
        self._public_key = public_key
        self._certificate_claim_id = certificate_claim_id

    @property
    def public_key(self):
        return self._public_key

    @property
    def certificate_claim_id(self):
        return self._certificate_claim_id

    @classmethod
    def signing_key_from_pem(cls, pem):
        return ecdsa.SigningKey.from_pem(pem, hashfunc=cls.HASHFUNC)

    @classmethod
    def signing_key_from_der(cls, der):
        return ecdsa.SigningKey.from_der(der, hashfunc=cls.HASHFUNC)

    @classmethod
    def load_from_certificate(cls, certificate_claim, certificate_claim_id):
        certificate = certificate_claim.certificate
        return cls(certificate.publicKey, certificate_claim_id)

    def validate_signature(self, digest, signature):
        public_key = load_der_public_key(self.public_key, default_backend())
        if len(signature) == 64:
            hash = hashes.SHA256()
        elif len(signature) == 96:
            hash = hashes.SHA384()
        signature = binascii.hexlify(signature)
        r = int(signature[:int(len(signature)/2)], 16)
        s = int(signature[int(len(signature)/2):], 16)
        encoded_sig = sigencode_der(r, s, len(signature)*4)
        try:
            public_key.verify(encoded_sig, digest, ec.ECDSA(Prehashed(hash)))
            return True
        except InvalidSignature:
            # TODO Fixme. This is what is expected today on the outer calls. This should be implementation independent
            # but requires changing everything calling that
            from ecdsa import BadSignatureError
            raise BadSignatureError

    def validate_detached_claim_signature(self, claim, claim_address, name):
        decoded_address = decode_address(claim_address)

        # extract and serialize the stream from the claim, then check the signature
        signature = claim.detached_signature.raw_signature

        if signature is None:
            raise Exception("No signature to validate")

        name = name.lower().encode()

        to_sign = bytearray()
        to_sign.extend(name)
        to_sign.extend(decoded_address)
        to_sign.extend(claim.serialized_no_signature)
        to_sign.extend(binascii.unhexlify(self.certificate_claim_id))

        return self.validate_signature(self.HASHFUNC(to_sign).digest(), signature)

    def validate_claim_signature(self, claim, claim_address):
        decoded_address = decode_address(claim_address)

        # extract and serialize the stream from the claim, then check the signature
        signature = binascii.unhexlify(claim.signature)

        if signature is None:
            raise Exception("No signature to validate")

        to_sign = bytearray()
        to_sign.extend(decoded_address)
        to_sign.extend(claim.serialized_no_signature)
        to_sign.extend(binascii.unhexlify(self.certificate_claim_id))

        return self.validate_signature(self.HASHFUNC(to_sign).digest(), signature)

    def validate_private_key(self, private_key):
        if not isinstance(private_key, ecdsa.SigningKey):
            raise TypeError("Not given a signing key, given a %s" % str(type(private_key)))
        return private_key.get_verifying_key().to_der() == self.public_key


class NIST256pValidator(Validator):
    CURVE_NAME = NIST256p
    HASHFUNC = hashlib.sha256


class NIST384pValidator(Validator):
    CURVE_NAME = NIST384p
    HASHFUNC = hashlib.sha384


class SECP256k1Validator(Validator):
    CURVE_NAME = SECP256k1
    HASHFUNC = hashlib.sha256


def get_validator(curve):
    if curve == NIST256p:
        return NIST256pValidator
    elif curve == NIST384p:
        return NIST384pValidator
    elif curve == SECP256k1:
        return SECP256k1Validator
    else:
        raise Exception("Unknown curve: %s" % str(curve))


def get_key_type_from_dem(pubkey_dem):
    name = serialization.load_der_public_key(pubkey_dem, default_backend()).curve.name
    if name == 'secp256k1':
        return ECDSA_CURVES[SECP256k1]
    elif name == 'secp256r1':
        return ECDSA_CURVES[NIST256p]
    elif name == 'secp384r1':
        return ECDSA_CURVES[NIST384p]
    raise Exception("unexpected curve: %s" % name)
