import asyncio
import hashlib
import os
import logging
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Optional, Iterator, Tuple
from binascii import hexlify

from torba.client.util import ArithUint256
from torba.client.hash import double_sha256

log = logging.getLogger(__name__)


class InvalidHeader(Exception):

    def __init__(self, height, message):
        super().__init__(message)
        self.message = message
        self.height = height


class BaseHeaders:

    header_size: int
    chunk_size: int

    max_target: int
    genesis_hash: Optional[bytes]
    target_timespan: int

    validate_difficulty: bool = True
    checkpoint = None

    def __init__(self, path) -> None:
        if path == ':memory:':
            self.io = BytesIO()
        self.path = path
        self._size: Optional[int] = None

    async def open(self):
        if self.path != ':memory:':
            if not os.path.exists(self.path):
                self.io = open(self.path, 'w+b')
            else:
                self.io = open(self.path, 'r+b')

    async def close(self):
        self.io.close()

    @staticmethod
    def serialize(header: dict) -> bytes:
        raise NotImplementedError

    @staticmethod
    def deserialize(height, header):
        raise NotImplementedError

    def get_next_chunk_target(self, chunk: int) -> ArithUint256:
        return ArithUint256(self.max_target)

    @staticmethod
    def get_next_block_target(chunk_target: ArithUint256, previous: Optional[dict],
                              current: Optional[dict]) -> ArithUint256:
        return chunk_target

    def __len__(self) -> int:
        if self._size is None:
            self._size = self.io.seek(0, os.SEEK_END) // self.header_size
        return self._size

    def __bool__(self):
        return True

    def __getitem__(self, height) -> dict:
        if isinstance(height, slice):
            raise NotImplementedError("Slicing of header chain has not been implemented yet.")
        if not 0 <= height <= self.height:
            raise IndexError(f"{height} is out of bounds, current height: {self.height}")
        return self.deserialize(height, self.get_raw_header(height))

    def get_raw_header(self, height) -> bytes:
        self.io.seek(height * self.header_size, os.SEEK_SET)
        return self.io.read(self.header_size)

    @property
    def height(self) -> int:
        return len(self)-1

    @property
    def bytes_size(self):
        return len(self) * self.header_size

    def hash(self, height=None) -> bytes:
        return self.hash_header(
            self.get_raw_header(height if height is not None else self.height)
        )

    @staticmethod
    def hash_header(header: bytes) -> bytes:
        if header is None:
            return b'0' * 64
        return hexlify(double_sha256(header)[::-1])

    @asynccontextmanager
    async def checkpointed_connector(self):
        buf = BytesIO()
        try:
            yield buf
        finally:
            await asyncio.sleep(0)
            final_height = len(self) + buf.tell() // self.header_size
            verifiable_bytes = (self.checkpoint[0] - len(self)) * self.header_size if self.checkpoint else 0
            if verifiable_bytes > 0 and final_height >= self.checkpoint[0]:
                buf.seek(0)
                self.io.seek(0)
                h = hashlib.sha256()
                h.update(self.io.read())
                h.update(buf.read(verifiable_bytes))
                if h.hexdigest().encode() == self.checkpoint[1]:
                    buf.seek(0)
                    self._write(len(self), buf.read(verifiable_bytes))
                    remaining = buf.read()
                    buf.seek(0)
                    buf.write(remaining)
                    buf.truncate()
                else:
                    log.warning("Checkpoint mismatch, connecting headers through slow method.")
            if buf.tell() > 0:
                await self.connect(len(self), buf.getvalue())

    async def connect(self, start: int, headers: bytes) -> int:
        added = 0
        bail = False
        for height, chunk in self._iterate_chunks(start, headers):
            try:
                # validate_chunk() is CPU bound and reads previous chunks from file system
                self.validate_chunk(height, chunk)
            except InvalidHeader as e:
                bail = True
                chunk = chunk[:(height-e.height)*self.header_size]
            added += self._write(height, chunk) if chunk else 0
            if bail:
                break
        return added

    def _write(self, height, verified_chunk):
        self.io.seek(height * self.header_size, os.SEEK_SET)
        written = self.io.write(verified_chunk) // self.header_size
        self.io.truncate()
        # .seek()/.write()/.truncate() might also .flush() when needed
        # the goal here is mainly to ensure we're definitely flush()'ing
        self.io.flush()
        self._size = self.io.tell() // self.header_size
        return written

    def validate_chunk(self, height, chunk):
        previous_hash, previous_header, previous_previous_header = None, None, None
        if height > 0:
            previous_header = self[height-1]
            previous_hash = self.hash(height-1)
        if height > 1:
            previous_previous_header = self[height-2]
        chunk_target = self.get_next_chunk_target(height // 2016 - 1)
        for current_hash, current_header in self._iterate_headers(height, chunk):
            block_target = self.get_next_block_target(chunk_target, previous_previous_header, previous_header)
            self.validate_header(height, current_hash, current_header, previous_hash, block_target)
            previous_previous_header = previous_header
            previous_header = current_header
            previous_hash = current_hash

    def validate_header(self, height: int, current_hash: bytes,
                        header: dict, previous_hash: bytes, target: ArithUint256):

        if previous_hash is None:
            if self.genesis_hash is not None and self.genesis_hash != current_hash:
                raise InvalidHeader(
                    height, f"genesis header doesn't match: {current_hash.decode()} "
                            f"vs expected {self.genesis_hash.decode()}")
            return

        if header['prev_block_hash'] != previous_hash:
            raise InvalidHeader(
                height, "previous hash mismatch: {} vs expected {}".format(
                    header['prev_block_hash'].decode(), previous_hash.decode())
            )

        if self.validate_difficulty:

            if header['bits'] != target.compact:
                raise InvalidHeader(
                    height, "bits mismatch: {} vs expected {}".format(
                        header['bits'], target.compact)
                )

            proof_of_work = self.get_proof_of_work(current_hash)
            if proof_of_work > target:
                raise InvalidHeader(
                    height, f"insufficient proof of work: {proof_of_work.value} vs target {target.value}"
                )

    async def repair(self):
        previous_header_hash = fail = None
        batch_size = 36
        for start_height in range(0, self.height, batch_size):
            self.io.seek(self.header_size * start_height)
            headers = self.io.read(self.header_size*batch_size)
            if len(headers) % self.header_size != 0:
                headers = headers[:(len(headers) // self.header_size) * self.header_size]
            for header_hash, header in self._iterate_headers(start_height, headers):
                height = header['block_height']
                if height:
                    if header['prev_block_hash'] != previous_header_hash:
                        fail = True
                else:
                    if header_hash != self.genesis_hash:
                        fail = True
                if fail:
                    log.warning("Header file corrupted at height %s, truncating it.", height - 1)
                    self.io.seek(max(0, (height - 1)) * self.header_size, os.SEEK_SET)
                    self.io.truncate()
                    self.io.flush()
                    self._size = None
                    return
                previous_header_hash = header_hash

    @staticmethod
    def get_proof_of_work(header_hash: bytes) -> ArithUint256:
        return ArithUint256(int(b'0x' + header_hash, 16))

    def _iterate_chunks(self, height: int, headers: bytes) -> Iterator[Tuple[int, bytes]]:
        assert len(headers) % self.header_size == 0, f"{len(headers)} {len(headers)%self.header_size}"
        start = 0
        end = (self.chunk_size - height % self.chunk_size) * self.header_size
        while start < end:
            yield height + (start // self.header_size), headers[start:end]
            start = end
            end = min(len(headers), end + self.chunk_size * self.header_size)

    def _iterate_headers(self, height: int, headers: bytes) -> Iterator[Tuple[bytes, dict]]:
        assert len(headers) % self.header_size == 0, len(headers)
        for idx in range(len(headers) // self.header_size):
            start, end = idx * self.header_size, (idx + 1) * self.header_size
            header = headers[start:end]
            yield self.hash_header(header), self.deserialize(height+idx, header)
