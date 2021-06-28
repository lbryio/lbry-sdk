import json
import logging
import os.path
import hashlib
from typing import Tuple, List
from string import ascii_letters
from decimal import Decimal, ROUND_UP
from binascii import hexlify, unhexlify
from google.protobuf.json_format import MessageToDict

from lbry.crypto.base58 import Base58
from lbry.constants import COIN

from lbry.schema.mime_types import guess_media_type
from lbry.schema.base import Metadata, BaseMessageList
from lbry.schema.tags import clean_tags, normalize_tag
from lbry.schema.types.v2.claim_pb2 import (
    Fee as FeeMessage,
    Location as LocationMessage,
    Language as LanguageMessage
)


log = logging.getLogger(__name__)


def calculate_sha384_file_hash(file_path):
    sha384 = hashlib.sha384()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(128 * sha384.block_size), b''):
            sha384.update(chunk)
    return sha384.digest()


def country_int_to_str(country: int) -> str:
    r = LocationMessage.Country.Name(country)
    return r[1:] if r.startswith('R') else r


def country_str_to_int(country: str) -> int:
    if len(country) == 3:
        country = 'R' + country
    return LocationMessage.Country.Value(country)


class Dimmensional(Metadata):

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

    def _extract(self, file_metadata, field):
        try:
            setattr(self, field, file_metadata.getValues(field)[0])
        except:
            log.exception(f'Could not extract {field} from file metadata.')

    def update(self, file_metadata=None, height=None, width=None):
        if height is not None:
            self.height = height
        elif file_metadata:
            self._extract(file_metadata, 'height')

        if width is not None:
            self.width = width
        elif file_metadata:
            self._extract(file_metadata, 'width')


class Playable(Metadata):

    __slots__ = ()

    @property
    def duration(self) -> int:
        return self.message.duration

    @duration.setter
    def duration(self, duration: int):
        self.message.duration = duration

    def update(self, file_metadata=None, duration=None):
        if duration is not None:
            self.duration = duration
        elif file_metadata:
            try:
                self.duration = file_metadata.getValues('duration')[0].seconds
            except:
                log.exception('Could not extract duration from file metadata.')


class Image(Dimmensional):

    __slots__ = ()


class Audio(Playable):

    __slots__ = ()


class Video(Dimmensional, Playable):

    __slots__ = ()

    def update(self, file_metadata=None, height=None, width=None, duration=None):
        Dimmensional.update(self, file_metadata, height, width)
        Playable.update(self, file_metadata, duration)


class Source(Metadata):

    __slots__ = ()

    def update(self, file_path=None):
        if file_path is not None:
            self.name = os.path.basename(file_path)
            self.media_type, stream_type = guess_media_type(file_path)
            if not os.path.isfile(file_path):
                raise Exception(f"File does not exist: {file_path}")
            self.size = os.path.getsize(file_path)
            if self.size == 0:
                raise Exception(f"Cannot publish empty file: {file_path}")
            self.file_hash_bytes = calculate_sha384_file_hash(file_path)
            return stream_type

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
    def file_hash(self) -> str:
        return hexlify(self.message.hash).decode()

    @file_hash.setter
    def file_hash(self, file_hash: str):
        self.message.hash = unhexlify(file_hash.encode())

    @property
    def file_hash_bytes(self) -> bytes:
        return self.message.hash

    @file_hash_bytes.setter
    def file_hash_bytes(self, file_hash_bytes: bytes):
        self.message.hash = file_hash_bytes

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
    def bt_infohash(self) -> str:
        return hexlify(self.message.bt_infohash).decode()

    @bt_infohash.setter
    def bt_infohash(self, bt_infohash: str):
        self.message.bt_infohash = unhexlify(bt_infohash.encode())

    @property
    def bt_infohash_bytes(self) -> bytes:
        return self.message.bt_infohash.decode()

    @bt_infohash_bytes.setter
    def bt_infohash_bytes(self, bt_infohash: bytes):
        self.message.bt_infohash = bt_infohash

    @property
    def url(self) -> str:
        return self.message.url

    @url.setter
    def url(self, url: str):
        self.message.url = url


