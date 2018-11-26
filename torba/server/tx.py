# Copyright (c) 2016-2017, Neil Booth
# Copyright (c) 2017, the ElectrumX authors
#
# All rights reserved.
#
# The MIT License (MIT)
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
# and warranty status of this software.

'''Transaction-related classes and functions.'''

from collections import namedtuple

from torba.server.hash import sha256, double_sha256, hash_to_hex_str
from torba.server.script import OpCodes
from torba.server.util import (
    unpack_le_int32_from, unpack_le_int64_from, unpack_le_uint16_from,
    unpack_le_uint32_from, unpack_le_uint64_from, pack_le_int32, pack_varint,
    pack_le_uint32, pack_le_int64, pack_varbytes,
)

ZERO = bytes(32)
MINUS_1 = 4294967295


class Tx(namedtuple("Tx", "version inputs outputs locktime")):
    '''Class representing a transaction.'''

    def serialize(self):
        return b''.join((
            pack_le_int32(self.version),
            pack_varint(len(self.inputs)),
            b''.join(tx_in.serialize() for tx_in in self.inputs),
            pack_varint(len(self.outputs)),
            b''.join(tx_out.serialize() for tx_out in self.outputs),
            pack_le_uint32(self.locktime)
        ))


class TxInput(namedtuple("TxInput", "prev_hash prev_idx script sequence")):
    '''Class representing a transaction input.'''
    def __str__(self):
        script = self.script.hex()
        prev_hash = hash_to_hex_str(self.prev_hash)
        return ("Input({}, {:d}, script={}, sequence={:d})"
                .format(prev_hash, self.prev_idx, script, self.sequence))

    def is_generation(self):
        '''Test if an input is generation/coinbase like'''
        return self.prev_idx == MINUS_1 and self.prev_hash == ZERO

    def serialize(self):
        return b''.join((
            self.prev_hash,
            pack_le_uint32(self.prev_idx),
            pack_varbytes(self.script),
            pack_le_uint32(self.sequence),
        ))


class TxOutput(namedtuple("TxOutput", "value pk_script")):

    def serialize(self):
        return b''.join((
            pack_le_int64(self.value),
            pack_varbytes(self.pk_script),
        ))


class Deserializer:
    '''Deserializes blocks into transactions.

    External entry points are read_tx(), read_tx_and_hash(),
    read_tx_and_vsize() and read_block().

    This code is performance sensitive as it is executed 100s of
    millions of times during sync.
    '''

    TX_HASH_FN = staticmethod(double_sha256)

    def __init__(self, binary, start=0):
        assert isinstance(binary, bytes)
        self.binary = binary
        self.binary_length = len(binary)
        self.cursor = start

    def read_tx(self):
        '''Return a deserialized transaction.'''
        return Tx(
            self._read_le_int32(),  # version
            self._read_inputs(),    # inputs
            self._read_outputs(),   # outputs
            self._read_le_uint32()  # locktime
        )

    def read_tx_and_hash(self):
        '''Return a (deserialized TX, tx_hash) pair.

        The hash needs to be reversed for human display; for efficiency
        we process it in the natural serialized order.
        '''
        start = self.cursor
        return self.read_tx(), self.TX_HASH_FN(self.binary[start:self.cursor])

    def read_tx_and_vsize(self):
        '''Return a (deserialized TX, vsize) pair.'''
        return self.read_tx(), self.binary_length

    def read_tx_block(self):
        '''Returns a list of (deserialized_tx, tx_hash) pairs.'''
        read = self.read_tx_and_hash
        # Some coins have excess data beyond the end of the transactions
        return [read() for _ in range(self._read_varint())]

    def _read_inputs(self):
        read_input = self._read_input
        return [read_input() for i in range(self._read_varint())]

    def _read_input(self):
        return TxInput(
            self._read_nbytes(32),   # prev_hash
            self._read_le_uint32(),  # prev_idx
            self._read_varbytes(),   # script
            self._read_le_uint32()   # sequence
        )

    def _read_outputs(self):
        read_output = self._read_output
        return [read_output() for i in range(self._read_varint())]

    def _read_output(self):
        return TxOutput(
            self._read_le_int64(),  # value
            self._read_varbytes(),  # pk_script
        )

    def _read_byte(self):
        cursor = self.cursor
        self.cursor += 1
        return self.binary[cursor]

    def _read_nbytes(self, n):
        cursor = self.cursor
        self.cursor = end = cursor + n
        assert self.binary_length >= end
        return self.binary[cursor:end]

    def _read_varbytes(self):
        return self._read_nbytes(self._read_varint())

    def _read_varint(self):
        n = self.binary[self.cursor]
        self.cursor += 1
        if n < 253:
            return n
        if n == 253:
            return self._read_le_uint16()
        if n == 254:
            return self._read_le_uint32()
        return self._read_le_uint64()

    def _read_le_int32(self):
        result, = unpack_le_int32_from(self.binary, self.cursor)
        self.cursor += 4
        return result

    def _read_le_int64(self):
        result, = unpack_le_int64_from(self.binary, self.cursor)
        self.cursor += 8
        return result

    def _read_le_uint16(self):
        result, = unpack_le_uint16_from(self.binary, self.cursor)
        self.cursor += 2
        return result

    def _read_le_uint32(self):
        result, = unpack_le_uint32_from(self.binary, self.cursor)
        self.cursor += 4
        return result

    def _read_le_uint64(self):
        result, = unpack_le_uint64_from(self.binary, self.cursor)
        self.cursor += 8
        return result


