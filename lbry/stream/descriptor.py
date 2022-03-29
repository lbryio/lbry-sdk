import os
import json
import binascii
import logging
import typing
import asyncio
import time
import re
from collections import OrderedDict
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from lbry.blob import MAX_BLOB_SIZE
from lbry.blob.blob_info import BlobInfo
from lbry.blob.blob_file import AbstractBlob, BlobFile
from lbry.utils import get_lbry_hash_obj
from lbry.error import InvalidStreamDescriptorError

log = logging.getLogger(__name__)

RE_ILLEGAL_FILENAME_CHARS = re.compile(
    r'('
    r'[<>:"/\\|?*]+|'                  # Illegal characters
    r'[\x00-\x1F]+|'                   # All characters in range 0-31
    r'[ \t]*(\.)+[ \t]*$|'             # Dots at the end
    r'(^[ \t]+|[ \t]+$)|'              # Leading and trailing whitespace
    r'^CON$|^PRN$|^AUX$|'              # Illegal names
    r'^NUL$|^COM[1-9]$|^LPT[1-9]$'     # ...
    r')'
)


def format_sd_info(stream_name: str, key: str, suggested_file_name: str, stream_hash: str,
                   blobs: typing.List[typing.Dict]) -> typing.Dict:
    return {
        "stream_type": "lbryfile",
        "stream_name": stream_name,
        "key": key,
        "suggested_file_name": suggested_file_name,
        "stream_hash": stream_hash,
        "blobs": blobs
    }


