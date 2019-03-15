import json
from collections import OrderedDict
from typing import List, Tuple
from decimal import Decimal
from binascii import hexlify, unhexlify

from google.protobuf import json_format  # pylint: disable=no-name-in-module
from google.protobuf.message import DecodeError as DecodeError_pb  # pylint: disable=no-name-in-module,import-error

from torba.client.constants import COIN

from lbrynet.schema.signature import Signature
from lbrynet.schema.validator import get_validator
from lbrynet.schema.signer import get_signer
from lbrynet.schema.constants import CURVE_NAMES, SECP256k1
from lbrynet.schema.encoding import decode_fields, decode_b64_fields, encode_fields
from lbrynet.schema.error import DecodeError
from lbrynet.schema.types.v2.claim_pb2 import Claim as ClaimMessage, Fee as FeeMessage
from lbrynet.schema.base import b58decode, b58encode
from lbrynet.schema import compat


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


class Claim:

    __slots__ = '_claim',

    def __init__(self, claim_message=None):
        self._claim = claim_message or ClaimMessage()

    @property
    def is_undetermined(self):
        return self._claim.WhichOneof('type') is None

    @property
    def is_stream(self):
        return self._claim.WhichOneof('type') == 'stream'

    @property
    def is_channel(self):
        return self._claim.WhichOneof('type') == 'channel'

    @property
    def stream_message(self):
        if self.is_undetermined:
            self._claim.stream.SetInParent()
        if not self.is_stream:
            raise ValueError('Claim is not a stream.')
        return self._claim.stream

    @property
    def stream(self) -> 'Stream':
        return Stream(self)

    @property
    def channel_message(self):
        if self.is_undetermined:
            self._claim.channel.SetInParent()
        if not self.is_channel:
            raise ValueError('Claim is not a channel.')
        return self._claim.channel

    @property
    def channel(self) -> 'Channel':
        return Channel(self)

    def to_bytes(self) -> bytes:
        return self._claim.SerializeToString()

    @classmethod
    def from_bytes(cls, data: bytes) -> 'Claim':
        claim = ClaimMessage()
        if data[0] == 0:
            claim.ParseFromString(data[1:])
            return cls(claim)
        elif data[0] == 1:
            claim.ParseFromString(data[85:])
            return cls(claim).from_message(payload[1:21], payload[21:85])
        elif data[0] == ord('{'):
            return compat.from_old_json_schema(cls(claim), data)
        else:
            return compat.from_types_v1(cls(claim), data)


class Video:

    __slots__ = '_video',

    def __init__(self, video_message):
        self._video = video_message

    @property
    def width(self) -> int:
        return self._video.width

    @width.setter
    def width(self, width: int):
        self._video.width = width

    @property
    def height(self) -> int:
        return self._video.height

    @height.setter
    def height(self, height: int):
        self._video.height = height

    @property
    def dimensions(self) -> Tuple[int, int]:
        return self.width, self.height

    @dimensions.setter
    def dimensions(self, dimensions: Tuple[int, int]):
        self._video.width, self._video.height = dimensions


class File:

    __slots__ = '_file',

    def __init__(self, file_message):
        self._file = file_message

    @property
    def name(self) -> str:
        return self._file.name

    @name.setter
    def name(self, name: str):
        self._file.name = name

    @property
    def size(self) -> int:
        return self._file.size

    @size.setter
    def size(self, size: int):
        self._file.size = size


class Fee:

    __slots__ = '_fee',

    def __init__(self, fee_message):
        self._fee = fee_message

    @property
    def currency(self) -> str:
        return FeeMessage.Currency.Name(self._fee.currency)

    @currency.setter
    def currency(self, currency: str):
        self._fee.currency = FeeMessage.Currency.Value(currency)

    @property
    def address(self) -> str:
        return b58encode(self._fee.address).decode()

    @address.setter
    def address(self, address: str):
        self._fee.address = b58decode(address)

    @property
    def address_bytes(self) -> bytes:
        return self._fee.address

    @address_bytes.setter
    def address_bytes(self, address: bytes):
        self._fee.address = address

    @property
    def amount(self) -> Decimal:
        if self.currency == 'LBC':
            return self.lbc
        if self.currency == 'USD':
            return self.usd

    @property
    def dewies(self) -> int:
        if self._fee.currency != FeeMessage.LBC:
            raise ValueError('Dewies can only be returned for LBC fees.')
        return self._fee.amount

    @dewies.setter
    def dewies(self, amount: int):
        self._fee.amount = amount
        self._fee.currency = FeeMessage.LBC

    DEWEYS = Decimal(COIN)

    @property
    def lbc(self) -> Decimal:
        if self._fee.currency != FeeMessage.LBC:
            raise ValueError('LBC can only be returned for LBC fees.')
        return Decimal(self._fee.amount / self.DEWEYS)

    @lbc.setter
    def lbc(self, amount: Decimal):
        self.dewies = int(amount * self.DEWEYS)

    USD = Decimal(100.0)

    @property
    def usd(self) -> Decimal:
        if self._fee.currency != FeeMessage.USD:
            raise ValueError('USD can only be returned for USD fees.')
        return Decimal(self._fee.amount / self.USD)

    @usd.setter
    def usd(self, amount: Decimal):
        self._fee.amount = int(amount * self.USD)
        self._fee.currency = FeeMessage.USD


