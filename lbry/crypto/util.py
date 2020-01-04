from binascii import unhexlify, hexlify


def bytes_to_int(be_bytes):
    """ Interprets a big-endian sequence of bytes as an integer. """
    return int(hexlify(be_bytes), 16)


def int_to_bytes(value):
    """ Converts an integer to a big-endian sequence of bytes. """
    length = (value.bit_length() + 7) // 8
    s = '%x' % value
    return unhexlify(('0' * (len(s) % 2) + s).zfill(length * 2))
