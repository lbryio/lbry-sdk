# Copyright (c) 2017, Neil Booth
# Copyright (c) 2018, LBRY Inc.
#
# All rights reserved.
#
# See the file "LICENCE" for information about the copyright
# and warranty status of this software.

""" Logic for BIP32 Hierarchical Key Derivation. """

import struct
import hashlib
from six import int2byte, byte2int, indexbytes

import ecdsa
import ecdsa.ellipticcurve as EC
import ecdsa.numbertheory as NT

from torba.basecoin import BaseCoin
from torba.hash import Base58, hmac_sha512, hash160, double_sha256
from torba.util import cachedproperty, bytes_to_int, int_to_bytes


class DerivationError(Exception):
    """ Raised when an invalid derivation occurs. """


class _KeyBase(object):
    """ A BIP32 Key, public or private. """

    CURVE = ecdsa.SECP256k1

    def __init__(self, coin, chain_code, n, depth, parent):
        if not isinstance(coin, BaseCoin):
            raise TypeError('invalid coin')
        if not isinstance(chain_code, (bytes, bytearray)):
            raise TypeError('chain code must be raw bytes')
        if len(chain_code) != 32:
            raise ValueError('invalid chain code')
        if not 0 <= n < 1 << 32:
            raise ValueError('invalid child number')
        if not 0 <= depth < 256:
            raise ValueError('invalid depth')
        if parent is not None:
            if not isinstance(parent, type(self)):
                raise TypeError('parent key has bad type')
        self.coin = coin
        self.chain_code = chain_code
        self.n = n
        self.depth = depth
        self.parent = parent

    def _hmac_sha512(self, msg):
        """ Use SHA-512 to provide an HMAC, returned as a pair of 32-byte objects. """
        hmac = hmac_sha512(self.chain_code, msg)
        return hmac[:32], hmac[32:]

    def _extended_key(self, ver_bytes, raw_serkey):
        """ Return the 78-byte extended key given prefix version bytes and serialized key bytes. """
        if not isinstance(ver_bytes, (bytes, bytearray)):
            raise TypeError('ver_bytes must be raw bytes')
        if len(ver_bytes) != 4:
            raise ValueError('ver_bytes must have length 4')
        if not isinstance(raw_serkey, (bytes, bytearray)):
            raise TypeError('raw_serkey must be raw bytes')
        if len(raw_serkey) != 33:
            raise ValueError('raw_serkey must have length 33')

        return (ver_bytes + int2byte(self.depth)
                + self.parent_fingerprint() + struct.pack('>I', self.n)
                + self.chain_code + raw_serkey)

    def fingerprint(self):
        """ Return the key's fingerprint as 4 bytes. """
        return self.identifier()[:4]

    def parent_fingerprint(self):
        """ Return the parent key's fingerprint as 4 bytes. """
        return self.parent.fingerprint() if self.parent else int2byte(0)*4

    def extended_key_string(self):
        """ Return an extended key as a base58 string. """
        return Base58.encode_check(self.extended_key())


