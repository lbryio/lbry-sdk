import struct
from typing import NamedTuple, List, Tuple

from chiabip158 import PyBIP158  # pylint: disable=no-name-in-module

from lbry.crypto.hash import double_sha256
from lbry.blockchain.transaction import Transaction
from lbry.blockchain.bcd_data_stream import BCDataStream


ZERO_BLOCK = bytes((0,)*32)


def create_block_filter(address_hashes: List[bytearray]) -> bytes:
    return bytes(PyBIP158(address_hashes).GetEncoded())


def get_block_filter(block_filter: bytes) -> PyBIP158:
    return PyBIP158(bytearray(block_filter))


class Block(NamedTuple):
    height: int
    version: int
    file_number: int
    block_hash: bytes
    prev_block_hash: bytes
    merkle_root: bytes
    claim_trie_root: bytes
    timestamp: int
    bits: int
    nonce: int
    txs: List[Transaction]

    @staticmethod
    def from_data_stream(stream: BCDataStream, height: int, file_number: int):
        header = stream.data.read(112)
        version, = struct.unpack('<I', header[:4])
        timestamp, bits, nonce = struct.unpack('<III', header[100:112])
        tx_count = stream.read_compact_size()
        return Block(
            height=height,
            version=version,
            file_number=file_number,
            block_hash=double_sha256(header),
            prev_block_hash=header[4:36],
            merkle_root=header[36:68],
            claim_trie_root=header[68:100][::-1],
            timestamp=timestamp,
            bits=bits,
            nonce=nonce,
            txs=[
                Transaction(height=height, position=i, timestamp=timestamp).deserialize(stream)
                for i in range(tx_count)
            ]
        )

    @property
    def is_first_block(self):
        return self.prev_block_hash == ZERO_BLOCK
