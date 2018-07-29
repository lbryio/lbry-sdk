import os
import struct
import logging
import typing
from binascii import unhexlify

from twisted.internet import threads, defer

from torba.stream import StreamController
from torba.util import int_to_hex, rev_hex, hash_encode
from torba.hash import double_sha256, pow_hash
if typing.TYPE_CHECKING:
    from torba import baseledger

log = logging.getLogger(__name__)


class BaseHeaders:

    header_size = 80
    verify_bits_to_target = True

    def __init__(self, ledger: 'baseledger.BaseLedger') -> None:
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
        log.info(
            '%s: added %s header blocks, final height %s',
            self.ledger.get_id(), change, self.height
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

        bits, _ = self._calculate_next_work_required(height, previous_header, header)
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
            bits_n = (bits >> 24) & 0xff
            assert 0x03 <= bits_n <= 0x1d, \
                "First part of bits should be in [0x03, 0x1d], but it was {}".format(hex(bits_n))
            bits_base = bits & 0xffffff
            assert 0x8000 <= bits_base <= 0x7fffff, \
                "Second part of bits should be in [0x8000, 0x7fffff] but it was {}".format(bits_base)

        # new target
        retarget_timespan = self.ledger.target_timespan
        n_actual_timespan = last['timestamp'] - first['timestamp']

        n_modulated_timespan = retarget_timespan + (n_actual_timespan - retarget_timespan) // 8

        n_min_timespan = retarget_timespan - (retarget_timespan // 8)
        n_max_timespan = retarget_timespan + (retarget_timespan // 2)

        # Limit adjustment step
        if n_modulated_timespan < n_min_timespan:
            n_modulated_timespan = n_min_timespan
        elif n_modulated_timespan > n_max_timespan:
            n_modulated_timespan = n_max_timespan

        # Retarget
        bn_pow_limit = _ArithUint256(self.ledger.max_target)
        bn_new = _ArithUint256.set_compact(last['bits'])
        bn_new *= n_modulated_timespan
        bn_new //= n_modulated_timespan
        if bn_new > bn_pow_limit:
            bn_new = bn_pow_limit

        return bn_new.get_compact(), bn_new._value


class _ArithUint256:
    """ See: lbrycrd/src/arith_uint256.cpp """

    def __init__(self, value):
        self._value = value

    def __str__(self):
        return hex(self._value)

    @staticmethod
    def from_compact(n_compact):
        """Convert a compact representation into its value"""
        n_size = n_compact >> 24
        # the lower 23 bits
        n_word = n_compact & 0x007fffff
        if n_size <= 3:
            return n_word >> 8 * (3 - n_size)
        else:
            return n_word << 8 * (n_size - 3)

    @classmethod
    def set_compact(cls, n_compact):
        return cls(cls.from_compact(n_compact))

    def bits(self):
        """Returns the position of the highest bit set plus one."""
        bits = bin(self._value)[2:]
        for i, d in enumerate(bits):
            if d:
                return (len(bits) - i) + 1
        return 0

    def get_low64(self):
        return self._value & 0xffffffffffffffff

    def get_compact(self):
        """Convert a value into its compact representation"""
        n_size = (self.bits() + 7) // 8
        if n_size <= 3:
            n_compact = self.get_low64() << 8 * (3 - n_size)
        else:
            n = _ArithUint256(self._value >> 8 * (n_size - 3))
            n_compact = n.get_low64()
        # The 0x00800000 bit denotes the sign.
        # Thus, if it is already set, divide the mantissa by 256 and increase the exponent.
        if n_compact & 0x00800000:
            n_compact >>= 8
            n_size += 1
        assert (n_compact & ~0x007fffff) == 0
        assert n_size < 256
        n_compact |= n_size << 24
        return n_compact

    def __mul__(self, x):
        # Take the mod because we are limited to an unsigned 256 bit number
        return _ArithUint256((self._value * x) % 2 ** 256)

    def __ifloordiv__(self, x):
        self._value = (self._value // x)
        return self

    def __gt__(self, x):
        return self._value > x._value
