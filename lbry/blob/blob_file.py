import os
import re
import time
import asyncio
import binascii
import logging
import typing
import contextlib
from io import BytesIO
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.primitives.padding import PKCS7
from cryptography.hazmat.backends import default_backend

from lbry.utils import get_lbry_hash_obj
from lbry.error import DownloadCancelledError, InvalidBlobHashError, InvalidDataError

from lbry.blob import MAX_BLOB_SIZE, BLOBHASH_LENGTH
from lbry.blob.blob_info import BlobInfo
from lbry.blob.writer import HashBlobWriter

log = logging.getLogger(__name__)


HEXMATCH = re.compile("^[a-f,0-9]+$")
BACKEND = default_backend()


def is_valid_blobhash(blobhash: str) -> bool:
    """Checks whether the blobhash is the correct length and contains only
    valid characters (0-9, a-f)

    @param blobhash: string, the blobhash to check

    @return: True/False
    """
    return len(blobhash) == BLOBHASH_LENGTH and HEXMATCH.match(blobhash)


def encrypt_blob_bytes(key: bytes, iv: bytes, unencrypted: bytes) -> typing.Tuple[bytes, str]:
    cipher = Cipher(AES(key), modes.CBC(iv), backend=BACKEND)
    padder = PKCS7(AES.block_size).padder()
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padder.update(unencrypted) + padder.finalize()) + encryptor.finalize()
    digest = get_lbry_hash_obj()
    digest.update(encrypted)
    return encrypted, digest.hexdigest()


def decrypt_blob_bytes(data: bytes, length: int, key: bytes, iv: bytes) -> bytes:
    if len(data) != length:
        raise ValueError("unexpected length")
    cipher = Cipher(AES(key), modes.CBC(iv), backend=BACKEND)
    unpadder = PKCS7(AES.block_size).unpadder()
    decryptor = cipher.decryptor()
    return unpadder.update(decryptor.update(data) + decryptor.finalize()) + unpadder.finalize()


