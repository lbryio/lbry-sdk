from binascii import unhexlify, hexlify
from collections import Sequence


class ReadOnlyList(Sequence):

    def __init__(self, lst):
        self.lst = lst

    def __getitem__(self, key):
        return self.lst[key]

    def __len__(self):
        return len(self.lst)


def subclass_tuple(name, base):
    return type(name, (base,), {'__slots__': ()})


class cachedproperty(object):

    def __init__(self, f):
        self.f = f

    def __get__(self, obj, type):
        obj = obj or type
        value = self.f(obj)
        setattr(obj, self.f.__name__, value)
        return value


class classproperty(object):

    def __init__(self, f):
        self.f = f

    def __get__(self, obj, owner):
        return self.f(owner)


def bytes_to_int(be_bytes):
    """ Interprets a big-endian sequence of bytes as an integer. """
    return int(hexlify(be_bytes), 16)


def int_to_bytes(value):
    """ Converts an integer to a big-endian sequence of bytes. """
    length = (value.bit_length() + 7) // 8
    h = '%x' % value
    return unhexlify(('0' * (len(h) % 2) + h).zfill(length * 2))


def rev_hex(s):
    return s.decode('hex')[::-1].encode('hex')


def int_to_hex(i, length=1):
    s = hex(i)[2:].rstrip('L')
    s = "0" * (2 * length - len(s)) + s
    return rev_hex(s)


def hex_to_int(s):
    return int('0x' + s[::-1].encode('hex'), 16)


def hash_encode(x):
    return x[::-1].encode('hex')
