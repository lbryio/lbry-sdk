import struct
from six import int2byte
from binascii import unhexlify

from torba.baseledger import BaseLedger
from torba.baseheader import BaseHeaders, _ArithUint256
from torba.util import int_to_hex, rev_hex, hash_encode

from .network import Network
from .database import WalletDatabase
from .transaction import Transaction


class Headers(BaseHeaders):

    header_size = 112

    @staticmethod
    def _serialize(header):
        return b''.join([
            int_to_hex(header['version'], 4),
            rev_hex(header['prev_block_hash']),
            rev_hex(header['merkle_root']),
            rev_hex(header['claim_trie_root']),
            int_to_hex(int(header['timestamp']), 4),
            int_to_hex(int(header['bits']), 4),
            int_to_hex(int(header['nonce']), 4)
        ])

    @staticmethod
    def _deserialize(height, header):
        version, = struct.unpack('<I', header[:4])
        timestamp, bits, nonce = struct.unpack('<III', header[100:112])
        return {
            'version': version,
            'prev_block_hash': hash_encode(header[4:36]),
            'merkle_root': hash_encode(header[36:68]),
            'claim_trie_root': hash_encode(header[68:100]),
            'timestamp': timestamp,
            'bits': bits,
            'nonce': nonce,
            'block_height': height,
        }

    def _calculate_next_work_required(self, height, first, last):
        """ See: lbrycrd/src/lbry.cpp """

        if height == 0:
            return self.ledger.genesis_bits, self.ledger.max_target

        if self.verify_bits_to_target:
            bits = last['bits']
            bitsN = (bits >> 24) & 0xff
            assert 0x03 <= bitsN <= 0x1f, \
                "First part of bits should be in [0x03, 0x1d], but it was {}".format(hex(bitsN))
            bitsBase = bits & 0xffffff
            assert 0x8000 <= bitsBase <= 0x7fffff, \
                "Second part of bits should be in [0x8000, 0x7fffff] but it was {}".format(bitsBase)

        # new target
        retargetTimespan = self.ledger.target_timespan
        nActualTimespan = last['timestamp'] - first['timestamp']

        nModulatedTimespan = retargetTimespan + (nActualTimespan - retargetTimespan) // 8

        nMinTimespan = retargetTimespan - (retargetTimespan // 8)
        nMaxTimespan = retargetTimespan + (retargetTimespan // 2)

        # Limit adjustment step
        if nModulatedTimespan < nMinTimespan:
            nModulatedTimespan = nMinTimespan
        elif nModulatedTimespan > nMaxTimespan:
            nModulatedTimespan = nMaxTimespan

        # Retarget
        bnPowLimit = _ArithUint256(self.ledger.max_target)
        bnNew = _ArithUint256.SetCompact(last['bits'])
        bnNew *= nModulatedTimespan
        bnNew //= nModulatedTimespan
        if bnNew > bnPowLimit:
            bnNew = bnPowLimit

        return bnNew.GetCompact(), bnNew._value


class MainNetLedger(BaseLedger):
    name = 'LBRY Credits'
    symbol = 'LBC'
    network_name = 'mainnet'

    database_class = WalletDatabase
    headers_class = Headers
    network_class = Network
    transaction_class = Transaction

    secret_prefix = int2byte(0x1c)
    pubkey_address_prefix = int2byte(0x55)
    script_address_prefix = int2byte(0x7a)
    extended_public_key_prefix = unhexlify('0488b21e')
    extended_private_key_prefix = unhexlify('0488ade4')

    max_target = 0x0000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = '9c89283ba0f3227f6c03b70216b9f665f0118d5e0fa729cedf4fb34d6a34f463'
    genesis_bits = 0x1f00ffff
    target_timespan = 150

    default_fee_per_byte = 50
    default_fee_per_name_char = 200000

    def __init__(self, *args, **kwargs):
        super(MainNetLedger, self).__init__(*args, **kwargs)
        self.fee_per_name_char = self.config.get('fee_per_name_char', self.default_fee_per_name_char)

    def get_transaction_base_fee(self, tx):
        """ Fee for the transaction header and all outputs; without inputs. """
        return max(
            super(MainNetLedger, self).get_transaction_base_fee(tx),
            self.get_transaction_claim_name_fee(tx)
        )

    def get_transaction_claim_name_fee(self, tx):
        fee = 0
        for output in tx.outputs:
            if output.script.is_claim_name:
                fee += len(output.script.values['claim_name']) * self.fee_per_name_char
        return fee

    def resolve(self, *uris):
        return self.network.get_values_for_uris(
            self.headers.hash(), *uris
        )


class TestNetLedger(MainNetLedger):
    network_name = 'testnet'
    pubkey_address_prefix = int2byte(111)
    script_address_prefix = int2byte(196)
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')


class UnverifiedHeaders(Headers):
    verify_bits_to_target = False


class RegTestLedger(MainNetLedger):
    network_name = 'regtest'
    headers_class = UnverifiedHeaders
    pubkey_address_prefix = int2byte(111)
    script_address_prefix = int2byte(196)
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')

    max_target = 0x7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = '6e3fcf1299d4ec5d79c3a4c91d624a4acf9e2e173d95a1a0504f677669687556'
    genesis_bits = 0x207fffff
    target_timespan = 1