class AbstractBlob:
    """
    A chunk of data (up to 2MB) available on the network which is specified by a sha384 hash

    This class is non-io specific
    """
    __slots__ = [
        'loop',
        'blob_hash',
        'length',
        'blob_completed_callback',
        'blob_directory',
        'writers',
        'verified',
        'writing',
        'readers',
        'added_on',
        'is_mine',
    ]

    def __init__(
        self, loop: asyncio.AbstractEventLoop, blob_hash: str, length: typing.Optional[int] = None,
        blob_completed_callback: typing.Optional[typing.Callable[['AbstractBlob'], asyncio.Task]] = None,
        blob_directory: typing.Optional[str] = None, added_on: typing.Optional[int] = None, is_mine: bool = False,
    ):
        self.loop = loop
        self.blob_hash = blob_hash
        self.length = length
        self.blob_completed_callback = blob_completed_callback
        self.blob_directory = blob_directory
        self.writers: typing.Dict[typing.Tuple[typing.Optional[str], typing.Optional[int]], HashBlobWriter] = {}
        self.verified: asyncio.Event = asyncio.Event()
        self.writing: asyncio.Event = asyncio.Event()
        self.readers: typing.List[typing.BinaryIO] = []
        self.added_on = added_on or time.time()
        self.is_mine = is_mine

        if not is_valid_blobhash(blob_hash):
            raise InvalidBlobHashError(blob_hash)

    def __del__(self):
        if self.writers or self.readers:
            log.warning("%s not closed before being garbage collected", self.blob_hash)
            self.close()

    @contextlib.contextmanager
    def _reader_context(self) -> typing.ContextManager[typing.BinaryIO]:
        raise NotImplementedError()

    @contextlib.contextmanager
    def reader_context(self) -> typing.ContextManager[typing.BinaryIO]:
        if not self.is_readable():
            raise OSError(f"{str(type(self))} not readable, {len(self.readers)} readers {len(self.writers)} writers")
        with self._reader_context() as reader:
            try:
                self.readers.append(reader)
                yield reader
            finally:
                if reader in self.readers:
                    self.readers.remove(reader)

    def _write_blob(self, blob_bytes: bytes) -> asyncio.Task:
        raise NotImplementedError()

    def set_length(self, length) -> None:
        if self.length is not None and length == self.length:
            return
        if self.length is None and 0 <= length <= MAX_BLOB_SIZE:
            self.length = length
            return
        log.warning("Got an invalid length. Previous length: %s, Invalid length: %s", self.length, length)

    def get_length(self) -> typing.Optional[int]:
        return self.length

    def get_is_verified(self) -> bool:
        return self.verified.is_set()

    def is_readable(self) -> bool:
        return self.verified.is_set()

    def is_writeable(self) -> bool:
        return not self.writing.is_set()

    def write_blob(self, blob_bytes: bytes):
        if not self.is_writeable():
            raise OSError("cannot open blob for writing")
        try:
            self.writing.set()
            self._write_blob(blob_bytes)
        finally:
            self.writing.clear()

    def close(self):
        while self.writers:
            _, writer = self.writers.popitem()
            if writer and writer.finished and not writer.finished.done() and not self.loop.is_closed():
                writer.finished.cancel()
        while self.readers:
            reader = self.readers.pop()
            if reader:
                reader.close()

    def delete(self):
        self.close()
        self.verified.clear()
        self.length = None

    async def sendfile(self, writer: asyncio.StreamWriter) -> int:
        """
        Read and send the file to the writer and return the number of bytes sent
        """

        if not self.is_readable():
            raise OSError('blob files cannot be read')
        with self.reader_context() as handle:
            try:
                return await self.loop.sendfile(writer.transport, handle, count=self.get_length())
            except (ConnectionError, BrokenPipeError, RuntimeError, OSError, AttributeError):
                return -1

    def decrypt(self, key: bytes, iv: bytes) -> bytes:
        """
        Decrypt a BlobFile to plaintext bytes
        """

        with self.reader_context() as reader:
            return decrypt_blob_bytes(reader.read(), self.length, key, iv)

    @classmethod
    async def create_from_unencrypted(
        cls, loop: asyncio.AbstractEventLoop, blob_dir: typing.Optional[str], key: bytes, iv: bytes,
        unencrypted: bytes, blob_num: int, added_on: int, is_mine: bool,
        blob_completed_callback: typing.Optional[typing.Callable[['AbstractBlob'], None]] = None,
    ) -> BlobInfo:
        """
        Create an encrypted BlobFile from plaintext bytes
        """

        blob_bytes, blob_hash = encrypt_blob_bytes(key, iv, unencrypted)
        length = len(blob_bytes)
        blob = cls(loop, blob_hash, length, blob_completed_callback, blob_dir, added_on, is_mine)
        writer = blob.get_blob_writer()
        writer.write(blob_bytes)
        await blob.verified.wait()
        return BlobInfo(blob_num, length, binascii.hexlify(iv).decode(), added_on, blob_hash, is_mine)

    def save_verified_blob(self, verified_bytes: bytes):
        if self.verified.is_set():
            return

        def update_events(_):
            self.verified.set()
            self.writing.clear()

        if self.is_writeable():
            self.writing.set()
            task = self._write_blob(verified_bytes)
            task.add_done_callback(update_events)
            if self.blob_completed_callback:
                task.add_done_callback(lambda _: self.blob_completed_callback(self))

    def get_blob_writer(self, peer_address: typing.Optional[str] = None,
                        peer_port: typing.Optional[int] = None) -> HashBlobWriter:
        if (peer_address, peer_port) in self.writers and not self.writers[(peer_address, peer_port)].closed():
            raise OSError(f"attempted to download blob twice from {peer_address}:{peer_port}")
        fut = asyncio.Future()
        writer = HashBlobWriter(self.blob_hash, self.get_length, fut)
        self.writers[(peer_address, peer_port)] = writer

        def remove_writer(_):
            if (peer_address, peer_port) in self.writers:
                del self.writers[(peer_address, peer_port)]

        fut.add_done_callback(remove_writer)

        def writer_finished_callback(finished: asyncio.Future):
            try:
                err = finished.exception()
                if err:
                    raise err
                verified_bytes = finished.result()
                while self.writers:
                    _, other = self.writers.popitem()
                    if other is not writer:
                        other.close_handle()
                self.save_verified_blob(verified_bytes)
            except (InvalidBlobHashError, InvalidDataError) as error:
                log.warning("writer error downloading %s: %s", self.blob_hash[:8], str(error))
            except (DownloadCancelledError, asyncio.CancelledError, asyncio.TimeoutError):
                pass

        fut.add_done_callback(writer_finished_callback)
        return writer


