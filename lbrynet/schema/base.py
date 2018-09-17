import six
from lbrynet.schema.schema import ADDRESS_CHECKSUM_LENGTH
from lbrynet.schema.hashing import double_sha256
from lbrynet.schema.error import InvalidAddress


alphabet = b'123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


if six.PY2:
    iseq, bseq, buffer = (
        lambda s: map(ord, s),
        lambda s: ''.join(map(chr, s)),
        lambda s: s,
    )
elif six.PY3:
    iseq, bseq, buffer = (
        lambda s: s,
        bytes,
        lambda s: s.buffer,
    )


def scrub_input(v):
    if isinstance(v, str) and not isinstance(v, bytes):
        v = v.encode('ascii')
    return v


def b58encode_int(i, default_one=True):
    '''Encode an integer using Base58'''
    if not i and default_one:
        return alphabet[0:1]
    string = b""
    while i:
        i, idx = divmod(i, 58)
        string = alphabet[idx:idx+1] + string
    return string


def b58encode(v):
    '''Encode a string using Base58'''

    v = scrub_input(v)

    nPad = len(v)
    v = v.lstrip(b'\0')
    nPad -= len(v)

    p, acc = 1, 0
    for c in iseq(reversed(v)):
        acc += p * c
        p = p << 8

    result = b58encode_int(acc, default_one=False)

    return alphabet[0:1] * nPad + result


def b58decode_int(v):
    '''Decode a Base58 encoded string as an integer'''

    v = scrub_input(v)

    decimal = 0
    for char in v:
        decimal = decimal * 58 + alphabet.index(char)
    return decimal


def b58decode(v):
    '''Decode a Base58 encoded string'''

    v = scrub_input(v)

    origlen = len(v)
    v = v.lstrip(alphabet[0:1])
    newlen = len(v)

    acc = b58decode_int(v)

    result = []
    while acc > 0:
        acc, mod = divmod(acc, 256)
        result.append(mod)

    return (b'\0' * (origlen - newlen) + bseq(reversed(result)))


def validate_b58_checksum(addr_bytes):
    addr_without_checksum = addr_bytes[:-ADDRESS_CHECKSUM_LENGTH]
    addr_checksum = addr_bytes[-ADDRESS_CHECKSUM_LENGTH:]
    if double_sha256(addr_without_checksum)[:ADDRESS_CHECKSUM_LENGTH] != addr_checksum:
        raise InvalidAddress("Invalid address checksum")


def b58decode_strip_checksum(v):
    addr_bytes = b58decode(v)
    validate_b58_checksum(addr_bytes)
    return addr_bytes[:-ADDRESS_CHECKSUM_LENGTH]


def b58encode_with_checksum(addr_bytes):
    addr_checksum = double_sha256(addr_bytes)[:ADDRESS_CHECKSUM_LENGTH]
    return b58encode(addr_bytes + addr_checksum)