class TxSegWit(namedtuple("Tx", "version marker flag inputs outputs "
                          "witness locktime")):
    '''Class representing a SegWit transaction.'''


class DeserializerSegWit(Deserializer):

    # https://bitcoincore.org/en/segwit_wallet_dev/#transaction-serialization

    def _read_witness(self, fields):
        read_witness_field = self._read_witness_field
        return [read_witness_field() for i in range(fields)]

    def _read_witness_field(self):
        read_varbytes = self._read_varbytes
        return [read_varbytes() for i in range(self._read_varint())]

    def _read_tx_parts(self):
        '''Return a (deserialized TX, tx_hash, vsize) tuple.'''
        start = self.cursor
        marker = self.binary[self.cursor + 4]
        if marker:
            tx = super().read_tx()
            tx_hash = self.TX_HASH_FN(self.binary[start:self.cursor])
            return tx, tx_hash, self.binary_length

        # Ugh, this is nasty.
        version = self._read_le_int32()
        orig_ser = self.binary[start:self.cursor]

        marker = self._read_byte()
        flag = self._read_byte()

        start = self.cursor
        inputs = self._read_inputs()
        outputs = self._read_outputs()
        orig_ser += self.binary[start:self.cursor]

        base_size = self.cursor - start
        witness = self._read_witness(len(inputs))

        start = self.cursor
        locktime = self._read_le_uint32()
        orig_ser += self.binary[start:self.cursor]
        vsize = (3 * base_size + self.binary_length) // 4

        return TxSegWit(version, marker, flag, inputs, outputs, witness,
                        locktime), self.TX_HASH_FN(orig_ser), vsize

    def read_tx(self):
        return self._read_tx_parts()[0]

    def read_tx_and_hash(self):
        tx, tx_hash, vsize = self._read_tx_parts()
        return tx, tx_hash

    def read_tx_and_vsize(self):
        tx, tx_hash, vsize = self._read_tx_parts()
        return tx, vsize


class DeserializerAuxPow(Deserializer):
    VERSION_AUXPOW = (1 << 8)

    def read_header(self, height, static_header_size):
        '''Return the AuxPow block header bytes'''
        start = self.cursor
        version = self._read_le_uint32()
        if version & self.VERSION_AUXPOW:
            # We are going to calculate the block size then read it as bytes
            self.cursor = start
            self.cursor += static_header_size  # Block normal header
            self.read_tx()  # AuxPow transaction
            self.cursor += 32  # Parent block hash
            merkle_size = self._read_varint()
            self.cursor += 32 * merkle_size  # Merkle branch
            self.cursor += 4  # Index
            merkle_size = self._read_varint()
            self.cursor += 32 * merkle_size  # Chain merkle branch
            self.cursor += 4  # Chain index
            self.cursor += 80  # Parent block header
            header_end = self.cursor
        else:
            header_end = static_header_size
        self.cursor = start
        return self._read_nbytes(header_end)


class DeserializerAuxPowSegWit(DeserializerSegWit, DeserializerAuxPow):
    pass


class DeserializerEquihash(Deserializer):
    def read_header(self, height, static_header_size):
        '''Return the block header bytes'''
        start = self.cursor
        # We are going to calculate the block size then read it as bytes
        self.cursor += static_header_size
        solution_size = self._read_varint()
        self.cursor += solution_size
        header_end = self.cursor
        self.cursor = start
        return self._read_nbytes(header_end)


class DeserializerEquihashSegWit(DeserializerSegWit, DeserializerEquihash):
    pass


class TxJoinSplit(namedtuple("Tx", "version inputs outputs locktime")):
    '''Class representing a JoinSplit transaction.'''