class Fee(Metadata):

    __slots__ = ()

    def update(self, address: str = None, currency: str = None, amount=None):
        if amount:
            currency = (currency or self.currency or '').lower()
            if not currency:
                raise Exception('In order to set a fee amount, please specify a fee currency.')
            if currency not in ('lbc', 'btc', 'usd'):
                raise Exception(f'Missing or unknown currency provided: {currency}')
            setattr(self, currency, Decimal(amount))
        elif currency:
            raise Exception('In order to set a fee currency, please specify a fee amount.')
        if address:
            if not self.currency:
                raise Exception('In order to set a fee address, please specify a fee amount and currency.')
            self.address = address

    @property
    def currency(self) -> str:
        if self.message.currency:
            return FeeMessage.Currency.Name(self.message.currency)

    @property
    def address(self) -> str:
        if self.address_bytes:
            return Base58.encode(self.address_bytes)

    @address.setter
    def address(self, address: str):
        self.address_bytes = Base58.decode(address)

    @property
    def address_bytes(self) -> bytes:
        return self.message.address

    @address_bytes.setter
    def address_bytes(self, address: bytes):
        self.message.address = address

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
        if self.message.currency != FeeMessage.LBC:
            raise ValueError('LBC can only be returned for LBC fees.')
        return Decimal(self.message.amount / self.DEWIES)

    @lbc.setter
    def lbc(self, amount: Decimal):
        self.dewies = int(amount * self.DEWIES)

    @property
    def dewies(self) -> int:
        if self.message.currency != FeeMessage.LBC:
            raise ValueError('Dewies can only be returned for LBC fees.')
        return self.message.amount

    @dewies.setter
    def dewies(self, amount: int):
        self.message.amount = amount
        self.message.currency = FeeMessage.LBC

    SATOSHIES = Decimal(COIN)

    @property
    def btc(self) -> Decimal:
        if self.message.currency != FeeMessage.BTC:
            raise ValueError('BTC can only be returned for BTC fees.')
        return Decimal(self.message.amount / self.SATOSHIES)

    @btc.setter
    def btc(self, amount: Decimal):
        self.satoshis = int(amount * self.SATOSHIES)

    @property
    def satoshis(self) -> int:
        if self.message.currency != FeeMessage.BTC:
            raise ValueError('Satoshies can only be returned for BTC fees.')
        return self.message.amount

    @satoshis.setter
    def satoshis(self, amount: int):
        self.message.amount = amount
        self.message.currency = FeeMessage.BTC

    PENNIES = Decimal('100.0')
    PENNY = Decimal('0.01')

    @property
    def usd(self) -> Decimal:
        if self.message.currency != FeeMessage.USD:
            raise ValueError('USD can only be returned for USD fees.')
        return Decimal(self.message.amount / self.PENNIES)

    @usd.setter
    def usd(self, amount: Decimal):
        self.pennies = int(amount.quantize(self.PENNY, ROUND_UP) * self.PENNIES)

    @property
    def pennies(self) -> int:
        if self.message.currency != FeeMessage.USD:
            raise ValueError('Pennies can only be returned for USD fees.')
        return self.message.amount

    @pennies.setter
    def pennies(self, amount: int):
        self.message.amount = amount
        self.message.currency = FeeMessage.USD


class ClaimReference(Metadata):

    __slots__ = ()

    @property
    def claim_id(self) -> str:
        return hexlify(self.claim_hash[::-1]).decode()

    @claim_id.setter
    def claim_id(self, claim_id: str):
        self.claim_hash = unhexlify(claim_id)[::-1]

    @property
    def claim_hash(self) -> bytes:
        return self.message.claim_hash

    @claim_hash.setter
    def claim_hash(self, claim_hash: bytes):
        self.message.claim_hash = claim_hash


class ClaimList(BaseMessageList[ClaimReference]):

    __slots__ = ()
    item_class = ClaimReference

    @property
    def _message(self):
        return self.message.claim_references

    def append(self, value):
        self.add().claim_id = value

    @property
    def ids(self) -> List[str]:
        return [c.claim_id for c in self]


class Language(Metadata):

    __slots__ = ()

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
        if parts and len(parts[0]) == 2 and parts[0].isalpha():
            self.region = parts.pop(0)
        if parts and len(parts[0]) == 3 and parts[0].isdigit():
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
            return country_int_to_str(self.message.region)

    @region.setter
    def region(self, region: str):
        self.message.region = country_str_to_int(region)


class LanguageList(BaseMessageList[Language]):
    __slots__ = ()
    item_class = Language

    def append(self, value: str):
        self.add().langtag = value


class Location(Metadata):

    __slots__ = ()

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

    def to_dict(self):
        d = MessageToDict(self.message)
        if self.message.longitude:
            d['longitude'] = self.longitude
        if self.message.latitude:
            d['latitude'] = self.latitude
        return d

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


class TagList(BaseMessageList[str]):
    __slots__ = ()
    item_class = str

    def append(self, tag: str):
        tag = normalize_tag(tag)
        if tag and tag not in self.message:
            self.message.append(tag)
