import re
from binascii import unhexlify, hexlify
from typing import TypeVar, Sequence, Optional
from torba.client.constants import COIN


def coins_to_satoshis(coins):
    if not isinstance(coins, str):
        raise ValueError("{coins} must be a string")
    result = re.search(r'^(\d{1,10})\.(\d{1,8})$', coins)
    if result is not None:
        whole, fractional = result.groups()
        return int(whole+fractional.ljust(8, "0"))
    raise ValueError("'{lbc}' is not a valid coin decimal")


def satoshis_to_coins(satoshis):
    coins = '{:.8f}'.format(satoshis / COIN).rstrip('0')
    if coins.endswith('.'):
        return coins+'0'
    else:
        return coins


T = TypeVar('T')


class ReadOnlyList(Sequence[T]):

    def __init__(self, lst):
        self.lst = lst

    def __getitem__(self, key):
        return self.lst[key]

    def __len__(self) -> int:
        return len(self.lst)


def subclass_tuple(name, base):
    return type(name, (base,), {'__slots__': ()})


class cachedproperty:

    def __init__(self, f):
        self.f = f

    def __get__(self, obj, objtype):
        obj = obj or objtype
        value = self.f(obj)
        setattr(obj, self.f.__name__, value)
        return value


def bytes_to_int(be_bytes):
    """ Interprets a big-endian sequence of bytes as an integer. """
    return int(hexlify(be_bytes), 16)


def int_to_bytes(value):
    """ Converts an integer to a big-endian sequence of bytes. """
    length = (value.bit_length() + 7) // 8
    s = '%x' % value
    return unhexlify(('0' * (len(s) % 2) + s).zfill(length * 2))


class ArithUint256:
    # https://github.com/bitcoin/bitcoin/blob/master/src/arith_uint256.cpp

    __slots__ = '_value', '_compact'

    def __init__(self, value: int) -> None:
        self._value = value
        self._compact: Optional[int] = None

    @classmethod
    def from_compact(cls, compact) -> 'ArithUint256':
        size = compact >> 24
        word = compact & 0x007fffff
        if size <= 3:
            return cls(word >> 8 * (3 - size))
        else:
            return cls(word << 8 * (size - 3))

    @property
    def value(self) -> int:
        return self._value

    @property
    def compact(self) -> int:
        if self._compact is None:
            self._compact = self._calculate_compact()
        return self._compact

    @property
    def negative(self) -> int:
        return self._calculate_compact(negative=True)

    @property
    def bits(self) -> int:
        """ Returns the position of the highest bit set plus one. """
        bits = bin(self._value)[2:]
        for i, d in enumerate(bits):
            if d:
                return (len(bits) - i) + 1
        return 0

    @property
    def low64(self) -> int:
        return self._value & 0xffffffffffffffff

    def _calculate_compact(self, negative=False) -> int:
        size = (self.bits + 7) // 8
        if size <= 3:
            compact = self.low64 << 8 * (3 - size)
        else:
            compact = ArithUint256(self._value >> 8 * (size - 3)).low64
        # The 0x00800000 bit denotes the sign.
        # Thus, if it is already set, divide the mantissa by 256 and increase the exponent.
        if compact & 0x00800000:
            compact >>= 8
            size += 1
        assert (compact & ~0x007fffff) == 0
        assert size < 256
        compact |= size << 24
        if negative and compact & 0x007fffff:
            compact |= 0x00800000
        return compact

    def __mul__(self, x):
        # Take the mod because we are limited to an unsigned 256 bit number
        return ArithUint256((self._value * x) % 2 ** 256)

    def __truediv__(self, x):
        return ArithUint256(int(self._value / x))

    def __gt__(self, other):
        return self._value > other

    def __lt__(self, other):
        return self._value < other
