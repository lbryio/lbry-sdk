import os
import asyncio
import logging
from io import BytesIO
from typing import Optional, Iterator, Tuple
from binascii import hexlify

from torba.util import ArithUint256
from torba.hash import double_sha256

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

    def __init__(self, path) -> None:
        if path == ':memory:':
            self.io = BytesIO()
        self.path = path
        self._size: Optional[int] = None
        self._header_connect_lock = asyncio.Lock()

    async def open(self):
        if self.path != ':memory:':
            self.io = open(self.path, 'a+b')

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
        assert not isinstance(height, slice), \
            "Slicing of header chain has not been implemented yet."
        return self.deserialize(height, self.get_raw_header(height))

    def get_raw_header(self, height) -> bytes:
        self.io.seek(height * self.header_size, os.SEEK_SET)
        return self.io.read(self.header_size)

    @property
    def height(self) -> int:
        return len(self)-1

    def hash(self, height=None) -> bytes:
        return self.hash_header(
            self.get_raw_header(height if height is not None else self.height)
        )

    @staticmethod
    def hash_header(header: bytes) -> bytes:
        if header is None:
            return b'0' * 64
        return hexlify(double_sha256(header)[::-1])

    async def connect(self, start: int, headers: bytes) -> int:
        added = 0
        bail = False
        # TODO: switch to get_running_loop() after depricating python 3.6 support
        #loop = asyncio.get_running_loop()
        loop = asyncio.get_event_loop()
        async with self._header_connect_lock:
            for height, chunk in self._iterate_chunks(start, headers):
                try:
                    # validate_chunk() is CPU bound and reads previous chunks from file system
                    await loop.run_in_executor(None, self.validate_chunk, height, chunk)
                except InvalidHeader as e:
                    bail = True
                    chunk = chunk[:(height-e.height+1)*self.header_size]
                written = 0
                if chunk:
                    self.io.seek(height * self.header_size, os.SEEK_SET)
                    written = self.io.write(chunk) // self.header_size
                    self.io.truncate()
                    # .seek()/.write()/.truncate() might also .flush() when needed
                    # the goal here is mainly to ensure we're definitely flush()'ing
                    await loop.run_in_executor(None, self.io.flush)
                    self._size = None
                added += written
                if bail:
                    break
        return added

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
                    height, "genesis header doesn't match: {} vs expected {}".format(
                        current_hash.decode(), self.genesis_hash.decode())
                )
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
                    height, "insufficient proof of work: {} vs target {}".format(
                        proof_of_work.value, target.value)
                )

    @staticmethod
    def get_proof_of_work(header_hash: bytes) -> ArithUint256:
        return ArithUint256(int(b'0x' + header_hash, 16))

    def _iterate_chunks(self, height: int, headers: bytes) -> Iterator[Tuple[int, bytes]]:
        assert len(headers) % self.header_size == 0
        start = 0
        end = (self.chunk_size - height % self.chunk_size) * self.header_size
        while start < end:
            yield height + (start // self.header_size), headers[start:end]
            start = end
            end = min(len(headers), end + self.chunk_size * self.header_size)

    def _iterate_headers(self, height: int, headers: bytes) -> Iterator[Tuple[bytes, dict]]:
        assert len(headers) % self.header_size == 0
        for idx in range(len(headers) // self.header_size):
            start, end = idx * self.header_size, (idx + 1) * self.header_size
            header = headers[start:end]
            yield self.hash_header(header), self.deserialize(height+idx, header)
