import struct
from lbry.crypto.hash import double_sha256
from lbry.wallet.transaction import Transaction
from lbry.wallet.bcd_data_stream import BCDataStream


ZERO_BLOCK = bytes((0,)*32)


class Block:

    __slots__ = (
        'version', 'block_hash', 'prev_block_hash',
        'merkle_root', 'claim_trie_root', 'timestamp',
        'bits', 'nonce', 'txs'
    )

    def __init__(self, stream):
        stream.read_uint32()  # block size
        header = stream.data.read(112)
        version, = struct.unpack('<I', header[:4])
        timestamp, bits, nonce = struct.unpack('<III', header[100:112])
        self.version = version
        self.block_hash = double_sha256(header)
        self.prev_block_hash = header[4:36]
        self.merkle_root = header[36:68]
        self.claim_trie_root = header[68:100][::-1]
        self.timestamp = timestamp
        self.bits = bits
        self.nonce = nonce
        tx_count = stream.read_compact_size()
        self.txs = [
            Transaction(position=i)._deserialize(stream)
            for i in range(tx_count)
        ]

    @property
    def is_first_block(self):
        return self.prev_block_hash == ZERO_BLOCK


def read_blocks(block_file):
    with open(block_file, 'rb') as fp:
        stream = BCDataStream(fp=fp)
        #while stream.read_uint32() == 4054508794:
        while stream.read_uint32() == 3517637882:
            yield Block(stream)