class Stream:

    __slots__ = '_claim', '_stream'

    def __init__(self, claim: Claim = None):
        self._claim = claim or Claim()
        self._stream = self._claim.stream_message

    @property
    def claim(self) -> Claim:
        return self._claim

    @property
    def video(self) -> Video:
        return Video(self._stream.video)

    @property
    def file(self) -> File:
        return File(self._stream.file)

    @property
    def fee(self) -> Fee:
        return Fee(self._stream.fee)

    @property
    def tags(self) -> List:
        return self._stream.tags

    @property
    def hash(self) -> str:
        return hexlify(self._stream.hash).decode()

    @hash.setter
    def hash(self, sd_hash: str):
        self._stream.hash = unhexlify(sd_hash.encode())

    @property
    def hash_bytes(self) -> bytes:
        return self._stream.hash

    @hash_bytes.setter
    def hash_bytes(self, hash: bytes):
        self._stream.hash = hash

    @property
    def language(self) -> str:
        return self._stream.language

    @language.setter
    def language(self, language: str):
        self._stream.language = language

    @property
    def title(self) -> str:
        return self._stream.title

    @title.setter
    def title(self, title: str):
        self._stream.title = title

    @property
    def author(self) -> str:
        return self._stream.author

    @author.setter
    def author(self, author: str):
        self._stream.author = author

    @property
    def description(self) -> str:
        return self._stream.description

    @description.setter
    def description(self, description: str):
        self._stream.description = description

    @property
    def media_type(self) -> str:
        return self._stream.media_type

    @media_type.setter
    def media_type(self, media_type: str):
        self._stream.media_type = media_type

    @property
    def license(self) -> str:
        return self._stream.license

    @license.setter
    def license(self, license: str):
        self._stream.license = license

    @property
    def license_url(self) -> str:
        return self._stream.license_url

    @license_url.setter
    def license_url(self, license_url: str):
        self._stream.license_url = license_url

    @property
    def thumbnail_url(self) -> str:
        return self._stream.thumbnail_url

    @thumbnail_url.setter
    def thumbnail_url(self, thumbnail_url: str):
        self._stream.thumbnail_url = thumbnail_url

    @property
    def duration(self) -> int:
        return self._stream.duration

    @duration.setter
    def duration(self, duration: int):
        self._stream.duration = duration

    @property
    def release_time(self) -> int:
        return self._stream.release_time

    @release_time.setter
    def release_time(self, release_time: int):
        self._stream.release_time = release_time


class Channel:

    __slots__ = '_claim', '_channel'

    def __init__(self, claim: Claim = None):
        self._claim = claim or Claim()
        self._channel = self._claim.channel_message

    @property
    def claim(self) -> Claim:
        return self._claim

    @property
    def tags(self) -> List:
        return self._channel.tags

    @property
    def public_key(self) -> str:
        return hexlify(self._channel.public_key).decode()

    @public_key.setter
    def public_key(self, sd_public_key: str):
        self._channel.public_key = unhexlify(sd_public_key.encode())

    @property
    def public_key_bytes(self) -> bytes:
        return self._channel.public_key

    @public_key_bytes.setter
    def public_key_bytes(self, public_key: bytes):
        self._channel.public_key = public_key

    @property
    def language(self) -> str:
        return self._channel.language

    @language.setter
    def language(self, language: str):
        self._channel.language = language

    @property
    def title(self) -> str:
        return self._channel.title

    @title.setter
    def title(self, title: str):
        self._channel.title = title

    @property
    def description(self) -> str:
        return self._channel.description

    @description.setter
    def description(self, description: str):
        self._channel.description = description

    @property
    def contact_email(self) -> str:
        return self._channel.contact_email

    @contact_email.setter
    def contact_email(self, contact_email: str):
        self._channel.contact_email = contact_email

    @property
    def homepage_url(self) -> str:
        return self._channel.homepage_url

    @homepage_url.setter
    def homepage_url(self, homepage_url: str):
        self._channel.homepage_url = homepage_url

    @property
    def thumbnail_url(self) -> str:
        return self._channel.thumbnail_url

    @thumbnail_url.setter
    def thumbnail_url(self, thumbnail_url: str):
        self._channel.thumbnail_url = thumbnail_url

    @property
    def cover_url(self) -> str:
        return self._channel.cover_url

    @cover_url.setter
    def cover_url(self, cover_url: str):
        self._channel.cover_url = cover_url
