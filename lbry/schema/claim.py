import logging
from typing import List
from binascii import hexlify, unhexlify

from asn1crypto.keys import PublicKeyInfo
from coincurve import PublicKey as cPublicKey

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError
from hachoir.core.log import log as hachoir_log
from hachoir.parser import createParser as binary_file_parser
from hachoir.metadata import extractMetadata as binary_file_metadata

from lbry.schema import compat
from lbry.schema.base import Signable
from lbry.schema.mime_types import guess_media_type, guess_stream_type
from lbry.schema.attrs import (
    Source, Playable, Dimmensional, Fee, Image, Video, Audio,
    LanguageList, LocationList, ClaimList, ClaimReference, TagList
)
from lbry.schema.types.v2.claim_pb2 import Claim as ClaimMessage
from lbry.error import InputValueIsNoneError


hachoir_log.use_print = False
log = logging.getLogger(__name__)


class Claim(Signable):

    STREAM = 'stream'
    CHANNEL = 'channel'
    COLLECTION = 'collection'
    REPOST = 'repost'

    __slots__ = ()

    message_class = ClaimMessage

    @property
    def claim_type(self) -> str:
        return self.message.WhichOneof('type')

    def get_message(self, type_name):
        message = getattr(self.message, type_name)
        if self.claim_type is None:
            message.SetInParent()
        if self.claim_type != type_name:
            raise ValueError(f'Claim is not a {type_name}.')
        return message

    @property
    def is_stream(self):
        return self.claim_type == self.STREAM

    @property
    def stream(self) -> 'Stream':
        return Stream(self)

    @property
    def is_channel(self):
        return self.claim_type == self.CHANNEL

    @property
    def channel(self) -> 'Channel':
        return Channel(self)

    @property
    def is_repost(self):
        return self.claim_type == self.REPOST

    @property
    def repost(self) -> 'Repost':
        return Repost(self)

    @property
    def is_collection(self):
        return self.claim_type == self.COLLECTION

    @property
    def collection(self) -> 'Collection':
        return Collection(self)

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


class BaseClaim:

    __slots__ = 'claim', 'message'

    claim_type = None
    object_fields = 'thumbnail',
    repeat_fields = 'tags', 'languages', 'locations'

    def __init__(self, claim: Claim = None):
        self.claim = claim or Claim()
        self.message = self.claim.get_message(self.claim_type)

    def to_dict(self):
        claim = MessageToDict(self.claim.message, preserving_proto_field_name=True)
        claim.update(claim.pop(self.claim_type))
        if 'languages' in claim:
            claim['languages'] = self.langtags
        if 'locations' in claim:
            claim['locations'] = [l.to_dict() for l in self.locations]
        return claim

    def none_check(self, kwargs):
        for key, value in kwargs.items():
            if value is None:
                raise InputValueIsNoneError(key)

    def update(self, strict_update=True, **kwargs) -> dict:
        self.none_check(kwargs)

        for key in list(kwargs):
            for field in self.object_fields:
                if key.startswith(f'{field}_'):
                    attr = getattr(self, field)
                    setattr(attr, key[len(f'{field}_'):], kwargs.pop(key))
                    continue

        for l in self.repeat_fields:
            field = getattr(self, l)
            clear = kwargs.pop(f'clear_{l}', False)
            if isinstance(clear, bool) and clear:
                failed = []
                if len(field) > 0:
                    del field[:]
                else:
                    failed = clear
                if failed:
                    kwargs[f'clear_{l}'] = failed
            if isinstance(clear, list):
                failed = []
                for c in clear:
                    if not field.remove(c):
                        failed.append(c)
                if failed:
                    kwargs[f'clear_{l}'] = failed
            items = kwargs.pop(l, None)
            if items is not None:
                if isinstance(items, str):
                    field.append(items)
                elif isinstance(items, list):
                    field.extend(items)
                else:
                    raise ValueError(f"Unknown {l} value: {items}")

        failed = dict()
        for key, value in kwargs.items():
            try:
                setattr(self, key, value)
            except AttributeError:
                failed[key] = value
                if strict_update:
                    raise

        return failed

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
    def tags(self) -> List[str]:
        return TagList(self.claim.message.tags)

    @property
    def languages(self) -> LanguageList:
        return LanguageList(self.claim.message.languages)

    @property
    def langtags(self) -> List[str]:
        return [l.langtag for l in self.languages]

    @property
    def locations(self) -> LocationList:
        return LocationList(self.claim.message.locations)


