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

from lbrynet.schema import compat
from lbrynet.schema.base import Signable
from lbrynet.schema.mime_types import guess_media_type
from lbrynet.schema.types.v2.claim_pb2 import (
    Claim as ClaimMessage,
    Fee as FeeMessage,
    Location as LocationMessage,
    Language as LanguageMessage
)


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


class Dimmensional:

    __slots__ = ()

    @property
    def width(self) -> int:
        return self.message.width

    @width.setter
    def width(self, width: int):
        self.message.width = width

    @property
    def height(self) -> int:
        return self.message.height

    @height.setter
    def height(self, height: int):
        self.message.height = height

    @property
    def dimensions(self) -> Tuple[int, int]:
        return self.width, self.height

    @dimensions.setter
    def dimensions(self, dimensions: Tuple[int, int]):
        self.message.width, self.message.height = dimensions


class Playable:

    __slots__ = ()

    @property
    def duration(self) -> int:
        return self.message.duration

    @duration.setter
    def duration(self, duration: int):
        self.message.duration = duration

    def set_duration_from_path(self, file_path):
        try:
            file_metadata = binary_file_metadata(binary_file_parser(file_path))
            self.duration = file_metadata.getValues('duration')[0].seconds
        except:
            pass


class Image(Dimmensional):

    __slots__ = 'message',

    def __init__(self, image_message):
        self.message = image_message


class Video(Dimmensional, Playable):

    __slots__ = 'message',

    def __init__(self, video_message):
        self.message = video_message


class Audio(Playable):

    __slots__ = 'message',

    def __init__(self, audio_message):
        self.message = audio_message


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
    def tags(self) -> List:
        return self.message.tags

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
    def thumbnail_url(self) -> str:
        return self.message.thumbnail_url

    @thumbnail_url.setter
    def thumbnail_url(self, thumbnail_url: str):
        self.message.thumbnail_url = thumbnail_url

    @property
    def language(self) -> str:
        if len(self.languages) > 0:
            return LanguageMessage.Language.Name(self.languages[0].language)

    @language.setter
    def language(self, language: str):
        value = LanguageMessage.Language.Value(language)
        if len(self.languages) > 0:
            self.languages[0].language = value
        else:
            self.languages.add().language = value

    @property
    def languages(self):
        return self.message.languages

    @property
    def location_country(self) -> str:
        if len(self.locations) > 0:
            return LocationMessage.Country.Name(self.locations[0].country)

    @location_country.setter
    def location_country(self, country: str):
        value = LocationMessage.Country.Value(country)
        if len(self.locations) > 0:
            self.locations[0].location = value
        else:
            self.locations.add().location = value

    @property
    def locations(self):
        return self.message.locations

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
            self, file_path=None, stream_type=None,
            fee_currency=None, fee_amount=None, fee_address=None,
            **kwargs):

        duration_was_not_set = True
        sub_types = ('image', 'video', 'audio')
        for key in list(kwargs.keys()):
            for sub_type in sub_types:
                if key.startswith(f'{sub_type}_'):
                    stream_type = sub_type
                    sub_obj = getattr(self, sub_type)
                    sub_obj_attr = key[len(f'{sub_type}_'):]
                    setattr(sub_obj, sub_obj_attr, kwargs.pop(key))
                    if sub_obj_attr == 'duration':
                        duration_was_not_set = False
                    break

        if stream_type is not None:
            if stream_type not in sub_types:
                raise Exception(
                    f"stream_type of '{stream_type}' is not valid, must be one of: {sub_types}"
                )

            sub_obj = getattr(self, stream_type)
            if duration_was_not_set and file_path and isinstance(sub_obj, Playable):
                sub_obj.set_duration_from_path(file_path)

        super().update(**kwargs)

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

    @property
    def sd_hash(self) -> str:
        return hexlify(self.message.sd_hash).decode()

    @sd_hash.setter
    def sd_hash(self, sd_hash: str):
        self.message.sd_hash = unhexlify(sd_hash.encode())

    @property
    def sd_hash_bytes(self) -> bytes:
        return self.message.sd_hash

    @sd_hash_bytes.setter
    def sd_hash_bytes(self, sd_hash: bytes):
        self.message.sd_hash = sd_hash

    @property
    def author(self) -> str:
        return self.message.author

    @author.setter
    def author(self, author: str):
        self.message.author = author

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
    def release_time(self) -> int:
        return self.message.release_time

    @release_time.setter
    def release_time(self, release_time: int):
        self.message.release_time = release_time

    @property
    def media_type(self) -> str:
        return self.message.media_type

    @media_type.setter
    def media_type(self, media_type: str):
        self.message.media_type = media_type

    @property
    def fee(self) -> Fee:
        return Fee(self.message.fee)

    @property
    def has_fee(self) -> bool:
        return self.message.HasField('fee')

    @property
    def file(self) -> File:
        return File(self.message.file)

    @property
    def image(self) -> Image:
        return Image(self.message.image)

    @property
    def video(self) -> Video:
        return Video(self.message.video)

    @property
    def audio(self) -> Audio:
        return Audio(self.message.audio)
