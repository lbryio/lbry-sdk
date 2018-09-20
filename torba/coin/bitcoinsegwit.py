__node_daemon__ = 'bitcoind'
__node_cli__ = 'bitcoin-cli'
__node_bin__ = 'bitcoin-0.16.3/bin'
__node_url__ = (
    'https://bitcoin.org/bin/bitcoin-core-0.16.3/bitcoin-0.16.3-x86_64-linux-gnu.tar.gz'
)
__electrumx__ = 'electrumx.lib.coins.BitcoinSegwitRegtest'

import struct
from typing import Optional
from binascii import hexlify, unhexlify
from torba.baseledger import BaseLedger
from torba.baseheader import BaseHeaders, ArithUint256


class MainHeaders(BaseHeaders):
    header_size = 80
    chunk_size = 2016
    max_target = 0x00000000ffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash: Optional[bytes] = b'000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f'
    target_timespan = 14 * 24 * 60 * 60

    @staticmethod
    def serialize(header: dict) -> bytes:
        return b''.join([
            struct.pack('<I', header['version']),
            unhexlify(header['prev_block_hash'])[::-1],
            unhexlify(header['merkle_root'])[::-1],
            struct.pack('<III', header['timestamp'], header['bits'], header['nonce'])
        ])

    @staticmethod
    def deserialize(height, header):
        version, = struct.unpack('<I', header[:4])
        timestamp, bits, nonce = struct.unpack('<III', header[68:80])
        return {
            'block_height': height,
            'version': version,
            'prev_block_hash': hexlify(header[4:36][::-1]),
            'merkle_root': hexlify(header[36:68][::-1]),
            'timestamp': timestamp,
            'bits': bits,
            'nonce': nonce
        }

    def get_next_chunk_target(self, chunk: int) -> ArithUint256:
        if chunk == -1:
            return ArithUint256(self.max_target)
        previous = self[chunk * 2016]
        current = self[chunk * 2016 + 2015]
        actual_timespan = current['timestamp'] - previous['timestamp']
        actual_timespan = max(actual_timespan, int(self.target_timespan / 4))
        actual_timespan = min(actual_timespan, self.target_timespan * 4)
        target = ArithUint256.from_compact(current['bits'])
        new_target = min(ArithUint256(self.max_target), (target * actual_timespan) / self.target_timespan)
        return new_target


class MainNetLedger(BaseLedger):
    name = 'BitcoinSegwit'
    symbol = 'BTC'
    network_name = 'mainnet'
    headers_class = MainHeaders

    pubkey_address_prefix = bytes((0,))
    script_address_prefix = bytes((5,))
    extended_public_key_prefix = unhexlify('0488b21e')
    extended_private_key_prefix = unhexlify('0488ade4')

    default_fee_per_byte = 50


class UnverifiedHeaders(MainHeaders):
    max_target = 0x7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = None
    validate_difficulty = False


class RegTestLedger(MainNetLedger):
    network_name = 'regtest'
    headers_class = UnverifiedHeaders

    pubkey_address_prefix = bytes((111,))
    script_address_prefix = bytes((196,))
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')