class Stream(BaseClaim):

    __slots__ = ()

    claim_type = Claim.STREAM

    object_fields = BaseClaim.object_fields + ('source',)

    def to_dict(self):
        claim = super().to_dict()
        if 'source' in claim:
            if 'hash' in claim['source']:
                claim['source']['hash'] = self.source.file_hash
            if 'sd_hash' in claim['source']:
                claim['source']['sd_hash'] = self.source.sd_hash
            elif 'bt_infohash' in claim['source']:
                claim['source']['bt_infohash'] = self.source.bt_infohash
            if 'media_type' in claim['source']:
                claim['stream_type'] = guess_stream_type(claim['source']['media_type'])
        fee = claim.get('fee', {})
        if 'address' in fee:
            fee['address'] = self.fee.address
        if 'amount' in fee:
            fee['amount'] = str(self.fee.amount)
        return claim

    def update(self, file_path=None, height=None, width=None, duration=None, **kwargs) -> dict:

        if kwargs.pop('clear_fee', False):
            self.message.ClearField('fee')
        else:
            self.fee.update(
                kwargs.pop('fee_address', None),
                kwargs.pop('fee_currency', None),
                kwargs.pop('fee_amount', None)
            )

        self.none_check(kwargs)

        if 'sd_hash' in kwargs:
            self.source.sd_hash = kwargs.pop('sd_hash')
        elif 'bt_infohash' in kwargs:
            self.source.bt_infohash = kwargs.pop('bt_infohash')
        if 'file_name' in kwargs:
            self.source.name = kwargs.pop('file_name')
        if 'file_hash' in kwargs:
            self.source.file_hash = kwargs.pop('file_hash')

        stream_type = None
        if file_path is not None:
            stream_type = self.source.update(file_path=file_path)
        elif self.source.name:
            self.source.media_type, stream_type = guess_media_type(self.source.name)
        elif self.source.media_type:
            stream_type = guess_stream_type(self.source.media_type)

        if 'file_size' in kwargs:
            self.source.size = kwargs.pop('file_size')

        if self.stream_type is not None and self.stream_type != stream_type:
            self.message.ClearField(self.stream_type)

        if stream_type in ('image', 'video', 'audio'):
            media = getattr(self, stream_type)
            media_args = {'file_metadata': None}
            if file_path is not None and not all((duration, width, height)):
                try:
                    media_args['file_metadata'] = binary_file_metadata(binary_file_parser(file_path))
                except:
                    log.exception('Could not read file metadata.')
            if isinstance(media, Playable):
                media_args['duration'] = duration
            if isinstance(media, Dimmensional):
                media_args['height'] = height
                media_args['width'] = width
            media.update(**media_args)

        return super().update(**kwargs)

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
    def has_source(self) -> bool:
        return self.message.HasField('source')

    @property
    def source(self) -> Source:
        return Source(self.message.source)

    @property
    def stream_type(self) -> str:
        return self.message.WhichOneof('type')

    @property
    def image(self) -> Image:
        return Image(self.message.image)

    @property
    def video(self) -> Video:
        return Video(self.message.video)

    @property
    def audio(self) -> Audio:
        return Audio(self.message.audio)


class Channel(BaseClaim):

    __slots__ = ()

    claim_type = Claim.CHANNEL

    object_fields = BaseClaim.object_fields + ('cover',)
    repeat_fields = BaseClaim.repeat_fields + ('featured',)

    def to_dict(self):
        claim = super().to_dict()
        claim['public_key'] = self.public_key
        if 'featured' in claim:
            claim['featured'] = self.featured.ids
        return claim

    @property
    def public_key(self) -> str:
        return hexlify(self.public_key_bytes).decode()

    @public_key.setter
    def public_key(self, sd_public_key: str):
        self.message.public_key = unhexlify(sd_public_key.encode())

    @property
    def public_key_bytes(self) -> bytes:
        if len(self.message.public_key) == 33:
            return self.message.public_key
        public_key_info = PublicKeyInfo.load(self.message.public_key)
        public_key = cPublicKey(public_key_info.native['public_key'])
        return public_key.format(compressed=True)

    @public_key_bytes.setter
    def public_key_bytes(self, public_key: bytes):
        self.message.public_key = public_key

    @property
    def email(self) -> str:
        return self.message.email

    @email.setter
    def email(self, email: str):
        self.message.email = email

    @property
    def website_url(self) -> str:
        return self.message.website_url

    @website_url.setter
    def website_url(self, website_url: str):
        self.message.website_url = website_url

    @property
    def cover(self) -> Source:
        return Source(self.message.cover)

    @property
    def featured(self) -> ClaimList:
        return ClaimList(self.message.featured)


class Repost(BaseClaim):

    __slots__ = ()

    claim_type = Claim.REPOST

    def update(self, **kwargs) -> dict:
        claim_type = kwargs.pop('claim_type', None)
        # Update common fields within BaseClaim.
        kwargs = super().update(strict_update=False, **kwargs)
        if claim_type:
            # Remaining updates go into deletes/edits of ClaimReference.
            kwargs = self.reference.update(claim_type, **kwargs)
        return kwargs

    def apply(self, reposted: 'Claim'):
        return self.reference.apply(reposted)

    @property
    def reference(self) -> ClaimReference:
        return ClaimReference(self.message)


class Collection(BaseClaim):

    __slots__ = ()

    claim_type = Claim.COLLECTION

    repeat_fields = BaseClaim.repeat_fields + ('claims',)

    def to_dict(self):
        claim = super().to_dict()
        if claim.pop('claim_references', None):
            claim['claims'] = self.claims.ids
        return claim

    @property
    def claims(self) -> ClaimList:
        return ClaimList(self.message)
