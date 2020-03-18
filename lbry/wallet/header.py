import os
import struct
import asyncio
import hashlib
import logging

from io import BytesIO
from contextlib import asynccontextmanager
from typing import Optional, Iterator, Tuple
from binascii import hexlify, unhexlify

from lbry.crypto.hash import sha512, double_sha256, ripemd160
from lbry.wallet.util import ArithUint256


log = logging.getLogger(__name__)


class InvalidHeader(Exception):

    def __init__(self, height, message):
        super().__init__(message)
        self.message = message
        self.height = height


class Headers:

    header_size = 112
    chunk_size = 10**16

    max_target = 0x0000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = b'9c89283ba0f3227f6c03b70216b9f665f0118d5e0fa729cedf4fb34d6a34f463'
    target_timespan = 150
    checkpoint = (600_000, b'100b33ca3d0b86a48f0d6d6f30458a130ecb89d5affefe4afccb134d5a40f4c2')
    first_block_timestamp = 1466646588  # block 1, as 0 is off by a lot
    timestamp_average_offset = 160.6855883050695  # calculated at 733447

    validate_difficulty: bool = True

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
    def serialize(header):
        return b''.join([
            struct.pack('<I', header['version']),
            unhexlify(header['prev_block_hash'])[::-1],
            unhexlify(header['merkle_root'])[::-1],
            unhexlify(header['claim_trie_root'])[::-1],
            struct.pack('<III', header['timestamp'], header['bits'], header['nonce'])
        ])

    @staticmethod
    def deserialize(height, header):
        version, = struct.unpack('<I', header[:4])
        timestamp, bits, nonce = struct.unpack('<III', header[100:112])
        return {
            'version': version,
            'prev_block_hash': hexlify(header[4:36][::-1]),
            'merkle_root': hexlify(header[36:68][::-1]),
            'claim_trie_root': hexlify(header[68:100][::-1]),
            'timestamp': timestamp,
            'bits': bits,
            'nonce': nonce,
            'block_height': height,
        }

    def get_next_chunk_target(self, chunk: int) -> ArithUint256:
        return ArithUint256(self.max_target)

    def get_next_block_target(self, max_target: ArithUint256, previous: Optional[dict],
                              current: Optional[dict]) -> ArithUint256:
        # https://github.com/lbryio/lbrycrd/blob/master/src/lbry.cpp
        if previous is None and current is None:
            return max_target
        if previous is None:
            previous = current
        actual_timespan = current['timestamp'] - previous['timestamp']
        modulated_timespan = self.target_timespan + int((actual_timespan - self.target_timespan) / 8)
        minimum_timespan = self.target_timespan - int(self.target_timespan / 8)  # 150 - 18 = 132
        maximum_timespan = self.target_timespan + int(self.target_timespan / 2)  # 150 + 75 = 225
        clamped_timespan = max(minimum_timespan, min(modulated_timespan, maximum_timespan))
        target = ArithUint256.from_compact(current['bits'])
        new_target = min(max_target, (target * clamped_timespan) / self.target_timespan)
        return new_target

    def __len__(self) -> int:
        if self._size is None:
            self._size = self.io.seek(0, os.SEEK_END) // self.header_size
        return self._size

    def __bool__(self):
        return True

    async def get(self, height) -> dict:
        if isinstance(height, slice):
            raise NotImplementedError("Slicing of header chain has not been implemented yet.")
        if not 0 <= height <= self.height:
            raise IndexError(f"{height} is out of bounds, current height: {self.height}")
        return self.deserialize(height, self.get_raw_header(height))

    def estimated_timestamp(self, height):
        return self.first_block_timestamp + (height * self.timestamp_average_offset)

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
                await self.validate_chunk(height, chunk)
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

    async def validate_chunk(self, height, chunk):
        previous_hash, previous_header, previous_previous_header = None, None, None
        if height > 0:
            previous_header = await self.get(height-1)
            previous_hash = self.hash(height-1)
        if height > 1:
            previous_previous_header = await self.get(height-2)
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

    @classmethod
    def get_proof_of_work(cls, header_hash: bytes):
        return ArithUint256(int(b'0x' + cls.header_hash_to_pow_hash(header_hash), 16))

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

    @staticmethod
    def header_hash_to_pow_hash(header_hash: bytes):
        header_hash_bytes = unhexlify(header_hash)[::-1]
        h = sha512(header_hash_bytes)
        pow_hash = double_sha256(
            ripemd160(h[:len(h) // 2]) +
            ripemd160(h[len(h) // 2:])
        )
        return hexlify(pow_hash[::-1])


class UnvalidatedHeaders(Headers):
    validate_difficulty = False
    max_target = 0x7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = b'6e3fcf1299d4ec5d79c3a4c91d624a4acf9e2e173d95a1a0504f677669687556'
