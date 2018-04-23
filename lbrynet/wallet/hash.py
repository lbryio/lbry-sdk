# Copyright (c) 2016-2017, Neil Booth
# Copyright (c) 2018, LBRY Inc.
#
# All rights reserved.
#
# See the file "LICENCE" for information about the copyright
# and warranty status of this software.

""" Cryptography hash functions and related classes. """

import six
import aes
import base64
import hashlib
import hmac
from binascii import hexlify, unhexlify

from .util import bytes_to_int, int_to_bytes
from .constants import CHAINS, MAIN_CHAIN

_sha256 = hashlib.sha256
_sha512 = hashlib.sha512
_new_hash = hashlib.new
_new_hmac = hmac.new


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
    r1 = ripemd160(r[:len(r) / 2])
    r2 = ripemd160(r[len(r) / 2:])
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


def public_key_to_address(public_key, chain=MAIN_CHAIN):
    return hash160_to_address(hash160(public_key), chain)


def hash160_to_address(h160, chain=MAIN_CHAIN):
    prefix = CHAINS[chain]['pubkey_address_prefix']
    raw_address = six.int2byte(prefix) + h160
    return Base58.encode(raw_address + double_sha256(raw_address)[0:4])


def address_to_hash_160(address):
    bytes = Base58.decode(address)
    prefix, pubkey_bytes, addr_checksum = bytes[0], bytes[1:21], bytes[21:]
    return pubkey_bytes


def aes_encrypt(secret, value):
    return base64.b64encode(aes.encryptData(secret, value.encode('utf8')))


def aes_decrypt(secret, value):
    return aes.decryptData(secret, base64.b64decode(value)).decode('utf8')


class Base58Error(Exception):
    """ Exception used for Base58 errors. """


class Base58(object):
    """ Class providing base 58 functionality. """

    chars = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    assert len(chars) == 58
    cmap = {c: n for n, c in enumerate(chars)}

    @staticmethod
    def char_value(c):
        val = Base58.cmap.get(c)
        if val is None:
            raise Base58Error('invalid base 58 character "{}"'.format(c))
        return val

    @staticmethod
    def decode(txt):
        """ Decodes txt into a big-endian bytearray. """
        if not isinstance(txt, str):
            raise TypeError('a string is required')

        if not txt:
            raise Base58Error('string cannot be empty')

        value = 0
        for c in txt:
            value = value * 58 + Base58.char_value(c)

        result = int_to_bytes(value)

        # Prepend leading zero bytes if necessary
        count = 0
        for c in txt:
            if c != '1':
                break
            count += 1
        if count:
            result = six.int2byte(0)*count + result

        return result

    @staticmethod
    def encode(be_bytes):
        """Converts a big-endian bytearray into a base58 string."""
        value = bytes_to_int(be_bytes)

        txt = ''
        while value:
            value, mod = divmod(value, 58)
            txt += Base58.chars[mod]

        for byte in be_bytes:
            if byte != 0:
                break
            txt += '1'

        return txt[::-1]

    @staticmethod
    def decode_check(txt, hash_fn=double_sha256):
        """ Decodes a Base58Check-encoded string to a payload. The version prefixes it. """
        be_bytes = Base58.decode(txt)
        result, check = be_bytes[:-4], be_bytes[-4:]
        if check != hash_fn(result)[:4]:
            raise Base58Error('invalid base 58 checksum for {}'.format(txt))
        return result

    @staticmethod
    def encode_check(payload, hash_fn=double_sha256):
        """ Encodes a payload bytearray (which includes the version byte(s))
            into a Base58Check string."""
        be_bytes = payload + hash_fn(payload)[:4]
        return Base58.encode(be_bytes)
