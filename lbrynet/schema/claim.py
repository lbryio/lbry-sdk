import os.path
import json
from string import ascii_letters
from typing import List, Tuple, Iterator, TypeVar, Generic
from decimal import Decimal, ROUND_UP
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


I = TypeVar('I')


class BaseMessageList(Generic[I]):

    __slots__ = 'message',

    item_class = None

    def __init__(self, message):
        self.message = message

    def add(self) -> I:
        return self.item_class(self.message.add())

    def extend(self, values: List[str]):
        for value in values:
            self.append(value)

    def append(self, value: str):
        raise NotImplemented

    def __len__(self):
        return len(self.message)

    def __iter__(self) -> Iterator[I]:
        for lang in self.message:
            yield self.item_class(lang)

    def __getitem__(self, item) -> I:
        return self.item_class(self.message[item])


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


class Source:

    __slots__ = 'message',

    def __init__(self, file_message):
        self.message = file_message

    @property
    def name(self) -> str:
        return self.message.name

    @name.setter
    def name(self, name: str):
        self.message.name = name

    @property
    def size(self) -> int:
        return self.message.size

    @size.setter
    def size(self, size: int):
        self.message.size = size

    @property
    def media_type(self) -> str:
        return self.message.media_type

    @media_type.setter
    def media_type(self, media_type: str):
        self.message.media_type = media_type

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
    def url(self) -> str:
        return self.message.url

    @url.setter
    def url(self, url: str):
        self.message.url = url


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
        if self.currency == 'BTC':
            return self.btc
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

    SATOSHIES = Decimal(COIN)

    @property
    def btc(self) -> Decimal:
        if self._fee.currency != FeeMessage.BTC:
            raise ValueError('BTC can only be returned for BTC fees.')
        return Decimal(self._fee.amount / self.SATOSHIES)

    @btc.setter
    def btc(self, amount: Decimal):
        self.satoshis = int(amount * self.SATOSHIES)

    @property
    def satoshis(self) -> int:
        if self._fee.currency != FeeMessage.BTC:
            raise ValueError('Satoshies can only be returned for BTC fees.')
        return self._fee.amount

    @satoshis.setter
    def satoshis(self, amount: int):
        self._fee.amount = amount
        self._fee.currency = FeeMessage.BTC

    PENNIES = Decimal('100.0')
    PENNY = Decimal('0.01')

    @property
    def usd(self) -> Decimal:
        if self._fee.currency != FeeMessage.USD:
            raise ValueError('USD can only be returned for USD fees.')
        return Decimal(self._fee.amount / self.PENNIES)

    @usd.setter
    def usd(self, amount: Decimal):
        self.pennies = int(amount.quantize(self.PENNY, ROUND_UP) * self.PENNIES)

    @property
    def pennies(self) -> int:
        if self._fee.currency != FeeMessage.USD:
            raise ValueError('Pennies can only be returned for USD fees.')
        return self._fee.amount

    @pennies.setter
    def pennies(self, amount: int):
        self._fee.amount = amount
        self._fee.currency = FeeMessage.USD


class Language:

    __slots__ = 'message',

    def __init__(self, message):
        self.message = message

    @property
    def langtag(self) -> str:
        langtag = []
        if self.language:
            langtag.append(self.language)
        if self.script:
            langtag.append(self.script)
        if self.region:
            langtag.append(self.region)
        return '-'.join(langtag)

    @langtag.setter
    def langtag(self, langtag: str):
        parts = langtag.split('-')
        self.language = parts.pop(0)
        if parts and len(parts[0]) == 4:
            self.script = parts.pop(0)
        if parts and len(parts[0]) == 2:
            self.region = parts.pop(0)
        assert not parts, f"Failed to parse language tag: {langtag}"

    @property
    def language(self) -> str:
        if self.message.language:
            return LanguageMessage.Language.Name(self.message.language)

    @language.setter
    def language(self, language: str):
        self.message.language = LanguageMessage.Language.Value(language)

    @property
    def script(self) -> str:
        if self.message.script:
            return LanguageMessage.Script.Name(self.message.script)

    @script.setter
    def script(self, script: str):
        self.message.script = LanguageMessage.Script.Value(script)

    @property
    def region(self) -> str:
        if self.message.region:
            return LocationMessage.Country.Name(self.message.region)

    @region.setter
    def region(self, region: str):
        self.message.region = LocationMessage.Country.Value(region)


class LanguageList(BaseMessageList[Language]):
    __slots__ = ()
    item_class = Language

    def append(self, value: str):
        self.add().langtag = value


