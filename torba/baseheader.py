import os
import struct
import logging
from binascii import unhexlify

from twisted.internet import threads, defer

from torba.stream import StreamController, execute_serially
from torba.util import int_to_hex, rev_hex, hash_encode
from torba.hash import double_sha256, pow_hash

log = logging.getLogger(__name__)


class BaseHeaders:

    header_size = 80
    verify_bits_to_target = True

    def __init__(self, ledger):  # type: (baseledger.BaseLedger) -> BaseHeaders
        self.ledger = ledger
        self._size = None
        self._on_change_controller = StreamController()
        self.on_changed = self._on_change_controller.stream

    @property
    def path(self):
        return os.path.join(self.ledger.path, 'headers')

    def touch(self):
        if not os.path.exists(self.path):
            with open(self.path, 'wb'):
                pass

    @property
    def height(self):
        return len(self)-1

    def hash(self, height=None):
        if height is None:
            height = self.height
        header = self[height]
        return self._hash_header(header)

    def sync_read_length(self):
        return os.path.getsize(self.path) // self.header_size

    def sync_read_header(self, height):
        if 0 <= height < len(self):
            with open(self.path, 'rb') as f:
                f.seek(height * self.header_size)
                return f.read(self.header_size)

    def __len__(self):
        if self._size is None:
            self._size = self.sync_read_length()
        return self._size

    def __getitem__(self, height):
        assert not isinstance(height, slice), \
            "Slicing of header chain has not been implemented yet."
        header = self.sync_read_header(height)
        return self._deserialize(height, header)

    @execute_serially
    @defer.inlineCallbacks
    def connect(self, start, headers):
        yield threads.deferToThread(self._sync_connect, start, headers)

    def _sync_connect(self, start, headers):
        previous_header = None
        for header in self._iterate_headers(start, headers):
            height = header['block_height']
            if previous_header is None and height > 0:
                previous_header = self[height-1]
            self._verify_header(height, header, previous_header)
            previous_header = header

        with open(self.path, 'r+b') as f:
            f.seek(start * self.header_size)
            f.write(headers)
            f.truncate()

        _old_size = self._size
        self._size = self.sync_read_length()
        change = self._size - _old_size
        log.info('{}: added {} header blocks, final height {}'.format(
            self.ledger.get_id(), change, self.height)
        )
        self._on_change_controller.add(change)

    def _iterate_headers(self, height, headers):
        assert len(headers) % self.header_size == 0
        for idx in range(len(headers) // self.header_size):
            start, end = idx * self.header_size, (idx + 1) * self.header_size
            header = headers[start:end]
            yield self._deserialize(height+idx, header)

    def _verify_header(self, height, header, previous_header):
        previous_hash = self._hash_header(previous_header)
        assert previous_hash == header['prev_block_hash'], \
            "prev hash mismatch: {} vs {}".format(previous_hash, header['prev_block_hash'])

        bits, target = self._calculate_next_work_required(height, previous_header, header)
        assert bits == header['bits'], \
            "bits mismatch: {} vs {} (hash: {})".format(
                bits, header['bits'], self._hash_header(header))

        # TODO: FIX ME!!!
        #_pow_hash = self._pow_hash_header(header)
        #assert int(b'0x' + _pow_hash, 16) <= target, \
        #    "insufficient proof of work: {} vs target {}".format(
        #    int(b'0x' + _pow_hash, 16), target)

    @staticmethod
    def _serialize(header):
        return b''.join([
            int_to_hex(header['version'], 4),
            rev_hex(header['prev_block_hash']),
            rev_hex(header['merkle_root']),
            int_to_hex(int(header['timestamp']), 4),
            int_to_hex(int(header['bits']), 4),
            int_to_hex(int(header['nonce']), 4)
        ])

    @staticmethod
    def _deserialize(height, header):
        version, = struct.unpack('<I', header[:4])
        timestamp, bits, nonce = struct.unpack('<III', header[68:80])
        return {
            'block_height': height,
            'version': version,
            'prev_block_hash': hash_encode(header[4:36]),
            'merkle_root': hash_encode(header[36:68]),
            'timestamp': timestamp,
            'bits': bits,
            'nonce': nonce,
        }

    def _hash_header(self, header):
        if header is None:
            return b'0' * 64
        return hash_encode(double_sha256(unhexlify(self._serialize(header))))

    def _pow_hash_header(self, header):
        if header is None:
            return b'0' * 64
        return hash_encode(pow_hash(unhexlify(self._serialize(header))))

    def _calculate_next_work_required(self, height, first, last):

        if height == 0:
            return self.ledger.genesis_bits, self.ledger.max_target

        if self.verify_bits_to_target:
            bits = last['bits']
            bitsN = (bits >> 24) & 0xff
            assert 0x03 <= bitsN <= 0x1d, \
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


class _ArithUint256:
    """ See: lbrycrd/src/arith_uint256.cpp """

    def __init__(self, value):
        self._value = value

    def __str__(self):
        return hex(self._value)

    @staticmethod
    def fromCompact(nCompact):
        """Convert a compact representation into its value"""
        nSize = nCompact >> 24
        # the lower 23 bits
        nWord = nCompact & 0x007fffff
        if nSize <= 3:
            return nWord >> 8 * (3 - nSize)
        else:
            return nWord << 8 * (nSize - 3)

    @classmethod
    def SetCompact(cls, nCompact):
        return cls(cls.fromCompact(nCompact))

    def bits(self):
        """Returns the position of the highest bit set plus one."""
        bn = bin(self._value)[2:]
        for i, d in enumerate(bn):
            if d:
                return (len(bn) - i) + 1
        return 0

    def GetLow64(self):
        return self._value & 0xffffffffffffffff

    def GetCompact(self):
        """Convert a value into its compact representation"""
        nSize = (self.bits() + 7) // 8
        nCompact = 0
        if nSize <= 3:
            nCompact = self.GetLow64() << 8 * (3 - nSize)
        else:
            bn = _ArithUint256(self._value >> 8 * (nSize - 3))
            nCompact = bn.GetLow64()
        # The 0x00800000 bit denotes the sign.
        # Thus, if it is already set, divide the mantissa by 256 and increase the exponent.
        if nCompact & 0x00800000:
            nCompact >>= 8
            nSize += 1
        assert (nCompact & ~0x007fffff) == 0
        assert nSize < 256
        nCompact |= nSize << 24
        return nCompact

    def __mul__(self, x):
        # Take the mod because we are limited to an unsigned 256 bit number
        return _ArithUint256((self._value * x) % 2 ** 256)

    def __ifloordiv__(self, x):
        self._value = (self._value // x)
        return self

    def __gt__(self, x):
        return self._value > x._value
