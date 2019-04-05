import os
import re
import asyncio
import binascii
import logging
import typing
import contextlib
from io import BytesIO
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.primitives.padding import PKCS7

from lbrynet.cryptoutils import backend, get_lbry_hash_obj
from lbrynet.error import DownloadCancelledError, InvalidBlobHashError, InvalidDataError

from lbrynet.blob import MAX_BLOB_SIZE, blobhash_length
from lbrynet.blob.blob_info import BlobInfo
from lbrynet.blob.writer import HashBlobWriter

log = logging.getLogger(__name__)


_hexmatch = re.compile("^[a-f,0-9]+$")


def is_valid_blobhash(blobhash: str) -> bool:
    """Checks whether the blobhash is the correct length and contains only
    valid characters (0-9, a-f)

    @param blobhash: string, the blobhash to check

    @return: True/False
    """
    return len(blobhash) == blobhash_length and _hexmatch.match(blobhash)


def encrypt_blob_bytes(key: bytes, iv: bytes, unencrypted: bytes) -> typing.Tuple[bytes, str]:
    cipher = Cipher(AES(key), modes.CBC(iv), backend=backend)
    padder = PKCS7(AES.block_size).padder()
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padder.update(unencrypted) + padder.finalize()) + encryptor.finalize()
    digest = get_lbry_hash_obj()
    digest.update(encrypted)
    return encrypted, digest.hexdigest()


def decrypt_blob_bytes(read_handle: typing.BinaryIO, length: int, key: bytes, iv: bytes) -> bytes:
    buff = read_handle.read()
    if len(buff) != length:
        raise ValueError("unexpected length")
    cipher = Cipher(AES(key), modes.CBC(iv), backend=backend)
    unpadder = PKCS7(AES.block_size).unpadder()
    decryptor = cipher.decryptor()
    return unpadder.update(decryptor.update(buff) + decryptor.finalize()) + unpadder.finalize()


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
        'writing'
    ]

    def __init__(self, loop: asyncio.BaseEventLoop, blob_hash: str, length: typing.Optional[int] = None,
                 blob_completed_callback: typing.Optional[typing.Callable[['AbstractBlob'], typing.Awaitable]] = None,
                 blob_directory: typing.Optional[str] = None):
        self.loop = loop
        self.blob_hash = blob_hash
        self.length = length
        self.blob_completed_callback = blob_completed_callback
        self.blob_directory = blob_directory
        self.writers: typing.List[HashBlobWriter] = []
        self.verified: asyncio.Event = asyncio.Event(loop=self.loop)
        self.writing: asyncio.Event = asyncio.Event(loop=self.loop)
        if not is_valid_blobhash(blob_hash):
            raise InvalidBlobHashError(blob_hash)

    def __del__(self):
        if self.writers or self.is_readable():
            log.warning("%s not closed before being garbage collected", self.blob_hash)
            self.close()

    @contextlib.contextmanager
    def reader_context(self) -> typing.ContextManager[typing.BinaryIO]:
        raise NotImplementedError()

    def _write_blob(self, blob_bytes: bytes):
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
            self.writers.pop().finished.cancel()

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
            return await self.loop.sendfile(writer.transport, handle, count=self.get_length())

    def decrypt(self, key: bytes, iv: bytes) -> bytes:
        """
        Decrypt a BlobFile to plaintext bytes
        """

        with self.reader_context() as reader:
            return decrypt_blob_bytes(reader, self.length, key, iv)

    @classmethod
    async def create_from_unencrypted(cls, loop: asyncio.BaseEventLoop, blob_dir: typing.Optional[str], key: bytes,
                                      iv: bytes, unencrypted: bytes, blob_num: int) -> BlobInfo:
        """
        Create an encrypted BlobFile from plaintext bytes
        """

        blob_bytes, blob_hash = encrypt_blob_bytes(key, iv, unencrypted)
        length = len(blob_bytes)
        blob = cls(loop, blob_hash, length, blob_directory=blob_dir)
        writer = blob.get_blob_writer()
        writer.write(blob_bytes)
        await blob.verified.wait()
        return BlobInfo(blob_num, length, binascii.hexlify(iv).decode(), blob_hash)

    def save_verified_blob(self, verified_bytes: bytes):
        if self.verified.is_set():
            return
        if self.is_writeable():
            self._write_blob(verified_bytes)
            self.verified.set()
            if self.blob_completed_callback:
                self.loop.create_task(self.blob_completed_callback(self))

    def get_blob_writer(self) -> HashBlobWriter:
        fut = asyncio.Future(loop=self.loop)
        writer = HashBlobWriter(self.blob_hash, self.get_length, fut)
        self.writers.append(writer)

        def writer_finished_callback(finished: asyncio.Future):
            try:
                err = finished.exception()
                if err:
                    raise err
                verified_bytes = finished.result()
                while self.writers:
                    other = self.writers.pop()
                    if other is not writer:
                        other.finished.cancel()
                self.save_verified_blob(verified_bytes)
                return
            except (InvalidBlobHashError, InvalidDataError) as error:
                log.debug("writer error downloading %s: %s", self.blob_hash[:8], str(error))
            except (DownloadCancelledError, asyncio.CancelledError, asyncio.TimeoutError):
                pass
            finally:
                if writer in self.writers:
                    self.writers.remove(writer)

        fut.add_done_callback(writer_finished_callback)
        return writer


