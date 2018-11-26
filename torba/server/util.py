# Copyright (c) 2016-2017, Neil Booth
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

'''Miscellaneous utility classes and functions.'''


import array
import inspect
from ipaddress import ip_address
import logging
import re
import sys
from collections import Container, Mapping
from struct import pack, Struct

# Logging utilities


class ConnectionLogger(logging.LoggerAdapter):
    '''Prepends a connection identifier to a logging message.'''
    def process(self, msg, kwargs):
        conn_id = self.extra.get('conn_id', 'unknown')
        return f'[{conn_id}] {msg}', kwargs


class CompactFormatter(logging.Formatter):
    '''Strips the module from the logger name to leave the class only.'''
    def format(self, record):
        record.name = record.name.rpartition('.')[-1]
        return super().format(record)


def make_logger(name, *, handler, level):
    '''Return the root ElectrumX logger.'''
    logger = logging.getLogger(name)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def class_logger(path, classname):
    '''Return a hierarchical logger for a class.'''
    return logging.getLogger(path).getChild(classname)


# Method decorator.  To be used for calculations that will always
# deliver the same result.  The method cannot take any arguments
# and should be accessed as an attribute.
class cachedproperty:

    def __init__(self, f):
        self.f = f

    def __get__(self, obj, type):
        obj = obj or type
        value = self.f(obj)
        setattr(obj, self.f.__name__, value)
        return value


def formatted_time(t, sep=' '):
    '''Return a number of seconds as a string in days, hours, mins and
    maybe secs.'''
    t = int(t)
    fmts = (('{:d}d', 86400), ('{:02d}h', 3600), ('{:02d}m', 60))
    parts = []
    for fmt, n in fmts:
        val = t // n
        if parts or val:
            parts.append(fmt.format(val))
        t %= n
    if len(parts) < 3:
        parts.append('{:02d}s'.format(t))
    return sep.join(parts)


def deep_getsizeof(obj):
    """Find the memory footprint of a Python object.

    Based on code from code.tutsplus.com: http://goo.gl/fZ0DXK

    This is a recursive function that drills down a Python object graph
    like a dictionary holding nested dictionaries with lists of lists
    and tuples and sets.

    The sys.getsizeof function does a shallow size of only. It counts each
    object inside a container as pointer only regardless of how big it
    really is.
    """

    ids = set()

    def size(o):
        if id(o) in ids:
            return 0

        r = sys.getsizeof(o)
        ids.add(id(o))

        if isinstance(o, (str, bytes, bytearray, array.array)):
            return r

        if isinstance(o, Mapping):
            return r + sum(size(k) + size(v) for k, v in o.items())

        if isinstance(o, Container):
            return r + sum(size(x) for x in o)

        return r

    return size(obj)


def subclasses(base_class, strict=True):
    '''Return a list of subclasses of base_class in its module.'''
    def select(obj):
        return (inspect.isclass(obj) and issubclass(obj, base_class) and
                (not strict or obj != base_class))

    pairs = inspect.getmembers(sys.modules[base_class.__module__], select)
    return [pair[1] for pair in pairs]


def chunks(items, size):
    '''Break up items, an iterable, into chunks of length size.'''
    for i in range(0, len(items), size):
        yield items[i: i + size]


def resolve_limit(limit):
    if limit is None:
        return -1
    assert isinstance(limit, int) and limit >= 0
    return limit


def bytes_to_int(be_bytes):
    '''Interprets a big-endian sequence of bytes as an integer'''
    return int.from_bytes(be_bytes, 'big')


