# Copyright (c) 2016-2017, Neil Booth
# Copyright (c) 2018, LBRY Inc.
#
# All rights reserved.
#
# See the file "LICENCE" for information about the copyright
# and warranty status of this software.

""" Cryptography hash functions and related classes. """

import os
import six
import base64
import hashlib
import hmac
from binascii import hexlify, unhexlify
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.primitives.ciphers.algorithms import AES
from cryptography.hazmat.primitives.padding import PKCS7
from cryptography.hazmat.backends import default_backend

from torba.util import bytes_to_int, int_to_bytes
from torba.constants import NULL_HASH32

_sha256 = hashlib.sha256
_sha512 = hashlib.sha512
_new_hash = hashlib.new
_new_hmac = hmac.new


class TXRef(object):

    __slots__ = '_id', '_hash'

    def __init__(self):
        self._id = None
        self._hash = None

    @property
    def id(self):
        return self._id

    @property
    def hash(self):
        return self._hash

    @property
    def is_null(self):
        return self.hash == NULL_HASH32


class TXRefImmutable(TXRef):

    __slots__ = ()

    @classmethod
    def from_hash(cls, tx_hash):  # type: (bytes) -> TXRefImmutable
        ref = cls()
        ref._hash = tx_hash
        ref._id = hexlify(tx_hash[::-1]).decode()
        return ref

    @classmethod
    def from_id(cls, tx_id):  # type: (str) -> TXRefImmutable
        ref = cls()
        ref._id = tx_id
        ref._hash = unhexlify(tx_id)[::-1]
        return ref


class TXORef(object):

    __slots__ = 'tx_ref', 'position'

    def __init__(self, tx_ref, position):  # type: (TXRef, int) -> None
        self.tx_ref = tx_ref
        self.position = position

    @property
    def id(self):
        return '{}:{}'.format(self.tx_ref.id, self.position)

    @property
    def is_null(self):
        return self.tx_ref.is_null

    @property
    def txo(self):
        return None


def sha256(x):
    """ Simple wrapper of hashlib sha256. """
    return _sha256(x).digest()


def sha512(x):
    """ Simple wrapper of hashlib sha512. """
    return _sha512(x).digest()


def ripemd160(x):
    """ Simple wrapper of hashlib ripemd160. """
    h = _new_hash('ripemd160')
    h.update(x)
    return h.digest()


def pow_hash(x):
    r = sha512(double_sha256(x))
    r1 = ripemd160(r[:len(r) // 2])
    r2 = ripemd160(r[len(r) // 2:])
    r3 = double_sha256(r1 + r2)
    return r3


def double_sha256(x):
    """ SHA-256 of SHA-256, as used extensively in bitcoin. """
    return sha256(sha256(x))


def hmac_sha512(key, msg):
    """ Use SHA-512 to provide an HMAC. """
    return _new_hmac(key, msg, _sha512).digest()


def hash160(x):
    """ RIPEMD-160 of SHA-256.
        Used to make bitcoin addresses from pubkeys. """
    return ripemd160(sha256(x))


def hash_to_hex_str(x):
    """ Convert a big-endian binary hash to displayed hex string.
        Display form of a binary hash is reversed and converted to hex. """
    return hexlify(reversed(x))


def hex_str_to_hash(x):
    """ Convert a displayed hex string to a binary hash. """
    return reversed(unhexlify(x))


def aes_encrypt(secret, value):
    key = double_sha256(secret)
    init_vector = os.urandom(16)
    encryptor = Cipher(AES(key), modes.CBC(init_vector), default_backend()).encryptor()
    padder = PKCS7(AES.block_size).padder()
    padded_data = padder.update(value) + padder.finalize()
    encrypted_data2 = encryptor.update(padded_data) + encryptor.finalize()
    return base64.b64encode(encrypted_data2)


def aes_decrypt(secret, value):
    data = base64.b64decode(value)
    key = double_sha256(secret)
    init_vector, data = data[:16], data[16:]
    decryptor = Cipher(AES(key), modes.CBC(init_vector), default_backend()).decryptor()
    unpadder = PKCS7(AES.block_size).unpadder()
    result = unpadder.update(decryptor.update(data)) + unpadder.finalize()
    return result


class Base58Error(Exception):
    """ Exception used for Base58 errors. """


class Base58(object):
    """ Class providing base 58 functionality. """

    chars = u'123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    assert len(chars) == 58
    char_map = {c: n for n, c in enumerate(chars)}

    @classmethod
    def char_value(cls, c):
        val = cls.char_map.get(c)
        if val is None:
            raise Base58Error('invalid base 58 character "{}"'.format(c))
        return val

    @classmethod
    def decode(cls, txt):
        """ Decodes txt into a big-endian bytearray. """
        if six.PY2 and isinstance(txt, buffer):
            txt = str(txt)

        if isinstance(txt, six.binary_type):
            txt = txt.decode()

        if not isinstance(txt, six.text_type):
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
            if c != u'1':
                break
            count += 1
        if count:
            result = six.int2byte(0) * count + result

        return result

    @classmethod
    def encode(cls, be_bytes):
        """Converts a big-endian bytearray into a base58 string."""
        value = bytes_to_int(be_bytes)

        txt = u''
        while value:
            value, mod = divmod(value, 58)
            txt += cls.chars[mod]

        for byte in be_bytes:
            if byte != 0:
                break
            txt += u'1'

        return txt[::-1]

    @classmethod
    def decode_check(cls, txt, hash_fn=double_sha256):
        """ Decodes a Base58Check-encoded string to a payload. The version prefixes it. """
        be_bytes = cls.decode(txt)
        result, check = be_bytes[:-4], be_bytes[-4:]
        if check != hash_fn(result)[:4]:
            raise Base58Error('invalid base 58 checksum for {}'.format(txt))
        return result

    @classmethod
    def encode_check(cls, payload, hash_fn=double_sha256):
        """ Encodes a payload bytearray (which includes the version byte(s))
            into a Base58Check string."""
        be_bytes = payload + hash_fn(payload)[:4]
        return cls.encode(be_bytes)
