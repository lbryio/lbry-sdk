import base64
import os
import struct
import asyncio
import logging
import zlib
from concurrent.futures.thread import ThreadPoolExecutor

from io import BytesIO
from typing import Optional, Iterator, Tuple, Callable
from binascii import hexlify, unhexlify

from lbry.crypto.hash import sha512, double_sha256, ripemd160
from lbry.wallet.util import ArithUint256
from .checkpoints import HASHES


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
    checkpoints = HASHES
    first_block_timestamp = 1466646588  # block 1, as 0 is off by a lot
    timestamp_average_offset = 160.6855883050695  # calculated at 733447

    validate_difficulty: bool = True

    def __init__(self, path) -> None:
        if path == ':memory:':
            self.io = BytesIO()
        self.path = path
        self._size: Optional[int] = None
        self.chunk_getter: Optional[Callable] = None
        self.executor = ThreadPoolExecutor(1)

    async def open(self):
        if self.path != ':memory:':
            if not os.path.exists(self.path):
                self.io = open(self.path, 'w+b')
            else:
                self.io = open(self.path, 'r+b')
        self._size = self.io.seek(0, os.SEEK_END) // self.header_size

    async def close(self):
        self.executor.shutdown()
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
        return self._size

    def __bool__(self):
        return True

    async def get(self, height) -> dict:
        if isinstance(height, slice):
            raise NotImplementedError("Slicing of header chain has not been implemented yet.")
        try:
            return self.deserialize(height, await self.get_raw_header(height))
        except struct.error:
            raise IndexError(f"failed to get {height}, at {len(self)}")

    def estimated_timestamp(self, height):
        return self.first_block_timestamp + (height * self.timestamp_average_offset)

    async def get_raw_header(self, height) -> bytes:
        if self.chunk_getter:
            await self.ensure_chunk_at(height)
        if not 0 <= height <= self.height:
            raise IndexError(f"{height} is out of bounds, current height: {self.height}")
        return await asyncio.get_running_loop().run_in_executor(self.executor, self._read, height)

    def _read(self, height, count=1):
        self.io.seek(height * self.header_size, os.SEEK_SET)
        return self.io.read(self.header_size * count)

    def chunk_hash(self, start, count):
        self.io.seek(start * self.header_size, os.SEEK_SET)
        return self.hash_header(self.io.read(count * self.header_size)).decode()

    async def ensure_tip(self):
        if self.checkpoints:
            await self.ensure_chunk_at(max(self.checkpoints.keys()))

    async def ensure_chunk_at(self, height):
        if await self.has_header(height):
            log.info("has header %s", height)
            return
        log.info("on-demand fetching height %s", height)
        start = (height // 1000) * 1000
        headers = await self.chunk_getter(start)  # pylint: disable=not-callable
        chunk = (
            zlib.decompress(base64.b64decode(headers['base64']), wbits=-15, bufsize=600_000)
        )
        chunk_hash = self.hash_header(chunk).decode()
        if self.checkpoints.get(start) == chunk_hash:
            return await asyncio.get_running_loop().run_in_executor(self.executor, self._write, start, chunk)
        elif start not in self.checkpoints:
            return  # todo: fixme
        raise Exception(
            f"Checkpoint mismatch at height {start}. Expected {self.checkpoints[start]}, but got {chunk_hash} instead."
        )

    async def has_header(self, height):
        def _has_header(height):
            empty = '56944c5d3f98413ef45cf54545538103cc9f298e0575820ad3591376e2e0f65d'
            all_zeroes = '789d737d4f448e554b318c94063bbfa63e9ccda6e208f5648ca76ee68896557b'
            return self.chunk_hash(height, 1) not in (empty, all_zeroes)
        return await asyncio.get_running_loop().run_in_executor(self.executor, _has_header, height)

    @property
    def height(self) -> int:
        return len(self)-1

    @property
    def bytes_size(self):
        return len(self) * self.header_size

    async def hash(self, height=None) -> bytes:
        return self.hash_header(
            await self.get_raw_header(height if height is not None else self.height)
        )

    @staticmethod
    def hash_header(header: bytes) -> bytes:
        if header is None:
            return b'0' * 64
        return hexlify(double_sha256(header)[::-1])

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
            if chunk:
                added += await asyncio.get_running_loop().run_in_executor(self.executor, self._write, height, chunk)
            if bail:
                break
        return added

    def _write(self, height, verified_chunk):
        self.io.seek(height * self.header_size, os.SEEK_SET)
        written = self.io.write(verified_chunk) // self.header_size
        # self.io.truncate()
        # .seek()/.write()/.truncate() might also .flush() when needed
        # the goal here is mainly to ensure we're definitely flush()'ing
        self.io.flush()
        self._size = self.io.tell() // self.header_size
        return written

    async def validate_chunk(self, height, chunk):
        previous_hash, previous_header, previous_previous_header = None, None, None
        if height > 0:
            raw = await self.get_raw_header(height-1)
            previous_header = self.deserialize(height-1, raw)
            previous_hash = self.hash_header(raw)
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
            headers = await asyncio.get_running_loop().run_in_executor(
                self.executor, self._read, start_height, batch_size
            )
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
                    def __truncate(at_height):
                        self.io.seek(max(0, (at_height - 1)) * self.header_size, os.SEEK_SET)
                        self.io.truncate()
                        self.io.flush()
                        self._size = self.io.seek(0, os.SEEK_END) // self.header_size
                    return await asyncio.get_running_loop().run_in_executor(self.executor, __truncate, height)
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
    checkpoints = {}