class DeserializerZcash(DeserializerEquihash):
    def read_tx(self):
        header = self._read_le_uint32()
        overwintered = ((header >> 31) == 1)
        if overwintered:
            version = header & 0x7fffffff
            self.cursor += 4  # versionGroupId
        else:
            version = header

        is_overwinter_v3 = version == 3
        is_sapling_v4 = version == 4

        base_tx = TxJoinSplit(
            version,
            self._read_inputs(),    # inputs
            self._read_outputs(),   # outputs
            self._read_le_uint32()  # locktime
        )

        if is_overwinter_v3 or is_sapling_v4:
            self.cursor += 4  # expiryHeight

        has_shielded = False
        if is_sapling_v4:
            self.cursor += 8  # valueBalance
            shielded_spend_size = self._read_varint()
            self.cursor += shielded_spend_size * 384  # vShieldedSpend
            shielded_output_size = self._read_varint()
            self.cursor += shielded_output_size * 948  # vShieldedOutput
            has_shielded = shielded_spend_size > 0 or shielded_output_size > 0

        if base_tx.version >= 2:
            joinsplit_size = self._read_varint()
            if joinsplit_size > 0:
                joinsplit_desc_len = 1506 + (192 if is_sapling_v4 else 296)
                # JSDescription
                self.cursor += joinsplit_size * joinsplit_desc_len
                self.cursor += 32  # joinSplitPubKey
                self.cursor += 64  # joinSplitSig

        if is_sapling_v4 and has_shielded:
            self.cursor += 64  # bindingSig

        return base_tx


class TxTime(namedtuple("Tx", "version time inputs outputs locktime")):
    '''Class representing transaction that has a time field.'''


class DeserializerTxTime(Deserializer):
    def read_tx(self):
        return TxTime(
            self._read_le_int32(),   # version
            self._read_le_uint32(),  # time
            self._read_inputs(),     # inputs
            self._read_outputs(),    # outputs
            self._read_le_uint32(),  # locktime
        )


class DeserializerReddcoin(Deserializer):
    def read_tx(self):
        version = self._read_le_int32()
        inputs = self._read_inputs()
        outputs = self._read_outputs()
        locktime = self._read_le_uint32()
        if version > 1:
            time = self._read_le_uint32()
        else:
            time = 0

        return TxTime(version, time, inputs, outputs, locktime)


class DeserializerTxTimeAuxPow(DeserializerTxTime):
    VERSION_AUXPOW = (1 << 8)

    def is_merged_block(self):
        start = self.cursor
        self.cursor = 0
        version = self._read_le_uint32()
        self.cursor = start
        if version & self.VERSION_AUXPOW:
            return True
        return False

    def read_header(self, height, static_header_size):
        '''Return the AuxPow block header bytes'''
        start = self.cursor
        version = self._read_le_uint32()
        if version & self.VERSION_AUXPOW:
            # We are going to calculate the block size then read it as bytes
            self.cursor = start
            self.cursor += static_header_size  # Block normal header
            self.read_tx()  # AuxPow transaction
            self.cursor += 32  # Parent block hash
            merkle_size = self._read_varint()
            self.cursor += 32 * merkle_size  # Merkle branch
            self.cursor += 4  # Index
            merkle_size = self._read_varint()
            self.cursor += 32 * merkle_size  # Chain merkle branch
            self.cursor += 4  # Chain index
            self.cursor += 80  # Parent block header
            header_end = self.cursor
        else:
            header_end = static_header_size
        self.cursor = start
        return self._read_nbytes(header_end)


class DeserializerBitcoinAtom(DeserializerSegWit):
    FORK_BLOCK_HEIGHT = 505888

    def read_header(self, height, static_header_size):
        '''Return the block header bytes'''
        header_len = static_header_size
        if height >= self.FORK_BLOCK_HEIGHT:
            header_len += 4  # flags
        return self._read_nbytes(header_len)


class DeserializerGroestlcoin(DeserializerSegWit):
    TX_HASH_FN = staticmethod(sha256)


class TxInputTokenPay(TxInput):
    '''Class representing a TokenPay transaction input.'''

    OP_ANON_MARKER = 0xb9
    # 2byte marker (cpubkey + sigc + sigr)
    MIN_ANON_IN_SIZE = 2 + (33 + 32 + 32)

    def _is_anon_input(self):
        return (len(self.script) >= self.MIN_ANON_IN_SIZE and
                self.script[0] == OpCodes.OP_RETURN and
                self.script[1] == self.OP_ANON_MARKER)

    def is_generation(self):
        # Transactions comming in from stealth addresses are seen by
        # the blockchain as newly minted coins. The reverse, where coins
        # are sent TO a stealth address, are seen by the blockchain as
        # a coin burn.
        if self._is_anon_input():
            return True
        return super(TxInputTokenPay, self).is_generation()