class Location:

    __slots__ = 'message',

    def __init__(self, message):
        self.message = message

    def from_value(self, value):
        if isinstance(value, str) and value.startswith('{'):
            value = json.loads(value)

        if isinstance(value, dict):
            for key, val in value.items():
                setattr(self, key, val)

        elif isinstance(value, str):
            parts = value.split(':')
            if len(parts) > 2 or (parts[0] and parts[0][0] in ascii_letters):
                country = parts and parts.pop(0)
                if country:
                    self.country = country
                state = parts and parts.pop(0)
                if state:
                    self.state = state
                city = parts and parts.pop(0)
                if city:
                    self.city = city
                code = parts and parts.pop(0)
                if code:
                    self.code = code
            latitude = parts and parts.pop(0)
            if latitude:
                self.latitude = latitude
            longitude = parts and parts.pop(0)
            if longitude:
                self.longitude = longitude

        else:
            raise ValueError(f'Could not parse country value: {value}')

    @property
    def country(self) -> str:
        if self.message.country:
            return LocationMessage.Country.Name(self.message.country)

    @country.setter
    def country(self, country: str):
        self.message.country = LocationMessage.Country.Value(country)

    @property
    def state(self) -> str:
        return self.message.state

    @state.setter
    def state(self, state: str):
        self.message.state = state

    @property
    def city(self) -> str:
        return self.message.city

    @city.setter
    def city(self, city: str):
        self.message.city = city

    @property
    def code(self) -> str:
        return self.message.code

    @code.setter
    def code(self, code: str):
        self.message.code = code

    GPS_PRECISION = Decimal('10000000')

    @property
    def latitude(self) -> str:
        if self.message.latitude:
            return str(Decimal(self.message.latitude) / self.GPS_PRECISION)

    @latitude.setter
    def latitude(self, latitude: str):
        latitude = Decimal(latitude)
        assert -90 <= latitude <= 90, "Latitude must be between -90 and 90 degrees."
        self.message.latitude = int(latitude * self.GPS_PRECISION)

    @property
    def longitude(self) -> str:
        if self.message.longitude:
            return str(Decimal(self.message.longitude) / self.GPS_PRECISION)

    @longitude.setter
    def longitude(self, longitude: str):
        longitude = Decimal(longitude)
        assert -180 <= longitude <= 180, "Longitude must be between -180 and 180 degrees."
        self.message.longitude = int(longitude * self.GPS_PRECISION)


class LocationList(BaseMessageList[Location]):
    __slots__ = ()
    item_class = Location

    def append(self, value):
        self.add().from_value(value)


class BaseClaimSubType:

    __slots__ = 'claim', 'message'

    def __init__(self, claim: Claim):
        self.claim = claim or Claim()

    @property
    def title(self) -> str:
        return self.claim.message.title

    @title.setter
    def title(self, title: str):
        self.claim.message.title = title

    @property
    def description(self) -> str:
        return self.claim.message.description

    @description.setter
    def description(self, description: str):
        self.claim.message.description = description

    @property
    def thumbnail(self) -> Source:
        return Source(self.claim.message.thumbnail)

    @property
    def tags(self) -> List:
        return self.claim.message.tags

    @property
    def languages(self) -> LanguageList:
        return LanguageList(self.claim.message.languages)

    @property
    def langtags(self) -> List[str]:
        return [l.langtag for l in self.languages]

    @property
    def locations(self) -> LocationList:
        return LocationList(self.claim.message.locations)

    def to_dict(self):
        return MessageToDict(self.message, preserving_proto_field_name=True)

    def update(self, **kwargs):
        for l in ('tags', 'languages', 'locations'):
            if kwargs.pop(f'clear_{l}', False):
                self.message.ClearField('tags')
            items = kwargs.pop(l, None)
            if items is not None:
                if isinstance(items, str):
                    getattr(self, l).append(items)
                elif isinstance(items, list):
                    getattr(self, l).extend(items)
                else:
                    raise ValueError(f"Unknown {l} value: {items}")

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
    def cover(self) -> Source:
        return Source(self.message.cover)


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
            elif fee_currency.lower() == 'btc':
                self.fee.btc = Decimal(fee_amount)
            elif fee_currency.lower() == 'usd':
                self.fee.usd = Decimal(fee_amount)
            else:
                raise Exception(f'Unknown currency type: {fee_currency}')

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
    def fee(self) -> Fee:
        return Fee(self.message.fee)

    @property
    def has_fee(self) -> bool:
        return self.message.HasField('fee')

    @property
    def source(self) -> Source:
        return Source(self.message.source)

    @property
    def image(self) -> Image:
        return Image(self.message.image)

    @property
    def video(self) -> Video:
        return Video(self.message.video)

    @property
    def audio(self) -> Audio:
        return Audio(self.message.audio)