class PubKey(_KeyBase):
    """ A BIP32 public key. """

    def __init__(self, coin, pubkey, chain_code, n, depth, parent=None):
        super(PubKey, self).__init__(coin, chain_code, n, depth, parent)
        if isinstance(pubkey, ecdsa.VerifyingKey):
            self.verifying_key = pubkey
        else:
            self.verifying_key = self._verifying_key_from_pubkey(pubkey)

    @classmethod
    def _verifying_key_from_pubkey(cls, pubkey):
        """ Converts a 33-byte compressed pubkey into an ecdsa.VerifyingKey object. """
        if not isinstance(pubkey, (bytes, bytearray)):
            raise TypeError('pubkey must be raw bytes')
        if len(pubkey) != 33:
            raise ValueError('pubkey must be 33 bytes')
        if byte2int(pubkey[0]) not in (2, 3):
            raise ValueError('invalid pubkey prefix byte')
        curve = cls.CURVE.curve

        is_odd = byte2int(pubkey[0]) == 3
        x = bytes_to_int(pubkey[1:])

        # p is the finite field order
        a, b, p = curve.a(), curve.b(), curve.p()
        y2 = pow(x, 3, p) + b
        assert a == 0  # Otherwise y2 += a * pow(x, 2, p)
        y = NT.square_root_mod_prime(y2 % p, p)
        if bool(y & 1) != is_odd:
            y = p - y
        point = EC.Point(curve, x, y)

        return ecdsa.VerifyingKey.from_public_point(point, curve=cls.CURVE)

    @cachedproperty
    def pubkey_bytes(self):
        """ Return the compressed public key as 33 bytes. """
        point = self.verifying_key.pubkey.point
        prefix = int2byte(2 + (point.y() & 1))
        padded_bytes = _exponent_to_bytes(point.x())
        return prefix + padded_bytes

    @cachedproperty
    def address(self):
        """ The public key as a P2PKH address. """
        return self.coin.public_key_to_address(self.pubkey_bytes)

    def ec_point(self):
        return self.verifying_key.pubkey.point

    def child(self, n):
        """ Return the derived child extended pubkey at index N. """
        if not 0 <= n < (1 << 31):
            raise ValueError('invalid BIP32 public key child number')

        msg = self.pubkey_bytes + struct.pack('>I', n)
        L, R = self._hmac_sha512(msg)

        curve = self.CURVE
        L = bytes_to_int(L)
        if L >= curve.order:
            raise DerivationError

        point = curve.generator * L + self.ec_point()
        if point == EC.INFINITY:
            raise DerivationError

        verkey = ecdsa.VerifyingKey.from_public_point(point, curve=curve)

        return PubKey(self.coin, verkey, R, n, self.depth + 1, self)

    def identifier(self):
        """ Return the key's identifier as 20 bytes. """
        return hash160(self.pubkey_bytes)

    def extended_key(self):
        """ Return a raw extended public key. """
        return self._extended_key(
            self.coin.extended_public_key_prefix,
            self.pubkey_bytes
        )


class LowSValueSigningKey(ecdsa.SigningKey):
    """
    Enforce low S values in signatures
    BIP-0062: https://github.com/bitcoin/bips/blob/master/bip-0062.mediawiki#low-s-values-in-signatures
    """

    def sign_number(self, number, entropy=None, k=None):
        order = self.privkey.order
        r, s = ecdsa.SigningKey.sign_number(self, number, entropy, k)
        if s > order / 2:
            s = order - s
        return r, s


