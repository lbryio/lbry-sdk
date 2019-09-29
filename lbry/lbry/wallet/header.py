import struct
from typing import Optional
from binascii import hexlify, unhexlify

from torba.client.baseheader import BaseHeaders
from torba.client.util import ArithUint256
from torba.client.hash import sha512, double_sha256, ripemd160


class Headers(BaseHeaders):

    header_size = 112
    chunk_size = 10**16

    max_target = 0x0000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = b'9c89283ba0f3227f6c03b70216b9f665f0118d5e0fa729cedf4fb34d6a34f463'
    target_timespan = 150
    checkpoint = (600_000, b'100b33ca3d0b86a48f0d6d6f30458a130ecb89d5affefe4afccb134d5a40f4c2')

    @property
    def claim_trie_root(self):
        return self[self.height]['claim_trie_root']

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

    @classmethod
    def get_proof_of_work(cls, header_hash: bytes):
        return super().get_proof_of_work(
            cls.header_hash_to_pow_hash(header_hash)
        )

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