def int_to_bytes(value):
    '''Converts an integer to a big-endian sequence of bytes'''
    return value.to_bytes((value.bit_length() + 7) // 8, 'big')


def increment_byte_string(bs):
    '''Return the lexicographically next byte string of the same length.

    Return None if there is none (when the input is all 0xff bytes).'''
    for n in range(1, len(bs) + 1):
        if bs[-n] != 0xff:
            return bs[:-n] + bytes([bs[-n] + 1]) + bytes(n - 1)
    return None


class LogicalFile:
    '''A logical binary file split across several separate files on disk.'''

    def __init__(self, prefix, digits, file_size):
        digit_fmt = '{' + ':0{:d}d'.format(digits) + '}'
        self.filename_fmt = prefix + digit_fmt
        self.file_size = file_size

    def read(self, start, size=-1):
        '''Read up to size bytes from the virtual file, starting at offset
        start, and return them.

        If size is -1 all bytes are read.'''
        parts = []
        while size != 0:
            try:
                with self.open_file(start, False) as f:
                    part = f.read(size)
                if not part:
                    break
            except FileNotFoundError:
                break
            parts.append(part)
            start += len(part)
            if size > 0:
                size -= len(part)
        return b''.join(parts)

    def write(self, start, b):
        '''Write the bytes-like object, b, to the underlying virtual file.'''
        while b:
            size = min(len(b), self.file_size - (start % self.file_size))
            with self.open_file(start, True) as f:
                f.write(b if size == len(b) else b[:size])
            b = b[size:]
            start += size

    def open_file(self, start, create):
        '''Open the virtual file and seek to start.  Return a file handle.
        Raise FileNotFoundError if the file does not exist and create
        is False.
        '''
        file_num, offset = divmod(start, self.file_size)
        filename = self.filename_fmt.format(file_num)
        f = open_file(filename, create)
        f.seek(offset)
        return f


def open_file(filename, create=False):
    '''Open the file name.  Return its handle.'''
    try:
        return open(filename, 'rb+')
    except FileNotFoundError:
        if create:
            return open(filename, 'wb+')
        raise


def open_truncate(filename):
    '''Open the file name.  Return its handle.'''
    return open(filename, 'wb+')


def address_string(address):
    '''Return an address as a correctly formatted string.'''
    fmt = '{}:{:d}'
    host, port = address
    try:
        host = ip_address(host)
    except ValueError:
        pass
    else:
        if host.version == 6:
            fmt = '[{}]:{:d}'
    return fmt.format(host, port)

# See http://stackoverflow.com/questions/2532053/validate-a-hostname-string
# Note underscores are valid in domain names, but strictly invalid in host
# names.  We ignore that distinction.


SEGMENT_REGEX = re.compile("(?!-)[A-Z_\\d-]{1,63}(?<!-)$", re.IGNORECASE)


def is_valid_hostname(hostname):
    if len(hostname) > 255:
        return False
    # strip exactly one dot from the right, if present
    if hostname and hostname[-1] == ".":
        hostname = hostname[:-1]
    return all(SEGMENT_REGEX.match(x) for x in hostname.split("."))


def protocol_tuple(s):
    '''Converts a protocol version number, such as "1.0" to a tuple (1, 0).

    If the version number is bad, (0, ) indicating version 0 is returned.'''
    try:
        return tuple(int(part) for part in s.split('.'))
    except Exception:
        return (0, )


def version_string(ptuple):
    '''Convert a version tuple such as (1, 2) to "1.2".
    There is always at least one dot, so (1, ) becomes "1.0".'''
    while len(ptuple) < 2:
        ptuple += (0, )
    return '.'.join(str(p) for p in ptuple)


def protocol_version(client_req, min_tuple, max_tuple):
    '''Given a client's protocol version string, return a pair of
    protocol tuples:

           (negotiated version, client min request)

    If the request is unsupported, the negotiated protocol tuple is
    None.
    '''
    if client_req is None:
        client_min = client_max = min_tuple
    else:
        if isinstance(client_req, list) and len(client_req) == 2:
            client_min, client_max = client_req
        else:
            client_min = client_max = client_req
        client_min = protocol_tuple(client_min)
        client_max = protocol_tuple(client_max)

    result = min(client_max, max_tuple)
    if result < max(client_min, min_tuple) or result == (0, ):
        result = None

    return result, client_min


struct_le_i = Struct('<i')
struct_le_q = Struct('<q')
struct_le_H = Struct('<H')
struct_le_I = Struct('<I')
struct_le_Q = Struct('<Q')
struct_be_H = Struct('>H')
struct_be_I = Struct('>I')
structB = Struct('B')

unpack_le_int32_from = struct_le_i.unpack_from
unpack_le_int64_from = struct_le_q.unpack_from
unpack_le_uint16_from = struct_le_H.unpack_from
unpack_le_uint32_from = struct_le_I.unpack_from
unpack_le_uint64_from = struct_le_Q.unpack_from
unpack_be_uint16_from = struct_be_H.unpack_from
unpack_be_uint32_from = struct_be_I.unpack_from

pack_le_int32 = struct_le_i.pack
pack_le_int64 = struct_le_q.pack
pack_le_uint16 = struct_le_H.pack
pack_le_uint32 = struct_le_I.pack
pack_le_uint64 = struct_le_Q.pack
pack_be_uint16 = struct_be_H.pack
pack_be_uint32 = struct_be_I.pack
pack_byte = structB.pack

hex_to_bytes = bytes.fromhex


def pack_varint(n):
    if n < 253:
        return pack_byte(n)
    if n < 65536:
        return pack_byte(253) + pack_le_uint16(n)
    if n < 4294967296:
        return pack_byte(254) + pack_le_uint32(n)
    return pack_byte(255) + pack_le_uint64(n)


def pack_varbytes(data):
    return pack_varint(len(data)) + data
