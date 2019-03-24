import os.path
from typing import List, Tuple
from decimal import Decimal
from binascii import hexlify, unhexlify

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError
from hachoir.parser import createParser as binary_file_parser
from hachoir.metadata import extractMetadata as binary_file_metadata
from hachoir.core.log import log as hachoir_log

from torba.client.hash import Base58
from torba.client.constants import COIN

from lbrynet.schema.types.v2.claim_pb2 import Claim as ClaimMessage, Fee as FeeMessage
from lbrynet.schema import compat
from lbrynet.schema.base import Signable
from lbrynet.schema.mime_types import guess_media_type


hachoir_log.use_print = False


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

    def to_dict(self):
        return MessageToDict(self.message, preserving_proto_field_name=True)

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


class BaseClaimSubType:

    __slots__ = 'claim', 'message'

    def __init__(self, claim: Claim):
        self.claim = claim or Claim()

    @property
    def title(self) -> str:
        return self.message.title

    @title.setter
    def title(self, title: str):
        self.message.title = title

    @property
    def description(self) -> str:
        return self.message.description

    @description.setter
    def description(self, description: str):
        self.message.description = description

    @property
    def language(self) -> str:
        return self.message.language

    @language.setter
    def language(self, language: str):
        self.message.language = language

    @property
    def thumbnail_url(self) -> str:
        return self.message.thumbnail_url

    @thumbnail_url.setter
    def thumbnail_url(self, thumbnail_url: str):
        self.message.thumbnail_url = thumbnail_url

    @property
    def tags(self) -> List:
        return self.message.tags

    def to_dict(self):
        return MessageToDict(self.message, preserving_proto_field_name=True)

    def update(self, tags=None, clear_tags=False, **kwargs):

        if clear_tags:
            self.message.ClearField('tags')

        if tags is not None:
            if isinstance(tags, str):
                self.tags.append(tags)
            elif isinstance(tags, list):
                self.tags.extend(tags)
            else:
                raise ValueError(f"Unknown tag type: {tags}")

        for key, value in kwargs.items():
            setattr(self, key, value)


class Channel(BaseClaimSubType):

    __slots__ = ()

    def __init__(self, claim: Claim = None):
        super().__init__(claim)
        self.message = self.claim.channel_message

    @property
    def public_key(self) -> str:
        return hexlify(self.message.public_key).decode()

    @public_key.setter
    def public_key(self, sd_public_key: str):
        self.message.public_key = unhexlify(sd_public_key.encode())

    @property
    def public_key_bytes(self) -> bytes:
        return self.message.public_key

    @public_key_bytes.setter
    def public_key_bytes(self, public_key: bytes):
        self.message.public_key = public_key

    @property
    def contact_email(self) -> str:
        return self.message.contact_email

    @contact_email.setter
    def contact_email(self, contact_email: str):
        self.message.contact_email = contact_email

    @property
    def homepage_url(self) -> str:
        return self.message.homepage_url

    @homepage_url.setter
    def homepage_url(self, homepage_url: str):
        self.message.homepage_url = homepage_url

    @property
    def cover_url(self) -> str:
        return self.message.cover_url

    @cover_url.setter
    def cover_url(self, cover_url: str):
        self.message.cover_url = cover_url


class Stream(BaseClaimSubType):

    __slots__ = ()

    def __init__(self, claim: Claim = None):
        super().__init__(claim)
        self.message = self.claim.stream_message

    def update(
            self, file_path=None, duration=None,
            fee_currency=None, fee_amount=None, fee_address=None,
            video_height=None, video_width=None,
            **kwargs):

        super().update(**kwargs)

        if video_height is not None:
            self.video.height = video_height

        if video_width is not None:
            self.video.width = video_width

        if file_path is not None:
            self.media_type = guess_media_type(file_path)
            if not os.path.isfile(file_path):
                raise Exception(f"File does not exist: {file_path}")
            self.file.size = os.path.getsize(file_path)
            if self.file.size == 0:
                raise Exception(f"Cannot publish empty file: {file_path}")

        if fee_amount and fee_currency:
            if fee_address:
                self.fee.address = fee_address
            if fee_currency.lower() == 'lbc':
                self.fee.lbc = Decimal(fee_amount)
            elif fee_currency.lower() == 'usd':
                self.fee.usd = Decimal(fee_amount)
            else:
                raise Exception(f'Unknown currency type: {fee_currency}')

        if duration is not None:
            self.duration = duration
        elif file_path is not None:
            try:
                file_metadata = binary_file_metadata(binary_file_parser(file_path))
                self.duration = file_metadata.getValues('duration')[0].seconds
            except:
                pass

    @property
    def video(self) -> Video:
        return Video(self.message.video)

    @property
    def file(self) -> File:
        return File(self.message.file)

    @property
    def fee(self) -> Fee:
        return Fee(self.message.fee)

    @property
    def has_fee(self) -> bool:
        return self.message.HasField('fee')

    @property
    def hash(self) -> str:
        return hexlify(self.message.hash).decode()

    @hash.setter
    def hash(self, sd_hash: str):
        self.message.hash = unhexlify(sd_hash.encode())

    @property
    def hash_bytes(self) -> bytes:
        return self.message.hash

    @hash_bytes.setter
    def hash_bytes(self, hash: bytes):
        self.message.hash = hash

    @property
    def author(self) -> str:
        return self.message.author

    @author.setter
    def author(self, author: str):
        self.message.author = author

    @property
    def media_type(self) -> str:
        return self.message.media_type

    @media_type.setter
    def media_type(self, media_type: str):
        self.message.media_type = media_type

    @property
    def license(self) -> str:
        return self.message.license

    @license.setter
    def license(self, license: str):
        self.message.license = license

    @property
    def license_url(self) -> str:
        return self.message.license_url

    @license_url.setter
    def license_url(self, license_url: str):
        self.message.license_url = license_url

    @property
    def duration(self) -> int:
        return self.message.duration

    @duration.setter
    def duration(self, duration: int):
        self.message.duration = duration

    @property
    def release_time(self) -> int:
        return self.message.release_time

    @release_time.setter
    def release_time(self, release_time: int):
        self.message.release_time = release_time
