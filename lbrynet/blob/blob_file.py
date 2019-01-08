import os
import asyncio
import logging
import typing
from io import BytesIO
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.primitives.padding import PKCS7

from lbrynet.cryptoutils import backend, get_lbry_hash_obj
from lbrynet.error import DownloadCancelledError, InvalidBlobHashError
from lbrynet.blob import MAX_BLOB_SIZE, blobhash_length
from lbrynet.blob.writer import HashBlobWriter

if typing.TYPE_CHECKING:
    from lbrynet.peer import Peer
    from lbrynet.blob.blob_manager import BlobFileManager

log = logging.getLogger(__name__)


def is_valid_hashcharacter(char: str) -> bool:
    return char in "0123456789abcdef"


def is_valid_blobhash(blobhash: str) -> bool:
    """Checks whether the blobhash is the correct length and contains only
    valid characters (0-9, a-f)

    @param blobhash: string, the blobhash to check

    @return: True/False
    """
    return len(blobhash) == blobhash_length and all(is_valid_hashcharacter(l) for l in blobhash)


def encrypt_blob_bytes(key: bytes, iv: bytes, unencrypted: bytes) -> typing.Tuple[bytes, str]:
    cipher = Cipher(AES(key), modes.CBC(iv), backend=backend)
    padder = PKCS7(AES.block_size).padder()
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(padder.update(unencrypted) + padder.finalize()) + encryptor.finalize()
    digest = get_lbry_hash_obj()
    digest.update(encrypted)
    return encrypted, digest.hexdigest()


class BlobFile:
    """
    A chunk of data available on the network which is specified by a hashsum

    This class is used to create blobs on the local filesystem
    when we already know the blob hash before hand (i.e., when downloading blobs)
    Also can be used for reading from blobs on the local filesystem
    """

    def __init__(self, loop: asyncio.BaseEventLoop, blob_dir: str, blob_hash: str,
                 length: typing.Optional[int] = None,
                 blob_completed_callback: typing.Optional[typing.Callable[['BlobFile'], typing.Awaitable]] = None):
        if not is_valid_blobhash(blob_hash):
            raise InvalidBlobHashError(blob_hash)
        self.loop = loop
        self.blob_hash = blob_hash
        self.length = length
        self.blob_dir = blob_dir
        self.file_path = os.path.join(blob_dir, self.blob_hash)
        self.writers: typing.List[HashBlobWriter] = []

        self.verified: asyncio.Event = asyncio.Event(loop=self.loop)
        self.finished_writing = asyncio.Event(loop=loop)
        self.blob_write_lock = asyncio.Lock(loop=loop)
        if os.path.isfile(os.path.join(blob_dir, blob_hash)):
            length = length or int(os.stat(os.path.join(blob_dir, blob_hash)).st_size)
            self.length = length
            self.verified.set()
        self.saved_verified_blob = False
        self.blob_completed_callback = blob_completed_callback

    def writer_finished(self, writer: HashBlobWriter):
        def callback(finished: asyncio.Future):
            try:
                error = finished.result()
            except Exception as err:
                error = err
            if writer in self.writers:  # remove this download attempt
                self.writers.remove(writer)
            if not error:  # the blob downloaded, cancel all the other download attempts and set the result
                while self.writers:
                    other = self.writers.pop()
                    other.finished.cancel()
                    other.peer.disconnect_tcp()
                t = self.loop.create_task(self.save_verified_blob(writer))
                t.add_done_callback(lambda *_: self.finished_writing.set())
            elif not isinstance(error, (DownloadCancelledError, asyncio.CancelledError, asyncio.TimeoutError)):
                if writer.peer:
                    log.warning(f"failed to download {self.blob_hash[:8]} from {writer.peer.address}: {str(error)}")
                raise error
        return callback

    async def save_verified_blob(self, writer):
        def _save_verified():
            # log.debug(f"write blob file {self.blob_hash[:8]} from {writer.peer.address}")
            if not self.saved_verified_blob and not os.path.isfile(self.file_path):
                if self.get_length() == len(writer.verified_bytes):
                    with open(self.file_path, 'wb') as write_handle:
                        write_handle.write(writer.verified_bytes)
                    self.saved_verified_blob = True
                else:
                    raise Exception("length mismatch")

        if self.verified.is_set():
            return
        await self.blob_write_lock.acquire()
        try:
            await self.loop.run_in_executor(None, _save_verified)
        finally:
            self.verified.set()
            self.blob_write_lock.release()
        if self.blob_completed_callback:
            await self.blob_completed_callback(self)

    def open_for_writing(self, peer: typing.Optional['Peer'] = None) -> HashBlobWriter:
        """
        open a blob file to be written by peer, supports concurrent
        writers, as long as they are from different peers.
        """

        if os.path.exists(self.file_path):
            raise OSError(f"File already exists '{self.file_path}'")

        for writer in self.writers:
            if writer.peer is peer:
                raise Exception("Tried to download the same file twice simultaneously from the same peer")

        log.debug(f"Opening {self.blob_hash[:8]} to be written")
        fut = asyncio.Future(loop=self.loop)
        writer = HashBlobWriter(self.blob_hash, self.get_length, fut, peer)
        self.writers.append(writer)
        fut.add_done_callback(self.writer_finished(writer))
        return writer

    async def read(self) -> BytesIO:
        def _read() -> BytesIO:
            b = BytesIO()
            with open(self.file_path, "rb") as f:
                b.write(f.read())
            return b

        return await self.loop.run_in_executor(None, _read)

    async def close(self):
        while self.writers:
            self.writers.pop().finished.cancel()

    async def delete(self):
        await self.close()
        await self.blob_write_lock.acquire()
        try:
            self.saved_verified_blob = False
            if os.path.isfile(self.file_path):
                os.remove(self.file_path)
        finally:
            self.blob_write_lock.release()

    def decrypt(self, key: bytes, iv: bytes) -> bytes:
        """
        Decrypt a BlobFile to plaintext bytes
        """

        with open(self.file_path, "rb") as f:
            buff = f.read()
        if len(buff) != self.length:
            raise ValueError("unexpected length")
        cipher = Cipher(AES(key), modes.CBC(iv), backend=backend)
        unpadder = PKCS7(AES.block_size).unpadder()
        decryptor = cipher.decryptor()
        return unpadder.update(decryptor.update(buff) + decryptor.finalize()) + unpadder.finalize()

    @classmethod
    async def create_from_unencrypted(cls, loop: asyncio.BaseEventLoop, blob_manager: 'BlobFileManager', key: bytes,
                                      iv: bytes, unencrypted: bytes, blob_num: int,
                                      callback: typing.Callable[[str, bytes, int, int], None]):
        """
        Create an encrypted BlobFile from plaintext bytes
        """

        blob_bytes, blob_hash = encrypt_blob_bytes(key, iv, unencrypted)
        length = len(blob_bytes)
        callback(blob_hash, iv, length, blob_num)
        blob = blob_manager.get_blob(blob_hash, length)
        writer = blob.open_for_writing()
        writer.write(blob_bytes)
        await blob.verified.wait()
        return cls(loop, blob_manager.blob_dir, blob_hash, length)

    def set_length(self, length):
        if self.length is not None and length == self.length:
            return True
        if self.length is None and 0 <= length <= MAX_BLOB_SIZE:
            self.length = length
            return True
        log.warning("Got an invalid length. Previous length: %s, Invalid length: %s",
                    self.length, length)
        return False

    def get_length(self):
        return self.length

    def get_is_verified(self):
        return self.verified.is_set()

    def is_downloading(self):
        return len(self.writers) > 0