class PrivateKey(_KeyBase):
    """A BIP32 private key."""

    HARDENED = 1 << 31

    def __init__(self, coin, privkey, chain_code, n, depth, parent=None):
        super(PrivateKey, self).__init__(coin, chain_code, n, depth, parent)
        if isinstance(privkey, ecdsa.SigningKey):
            self.signing_key = privkey
        else:
            self.signing_key = self._signing_key_from_privkey(privkey)

    @classmethod
    def _signing_key_from_privkey(cls, private_key):
        """ Converts a 32-byte private key into an ecdsa.SigningKey object. """
        exponent = cls._private_key_secret_exponent(private_key)
        return LowSValueSigningKey.from_secret_exponent(exponent, curve=cls.CURVE)

    @classmethod
    def _private_key_secret_exponent(cls, private_key):
        """ Return the private key as a secret exponent if it is a valid private key. """
        if not isinstance(private_key, (bytes, bytearray)):
            raise TypeError('private key must be raw bytes')
        if len(private_key) != 32:
            raise ValueError('private key must be 32 bytes')
        exponent = bytes_to_int(private_key)
        if not 1 <= exponent < cls.CURVE.order:
            raise ValueError('private key represents an invalid exponent')
        return exponent

    @classmethod
    def from_seed(cls, coin, seed):
        # This hard-coded message string seems to be coin-independent...
        hmac = hmac_sha512(b'Bitcoin seed', seed)
        privkey, chain_code = hmac[:32], hmac[32:]
        return cls(coin, privkey, chain_code, 0, 0)

    @cachedproperty
    def private_key_bytes(self):
        """ Return the serialized private key (no leading zero byte). """
        return _exponent_to_bytes(self.secret_exponent())

    @cachedproperty
    def public_key(self):
        """ Return the corresponding extended public key. """
        verifying_key = self.signing_key.get_verifying_key()
        parent_pubkey = self.parent.public_key if self.parent else None
        return PubKey(self.coin, verifying_key, self.chain_code, self.n, self.depth,
                      parent_pubkey)

    def ec_point(self):
        return self.public_key.ec_point()

    def secret_exponent(self):
        """ Return the private key as a secret exponent. """
        return self.signing_key.privkey.secret_multiplier

    def wif(self):
        """ Return the private key encoded in Wallet Import Format. """
        return self.coin.private_key_to_wif(self.private_key_bytes)

    def address(self):
        """ The public key as a P2PKH address. """
        return self.public_key.address

    def child(self, n):
        """ Return the derived child extended private key at index N."""
        if not 0 <= n < (1 << 32):
            raise ValueError('invalid BIP32 private key child number')

        if n >= self.HARDENED:
            serkey = b'\0' + self.private_key_bytes
        else:
            serkey = self.public_key.pubkey_bytes

        msg = serkey + struct.pack('>I', n)
        L, R = self._hmac_sha512(msg)

        curve = self.CURVE
        L = bytes_to_int(L)
        exponent = (L + bytes_to_int(self.private_key_bytes)) % curve.order
        if exponent == 0 or L >= curve.order:
            raise DerivationError

        privkey = _exponent_to_bytes(exponent)

        return PrivateKey(self.coin, privkey, R, n, self.depth + 1, self)

    def sign(self, data):
        """ Produce a signature for piece of data by double hashing it and signing the hash. """
        key = self.signing_key
        digest = double_sha256(data)
        return key.sign_digest_deterministic(digest, hashlib.sha256, ecdsa.util.sigencode_der)

    def identifier(self):
        """Return the key's identifier as 20 bytes."""
        return self.public_key.identifier()

    def extended_key(self):
        """Return a raw extended private key."""
        return self._extended_key(
            self.coin.extended_private_key_prefix,
            b'\0' + self.private_key_bytes
        )


def _exponent_to_bytes(exponent):
    """Convert an exponent to 32 big-endian bytes"""
    return (int2byte(0)*32 + int_to_bytes(exponent))[-32:]


def _from_extended_key(coin, ekey):
    """Return a PubKey or PrivateKey from an extended key raw bytes."""
    if not isinstance(ekey, (bytes, bytearray)):
        raise TypeError('extended key must be raw bytes')
    if len(ekey) != 78:
        raise ValueError('extended key must have length 78')

    depth = indexbytes(ekey, 4)
    fingerprint = ekey[5:9]   # Not used
    n, = struct.unpack('>I', ekey[9:13])
    chain_code = ekey[13:45]

    if ekey[:4] == coin.extended_public_key_prefix:
        pubkey = ekey[45:]
        key = PubKey(coin, pubkey, chain_code, n, depth)
    elif ekey[:4] == coin.extended_private_key_prefix:
        if indexbytes(ekey, 45) != 0:
            raise ValueError('invalid extended private key prefix byte')
        privkey = ekey[46:]
        key = PrivateKey(coin, privkey, chain_code, n, depth)
    else:
        raise ValueError('version bytes unrecognised')

    return key


def from_extended_key_string(coin, ekey_str):
    """Given an extended key string, such as

    xpub6BsnM1W2Y7qLMiuhi7f7dbAwQZ5Cz5gYJCRzTNainXzQXYjFwtuQXHd
    3qfi3t3KJtHxshXezfjft93w4UE7BGMtKwhqEHae3ZA7d823DVrL

    return a PubKey or PrivateKey.
    """
    return _from_extended_key(coin, Base58.decode_check(ekey_str))