class BlobBuffer(AbstractBlob):
    """
    An in-memory only blob
    """
    def __init__(
        self, loop: asyncio.AbstractEventLoop, blob_hash: str, length: typing.Optional[int] = None,
        blob_completed_callback: typing.Optional[typing.Callable[['AbstractBlob'], asyncio.Task]] = None,
        blob_directory: typing.Optional[str] = None, added_on: typing.Optional[int] = None, is_mine: bool = False
    ):
        self._verified_bytes: typing.Optional[BytesIO] = None
        super().__init__(loop, blob_hash, length, blob_completed_callback, blob_directory, added_on, is_mine)

    @contextlib.contextmanager
    def _reader_context(self) -> typing.ContextManager[typing.BinaryIO]:
        if not self.is_readable():
            raise OSError("cannot open blob for reading")
        try:
            yield self._verified_bytes
        finally:
            if self._verified_bytes:
                self._verified_bytes.close()
            self._verified_bytes = None
            self.verified.clear()

    def _write_blob(self, blob_bytes: bytes):
        async def write():
            if self._verified_bytes:
                raise OSError("already have bytes for blob")
            self._verified_bytes = BytesIO(blob_bytes)
        return self.loop.create_task(write())

    def delete(self):
        if self._verified_bytes:
            self._verified_bytes.close()
            self._verified_bytes = None
        return super().delete()

    def __del__(self):
        super().__del__()
        if self._verified_bytes:
            self.delete()


class BlobFile(AbstractBlob):
    """
    A blob existing on the local file system
    """
    def __init__(
        self, loop: asyncio.AbstractEventLoop, blob_hash: str, length: typing.Optional[int] = None,
        blob_completed_callback: typing.Optional[typing.Callable[['AbstractBlob'], asyncio.Task]] = None,
        blob_directory: typing.Optional[str] = None, added_on: typing.Optional[int] = None, is_mine: bool = False
    ):
        super().__init__(loop, blob_hash, length, blob_completed_callback, blob_directory, added_on, is_mine)
        if not blob_directory or not os.path.isdir(blob_directory):
            raise OSError(f"invalid blob directory '{blob_directory}'")
        self.file_path = os.path.join(self.blob_directory, self.blob_hash)
        if self.file_exists:
            file_size = int(os.stat(self.file_path).st_size)
            if length and length != file_size:
                log.warning("expected %s to be %s bytes, file has %s", self.blob_hash, length, file_size)
                self.delete()
            else:
                self.length = file_size
                self.verified.set()

    @property
    def file_exists(self):
        return os.path.isfile(self.file_path)

    def is_writeable(self) -> bool:
        return super().is_writeable() and not os.path.isfile(self.file_path)

    def get_blob_writer(self, peer_address: typing.Optional[str] = None,
                        peer_port: typing.Optional[str] = None) -> HashBlobWriter:
        if self.file_exists:
            raise OSError(f"File already exists '{self.file_path}'")
        return super().get_blob_writer(peer_address, peer_port)

    @contextlib.contextmanager
    def _reader_context(self) -> typing.ContextManager[typing.BinaryIO]:
        handle = open(self.file_path, 'rb')
        try:
            yield handle
        finally:
            handle.close()

    def _write_blob(self, blob_bytes: bytes):
        def _write_blob():
            with open(self.file_path, 'wb') as f:
                f.write(blob_bytes)

        async def write_blob():
            await self.loop.run_in_executor(None, _write_blob)

        return self.loop.create_task(write_blob())

    def delete(self):
        super().delete()
        if os.path.isfile(self.file_path):
            os.remove(self.file_path)

    @classmethod
    async def create_from_unencrypted(
        cls, loop: asyncio.AbstractEventLoop, blob_dir: typing.Optional[str], key: bytes, iv: bytes,
        unencrypted: bytes, blob_num: int, added_on: float, is_mine: bool,
        blob_completed_callback: typing.Optional[typing.Callable[['AbstractBlob'], asyncio.Task]] = None
    ) -> BlobInfo:
        if not blob_dir or not os.path.isdir(blob_dir):
            raise OSError(f"cannot create blob in directory: '{blob_dir}'")
        return await super().create_from_unencrypted(
            loop, blob_dir, key, iv, unencrypted, blob_num, added_on, is_mine, blob_completed_callback
        )
