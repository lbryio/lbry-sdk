from typing import List, Tuple
from decimal import Decimal
from binascii import hexlify, unhexlify

from google.protobuf.message import DecodeError

from torba.client.hash import Base58
from torba.client.constants import COIN

from lbrynet.schema.types.v2.claim_pb2 import Claim as ClaimMessage, Fee as FeeMessage
from lbrynet.schema import compat
from lbrynet.schema.base import Signable


class Claim(Signable):

    __slots__ = 'version',
    message_class = ClaimMessage

    def __init__(self, claim_message=None):
        super().__init__(claim_message)
        self.version = 2

    @property
    def is_stream(self):
        return self.message.WhichOneof('type') == 'stream'

    @property
    def is_channel(self):
        return self.message.WhichOneof('type') == 'channel'

    @property
    def stream_message(self):
        if self.is_undetermined:
            self.message.stream.SetInParent()
        if not self.is_stream:
            raise ValueError('Claim is not a stream.')
        return self.message.stream

    @property
    def stream(self) -> 'Stream':
        return Stream(self)

    @property
    def channel_message(self):
        if self.is_undetermined:
            self.message.channel.SetInParent()
        if not self.is_channel:
            raise ValueError('Claim is not a channel.')
        return self.message.channel

    @property
    def channel(self) -> 'Channel':
        return Channel(self)

    @classmethod
    def from_bytes(cls, data: bytes) -> 'Claim':
        try:
            return super().from_bytes(data)
        except DecodeError:
            claim = cls()
            if data[0] == ord('{'):
                claim.version = 0
                compat.from_old_json_schema(claim, data)
            elif data[0] not in (0, 1):
                claim.version = 1
                compat.from_types_v1(claim, data)
            else:
                raise
            return claim


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

    @property
    def address(self) -> str:
        return Base58.encode(self._fee.address)

    @address.setter
    def address(self, address: str):
        self._fee.address = Base58.decode(address)

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

    DEWIES = Decimal(COIN)

    @property
    def lbc(self) -> Decimal:
        if self._fee.currency != FeeMessage.LBC:
            raise ValueError('LBC can only be returned for LBC fees.')
        return Decimal(self._fee.amount / self.DEWIES)

    @lbc.setter
    def lbc(self, amount: Decimal):
        self.dewies = int(amount * self.DEWIES)

    @property
    def dewies(self) -> int:
        if self._fee.currency != FeeMessage.LBC:
            raise ValueError('Dewies can only be returned for LBC fees.')
        return self._fee.amount

    @dewies.setter
    def dewies(self, amount: int):
        self._fee.amount = amount
        self._fee.currency = FeeMessage.LBC

    PENNIES = Decimal(100.0)

    @property
    def usd(self) -> Decimal:
        if self._fee.currency != FeeMessage.USD:
            raise ValueError('USD can only be returned for USD fees.')
        return Decimal(self._fee.amount / self.PENNIES)

    @usd.setter
    def usd(self, amount: Decimal):
        self.pennies = int(amount * self.PENNIES)

    @property
    def pennies(self) -> int:
        if self._fee.currency != FeeMessage.USD:
            raise ValueError('Pennies can only be returned for USD fees.')
        return self._fee.amount

    @pennies.setter
    def pennies(self, amount: int):
        self._fee.amount = amount
        self._fee.currency = FeeMessage.USD


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
    def has_fee(self) -> bool:
        return self._stream.HasField('fee')

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