class BlobBuffer(AbstractBlob):
    """
    An in-memory only blob
    """
    def __init__(self, loop: asyncio.BaseEventLoop, blob_hash: str, length: typing.Optional[int] = None,
                 blob_completed_callback: typing.Optional[typing.Callable[['AbstractBlob'], typing.Awaitable]] = None,
                 blob_directory: typing.Optional[str] = None):
        super().__init__(loop, blob_hash, length, blob_completed_callback, blob_directory)
        self._verified_bytes: typing.Optional[BytesIO] = None

    @contextlib.contextmanager
    def reader_context(self) -> typing.ContextManager[typing.BinaryIO]:
        if not self.is_readable():
            raise OSError("cannot open blob for reading")
        try:
            yield self._verified_bytes
        finally:
            self._verified_bytes.close()
            self._verified_bytes = None
            self.verified.clear()

    def _write_blob(self, blob_bytes: bytes):
        if self._verified_bytes:
            raise OSError("already have bytes for blob")
        self._verified_bytes = BytesIO(blob_bytes)

    def delete(self):
        if self._verified_bytes:
            self._verified_bytes.close()
            self._verified_bytes = None
        return super().delete()


class BlobFile(AbstractBlob):
    """
    A blob existing on the local file system
    """
    def __init__(self, loop: asyncio.BaseEventLoop, blob_hash: str, length: typing.Optional[int] = None,
                 blob_completed_callback: typing.Optional[typing.Callable[['AbstractBlob'], typing.Awaitable]] = None,
                 blob_directory: typing.Optional[str] = None):
        if not blob_directory or not os.path.isdir(blob_directory):
            raise OSError(f"invalid blob directory '{blob_directory}'")
        super().__init__(loop, blob_hash, length, blob_completed_callback, blob_directory)
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

    def get_blob_writer(self) -> HashBlobWriter:
        if self.file_exists:
            raise OSError(f"File already exists '{self.file_path}'")
        return super().get_blob_writer()

    @contextlib.contextmanager
    def reader_context(self) -> typing.ContextManager[typing.BinaryIO]:
        handle = open(self.file_path, 'rb')
        try:
            yield handle
        finally:
            handle.close()

    def _write_blob(self, blob_bytes: bytes):
        with open(self.file_path, 'wb') as f:
            f.write(blob_bytes)

    def delete(self):
        if os.path.isfile(self.file_path):
            os.remove(self.file_path)
        return super().delete()

    @classmethod
    async def create_from_unencrypted(cls, loop: asyncio.BaseEventLoop, blob_dir: str, key: bytes,
                                      iv: bytes, unencrypted: bytes, blob_num: int) -> BlobInfo:
        if not blob_dir or not os.path.isdir(blob_dir):
            raise OSError(f"cannot create blob in directory: '{blob_dir}'")
        return await super().create_from_unencrypted(loop, blob_dir, key, iv, unencrypted, blob_num)
