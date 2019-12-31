from lbry.crypto.hash import double_sha256
from lbry.crypto.util import bytes_to_int, int_to_bytes


class Base58Error(Exception):
    """ Exception used for Base58 errors. """


class Base58:
    """ Class providing base 58 functionality. """

    chars = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    assert len(chars) == 58
    char_map = {c: n for n, c in enumerate(chars)}

    @classmethod
    def char_value(cls, c):
        val = cls.char_map.get(c)
        if val is None:
            raise Base58Error(f'invalid base 58 character "{c}"')
        return val

    @classmethod
    def decode(cls, txt):
        """ Decodes txt into a big-endian bytearray. """
        if isinstance(txt, memoryview):
            txt = str(txt)

        if isinstance(txt, bytes):
            txt = txt.decode()

        if not isinstance(txt, str):
            raise TypeError('a string is required')

        if not txt:
            raise Base58Error('string cannot be empty')

        value = 0
        for c in txt:
            value = value * 58 + cls.char_value(c)

        result = int_to_bytes(value)

        # Prepend leading zero bytes if necessary
        count = 0
        for c in txt:
            if c != '1':
                break
            count += 1
        if count:
            result = bytes((0,)) * count + result

        return result

    @classmethod
    def encode(cls, be_bytes):
        """Converts a big-endian bytearray into a base58 string."""
        value = bytes_to_int(be_bytes)

        txt = ''
        while value:
            value, mod = divmod(value, 58)
            txt += cls.chars[mod]

        for byte in be_bytes:
            if byte != 0:
                break
            txt += '1'

        return txt[::-1]

    @classmethod
    def decode_check(cls, txt, hash_fn=double_sha256):
        """ Decodes a Base58Check-encoded string to a payload. The version prefixes it. """
        be_bytes = cls.decode(txt)
        result, check = be_bytes[:-4], be_bytes[-4:]
        if check != hash_fn(result)[:4]:
            raise Base58Error(f'invalid base 58 checksum for {txt}')
        return result

    @classmethod
    def encode_check(cls, payload, hash_fn=double_sha256):
        """ Encodes a payload bytearray (which includes the version byte(s))
            into a Base58Check string."""
        be_bytes = payload + hash_fn(payload)[:4]
        return cls.encode(be_bytes)
