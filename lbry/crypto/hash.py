import hashlib
import hmac
from binascii import hexlify, unhexlify


def sha256(x):
    """ Simple wrapper of hashlib sha256. """
    return hashlib.sha256(x).digest()


def sha512(x):
    """ Simple wrapper of hashlib sha512. """
    return hashlib.sha512(x).digest()


def ripemd160(x):
    """ Simple wrapper of hashlib ripemd160. """
    try:
        h = hashlib.new('ripemd160')
    except ValueError as e:
        raise RuntimeError(
            "Your Python/OpenSSL installation does not support RIPEMD160. "
            "Try reinstalling Python with full OpenSSL support."
        ) from e
    h.update(x)
    return h.digest()



def double_sha256(x):
    """ SHA-256 of SHA-256, as used extensively in bitcoin. """
    return sha256(sha256(x))


def hmac_sha512(key, msg):
    """ Use SHA-512 to provide an HMAC. """
    return hmac.new(key, msg, hashlib.sha512).digest()


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