def random_iv_generator() -> typing.Generator[bytes, None, None]:
    while 1:
        yield os.urandom(AES.block_size // 8)


def read_bytes(file_path: str, offset: int, to_read: int):
    with open(file_path, 'rb') as f:
        f.seek(offset)
        return f.read(to_read)


async def file_reader(file_path: str):
    length = int(os.stat(file_path).st_size)
    offset = 0

    while offset < length:
        bytes_to_read = min((length - offset), MAX_BLOB_SIZE - 1)
        if not bytes_to_read:
            break
        blob_bytes = await asyncio.get_event_loop().run_in_executor(
            None, read_bytes, file_path, offset, bytes_to_read
        )
        yield blob_bytes
        offset += bytes_to_read


def sanitize_file_name(dirty_name: str, default_file_name: str = 'lbry_download'):
    file_name, ext = os.path.splitext(dirty_name)
    file_name = re.sub(RE_ILLEGAL_FILENAME_CHARS, '', file_name)
    ext = re.sub(RE_ILLEGAL_FILENAME_CHARS, '', ext)

    if not file_name:
        log.warning('Unable to sanitize file name for %s, returning default value %s', dirty_name, default_file_name)
        file_name = default_file_name
    if len(ext) > 1:
        file_name += ext

    return file_name


class StreamDescriptor:
    __slots__ = [
        'loop',
        'blob_dir',
        'stream_name',
        'key',
        'suggested_file_name',
        'blobs',
        'stream_hash',
        'sd_hash'
    ]

    def __init__(self, loop: asyncio.AbstractEventLoop, blob_dir: str, stream_name: str, key: str,
                 suggested_file_name: str, blobs: typing.List[BlobInfo], stream_hash: typing.Optional[str] = None,
                 sd_hash: typing.Optional[str] = None):
        self.loop = loop
        self.blob_dir = blob_dir
        self.stream_name = stream_name
        self.key = key
        self.suggested_file_name = suggested_file_name
        self.blobs = blobs
        self.stream_hash = stream_hash or self.get_stream_hash()
        self.sd_hash = sd_hash

    @property
    def length(self) -> int:
        return len(self.as_json())

    def get_stream_hash(self) -> str:
        return self.calculate_stream_hash(
            binascii.hexlify(self.stream_name.encode()), self.key.encode(),
            binascii.hexlify(self.suggested_file_name.encode()),
            [blob_info.as_dict() for blob_info in self.blobs]
        )

    def calculate_sd_hash(self) -> str:
        h = get_lbry_hash_obj()
        h.update(self.as_json())
        return h.hexdigest()

    def as_json(self) -> bytes:
        return json.dumps(
            format_sd_info(binascii.hexlify(self.stream_name.encode()).decode(), self.key,
                           binascii.hexlify(self.suggested_file_name.encode()).decode(),
                           self.stream_hash,
                           [blob_info.as_dict() for blob_info in self.blobs]), sort_keys=True
        ).encode()

    def old_sort_json(self) -> bytes:
        blobs = []
        for blob in self.blobs:
            blobs.append(OrderedDict(
                [('length', blob.length), ('blob_num', blob.blob_num), ('iv', blob.iv)] if not blob.blob_hash else
                [('length', blob.length), ('blob_num', blob.blob_num), ('blob_hash', blob.blob_hash), ('iv', blob.iv)]
            ))
            if not blob.blob_hash:
                break
        return json.dumps(
            OrderedDict([
                ('stream_name', binascii.hexlify(self.stream_name.encode()).decode()),
                ('blobs', blobs),
                ('stream_type', 'lbryfile'),
                ('key', self.key),
                ('suggested_file_name', binascii.hexlify(self.suggested_file_name.encode()).decode()),
                ('stream_hash', self.stream_hash),
            ])
        ).encode()

    def calculate_old_sort_sd_hash(self) -> str:
        h = get_lbry_hash_obj()
        h.update(self.old_sort_json())
        return h.hexdigest()

    async def make_sd_blob(
            self, blob_file_obj: typing.Optional[AbstractBlob] = None, old_sort: typing.Optional[bool] = False,
            blob_completed_callback: typing.Optional[typing.Callable[['AbstractBlob'], None]] = None,
            added_on: float = None, is_mine: bool = False
        ):
        sd_hash = self.calculate_sd_hash() if not old_sort else self.calculate_old_sort_sd_hash()
        if not old_sort:
            sd_data = self.as_json()
        else:
            sd_data = self.old_sort_json()
        sd_blob = blob_file_obj or BlobFile(
            self.loop, sd_hash, len(sd_data), blob_completed_callback, self.blob_dir, added_on, is_mine
        )
        if blob_file_obj:
            blob_file_obj.set_length(len(sd_data))
        if not sd_blob.get_is_verified():
            writer = sd_blob.get_blob_writer()
            writer.write(sd_data)

        await sd_blob.verified.wait()
        sd_blob.close()
        return sd_blob

    @classmethod
    def _from_stream_descriptor_blob(cls, loop: asyncio.AbstractEventLoop, blob_dir: str,
                                     blob: AbstractBlob) -> 'StreamDescriptor':
        with blob.reader_context() as blob_reader:
            json_bytes = blob_reader.read()
        try:
            decoded = json.loads(json_bytes.decode())
        except json.JSONDecodeError:
            blob.delete()
            raise InvalidStreamDescriptorError("Does not decode as valid JSON")
        if decoded['blobs'][-1]['length'] != 0:
            raise InvalidStreamDescriptorError("Does not end with a zero-length blob.")
        if any(blob_info['length'] == 0 for blob_info in decoded['blobs'][:-1]):
            raise InvalidStreamDescriptorError("Contains zero-length data blob")
        if 'blob_hash' in decoded['blobs'][-1]:
            raise InvalidStreamDescriptorError("Stream terminator blob should not have a hash")
        if any(i != blob_info['blob_num'] for i, blob_info in enumerate(decoded['blobs'])):
            raise InvalidStreamDescriptorError("Stream contains out of order or skipped blobs")
        added_on = time.time()
        descriptor = cls(
            loop, blob_dir,
            binascii.unhexlify(decoded['stream_name']).decode(),
            decoded['key'],
            binascii.unhexlify(decoded['suggested_file_name']).decode(),
            [BlobInfo(info['blob_num'], info['length'], info['iv'], added_on, info.get('blob_hash'))
             for info in decoded['blobs']],
            decoded['stream_hash'],
            blob.blob_hash
        )
        if descriptor.get_stream_hash() != decoded['stream_hash']:
            raise InvalidStreamDescriptorError("Stream hash does not match stream metadata")
        return descriptor

    @classmethod
    async def from_stream_descriptor_blob(cls, loop: asyncio.AbstractEventLoop, blob_dir: str,
                                          blob: AbstractBlob) -> 'StreamDescriptor':
        if not blob.is_readable():
            raise InvalidStreamDescriptorError(f"unreadable/missing blob: {blob.blob_hash}")
        return await loop.run_in_executor(None, cls._from_stream_descriptor_blob, loop, blob_dir, blob)

    @staticmethod
    def get_blob_hashsum(blob_dict: typing.Dict):
        length = blob_dict['length']
        if length != 0:
            blob_hash = blob_dict['blob_hash']
        else:
            blob_hash = None
        blob_num = blob_dict['blob_num']
        iv = blob_dict['iv']
        blob_hashsum = get_lbry_hash_obj()
        if length != 0:
            blob_hashsum.update(blob_hash.encode())
        blob_hashsum.update(str(blob_num).encode())
        blob_hashsum.update(iv.encode())
        blob_hashsum.update(str(length).encode())
        return blob_hashsum.digest()

    @staticmethod
    def calculate_stream_hash(hex_stream_name: bytes, key: bytes, hex_suggested_file_name: bytes,
                              blob_infos: typing.List[typing.Dict]) -> str:
        h = get_lbry_hash_obj()
        h.update(hex_stream_name)
        h.update(key)
        h.update(hex_suggested_file_name)
        blobs_hashsum = get_lbry_hash_obj()
        for blob in blob_infos:
            blobs_hashsum.update(StreamDescriptor.get_blob_hashsum(blob))
        h.update(blobs_hashsum.digest())
        return h.hexdigest()

    @classmethod
    async def create_stream(
            cls, loop: asyncio.AbstractEventLoop, blob_dir: str, file_path: str, key: typing.Optional[bytes] = None,
            iv_generator: typing.Optional[typing.Generator[bytes, None, None]] = None,
            old_sort: bool = False,
            blob_completed_callback: typing.Optional[typing.Callable[['AbstractBlob'],
                                                                     asyncio.Task]] = None) -> 'StreamDescriptor':
        blobs: typing.List[BlobInfo] = []

        iv_generator = iv_generator or random_iv_generator()
        key = key or os.urandom(AES.block_size // 8)
        blob_num = -1
        added_on = time.time()
        async for blob_bytes in file_reader(file_path):
            blob_num += 1
            blob_info = await BlobFile.create_from_unencrypted(
                loop, blob_dir, key, next(iv_generator), blob_bytes, blob_num, added_on, True, blob_completed_callback
            )
            blobs.append(blob_info)
        blobs.append(
            # add the stream terminator
            BlobInfo(len(blobs), 0, binascii.hexlify(next(iv_generator)).decode(), added_on, None, True)
        )
        file_name = os.path.basename(file_path)
        suggested_file_name = sanitize_file_name(file_name)
        descriptor = cls(
            loop, blob_dir, file_name, binascii.hexlify(key).decode(), suggested_file_name, blobs
        )
        sd_blob = await descriptor.make_sd_blob(
            old_sort=old_sort, blob_completed_callback=blob_completed_callback, added_on=added_on, is_mine=True
        )
        descriptor.sd_hash = sd_blob.blob_hash
        return descriptor

    def lower_bound_decrypted_length(self) -> int:
        length = sum(blob.length - 1 for blob in self.blobs[:-2])
        return length + self.blobs[-2].length - (AES.block_size // 8)

    def upper_bound_decrypted_length(self) -> int:
        return self.lower_bound_decrypted_length() + (AES.block_size // 8)

    @classmethod
    async def recover(cls, blob_dir: str, sd_blob: 'AbstractBlob', stream_hash: str, stream_name: str,
                      suggested_file_name: str, key: str,
                      blobs: typing.List['BlobInfo']) -> typing.Optional['StreamDescriptor']:
        descriptor = cls(asyncio.get_event_loop(), blob_dir, stream_name, key, suggested_file_name,
                         blobs, stream_hash, sd_blob.blob_hash)

        if descriptor.calculate_sd_hash() == sd_blob.blob_hash:  # first check for a normal valid sd
            old_sort = False
        elif descriptor.calculate_old_sort_sd_hash() == sd_blob.blob_hash:  # check if old field sorting works
            old_sort = True
        else:
            return
        await descriptor.make_sd_blob(sd_blob, old_sort)
        return descriptor