class TxInputTokenPayStealth(
        namedtuple("TxInput", "keyimage ringsize script sequence")):
    '''Class representing a TokenPay stealth transaction input.'''

    def __str__(self):
        script = self.script.hex()
        keyimage = bytes(self.keyimage).hex()
        return ("Input({}, {:d}, script={}, sequence={:d})"
                .format(keyimage, self.ringsize[1], script, self.sequence))

    def is_generation(self):
        return True

    def serialize(self):
        return b''.join((
            self.keyimage,
            self.ringsize,
            pack_varbytes(self.script),
            pack_le_uint32(self.sequence),
        ))


class DeserializerTokenPay(DeserializerTxTime):

    def _read_input(self):
        txin = TxInputTokenPay(
            self._read_nbytes(32),   # prev_hash
            self._read_le_uint32(),  # prev_idx
            self._read_varbytes(),   # script
            self._read_le_uint32(),  # sequence
        )
        if txin._is_anon_input():
            # Not sure if this is actually needed, and seems
            # extra work for no immediate benefit, but it at
            # least correctly represents a stealth input
            raw = txin.serialize()
            deserializer = Deserializer(raw)
            txin = TxInputTokenPayStealth(
                deserializer._read_nbytes(33),  # keyimage
                deserializer._read_nbytes(3),   # ringsize
                deserializer._read_varbytes(),  # script
                deserializer._read_le_uint32()  # sequence
            )
        return txin


# Decred
class TxInputDcr(namedtuple("TxInput", "prev_hash prev_idx tree sequence")):
    '''Class representing a Decred transaction input.'''

    def __str__(self):
        prev_hash = hash_to_hex_str(self.prev_hash)
        return ("Input({}, {:d}, tree={}, sequence={:d})"
                .format(prev_hash, self.prev_idx, self.tree, self.sequence))

    def is_generation(self):
        '''Test if an input is generation/coinbase like'''
        return self.prev_idx == MINUS_1 and self.prev_hash == ZERO


class TxOutputDcr(namedtuple("TxOutput", "value version pk_script")):
    '''Class representing a Decred transaction output.'''
    pass


class TxDcr(namedtuple("Tx", "version inputs outputs locktime expiry "
                             "witness")):
    '''Class representing a Decred  transaction.'''


class DeserializerDecred(Deserializer):
    @staticmethod
    def blake256(data):
        from blake256.blake256 import blake_hash
        return blake_hash(data)

    @staticmethod
    def blake256d(data):
        from blake256.blake256 import blake_hash
        return blake_hash(blake_hash(data))

    def read_tx(self):
        return self._read_tx_parts(produce_hash=False)[0]

    def read_tx_and_hash(self):
        tx, tx_hash, vsize = self._read_tx_parts()
        return tx, tx_hash

    def read_tx_and_vsize(self):
        tx, tx_hash, vsize = self._read_tx_parts(produce_hash=False)
        return tx, vsize

    def read_tx_block(self):
        '''Returns a list of (deserialized_tx, tx_hash) pairs.'''
        read = self.read_tx_and_hash
        txs = [read() for _ in range(self._read_varint())]
        stxs = [read() for _ in range(self._read_varint())]
        return txs + stxs

    def read_tx_tree(self):
        '''Returns a list of deserialized_tx without tx hashes.'''
        read_tx = self.read_tx
        return [read_tx() for _ in range(self._read_varint())]

    def _read_input(self):
        return TxInputDcr(
            self._read_nbytes(32),   # prev_hash
            self._read_le_uint32(),  # prev_idx
            self._read_byte(),       # tree
            self._read_le_uint32(),  # sequence
        )

    def _read_output(self):
        return TxOutputDcr(
            self._read_le_int64(),  # value
            self._read_le_uint16(),  # version
            self._read_varbytes(),  # pk_script
        )

    def _read_witness(self, fields):
        read_witness_field = self._read_witness_field
        assert fields == self._read_varint()
        return [read_witness_field() for _ in range(fields)]

    def _read_witness_field(self):
        value_in = self._read_le_int64()
        block_height = self._read_le_uint32()
        block_index = self._read_le_uint32()
        script = self._read_varbytes()
        return value_in, block_height, block_index, script

    def _read_tx_parts(self, produce_hash=True):
        start = self.cursor
        version = self._read_le_int32()
        inputs = self._read_inputs()
        outputs = self._read_outputs()
        locktime = self._read_le_uint32()
        expiry = self._read_le_uint32()
        end_prefix = self.cursor
        witness = self._read_witness(len(inputs))

        if produce_hash:
            # TxSerializeNoWitness << 16 == 0x10000
            no_witness_header = pack_le_uint32(0x10000 | (version & 0xffff))
            prefix_tx = no_witness_header + self.binary[start+4:end_prefix]
            tx_hash = self.blake256(prefix_tx)
        else:
            tx_hash = None

        return TxDcr(
            version,
            inputs,
            outputs,
            locktime,
            expiry,
            witness
        ), tx_hash, self.cursor - start
