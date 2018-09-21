# Copyright (c) 2017, Neil Booth
# Copyright (c) 2018, LBRY Inc.
#
# All rights reserved.
#
# See the file "LICENCE" for information about the copyright
# and warranty status of this software.

""" Logic for BIP32 Hierarchical Key Derivation. """
from coincurve import PublicKey, PrivateKey as _PrivateKey

from torba.hash import Base58, hmac_sha512, hash160, double_sha256
from torba.util import cachedproperty


class DerivationError(Exception):
    """ Raised when an invalid derivation occurs. """


class _KeyBase:
    """ A BIP32 Key, public or private. """

    def __init__(self, ledger, chain_code, n, depth, parent):
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
        self.ledger = ledger
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

        return (ver_bytes + bytes((self.depth,))
                + self.parent_fingerprint() + self.n.to_bytes(4, 'big')
                + self.chain_code + raw_serkey)

    def identifier(self):
        raise NotImplementedError

    def extended_key(self):
        raise NotImplementedError

    def fingerprint(self):
        """ Return the key's fingerprint as 4 bytes. """
        return self.identifier()[:4]

    def parent_fingerprint(self):
        """ Return the parent key's fingerprint as 4 bytes. """
        return self.parent.fingerprint() if self.parent else bytes((0,)*4)

    def extended_key_string(self):
        """ Return an extended key as a base58 string. """
        return Base58.encode_check(self.extended_key())


class PubKey(_KeyBase):
    """ A BIP32 public key. """

    def __init__(self, ledger, pubkey, chain_code, n, depth, parent=None):
        super().__init__(ledger, chain_code, n, depth, parent)
        if isinstance(pubkey, PublicKey):
            self.verifying_key = pubkey
        else:
            self.verifying_key = self._verifying_key_from_pubkey(pubkey)

    @classmethod
    def _verifying_key_from_pubkey(cls, pubkey):
        """ Converts a 33-byte compressed pubkey into an PublicKey object. """
        if not isinstance(pubkey, (bytes, bytearray)):
            raise TypeError('pubkey must be raw bytes')
        if len(pubkey) != 33:
            raise ValueError('pubkey must be 33 bytes')
        if pubkey[0] not in (2, 3):
            raise ValueError('invalid pubkey prefix byte')
        return PublicKey(pubkey)

    @cachedproperty
    def pubkey_bytes(self):
        """ Return the compressed public key as 33 bytes. """
        return self.verifying_key.format(True)

    @cachedproperty
    def address(self):
        """ The public key as a P2PKH address. """
        return self.ledger.public_key_to_address(self.pubkey_bytes)

    def ec_point(self):
        return self.verifying_key.point()

    def child(self, n: int):
        """ Return the derived child extended pubkey at index N. """
        if not 0 <= n < (1 << 31):
            raise ValueError('invalid BIP32 public key child number')

        msg = self.pubkey_bytes + n.to_bytes(4, 'big')
        L_b, R_b = self._hmac_sha512(msg)  # pylint: disable=invalid-name
        derived_key = self.verifying_key.add(L_b)
        return PubKey(self.ledger, derived_key, R_b, n, self.depth + 1, self)

    def identifier(self):
        """ Return the key's identifier as 20 bytes. """
        return hash160(self.pubkey_bytes)

    def extended_key(self):
        """ Return a raw extended public key. """
        return self._extended_key(
            self.ledger.extended_public_key_prefix,
            self.pubkey_bytes
        )


class PrivateKey(_KeyBase):
    """A BIP32 private key."""

    HARDENED = 1 << 31

    def __init__(self, ledger, privkey, chain_code, n, depth, parent=None):
        super().__init__(ledger, chain_code, n, depth, parent)
        if isinstance(privkey, _PrivateKey):
            self.signing_key = privkey
        else:
            self.signing_key = self._signing_key_from_privkey(privkey)

    @classmethod
    def _signing_key_from_privkey(cls, private_key):
        """ Converts a 32-byte private key into an coincurve.PrivateKey object. """
        return _PrivateKey.from_int(PrivateKey._private_key_secret_exponent(private_key))

    @classmethod
    def _private_key_secret_exponent(cls, private_key):
        """ Return the private key as a secret exponent if it is a valid private key. """
        if not isinstance(private_key, (bytes, bytearray)):
            raise TypeError('private key must be raw bytes')
        if len(private_key) != 32:
            raise ValueError('private key must be 32 bytes')
        return int.from_bytes(private_key, 'big')

    @classmethod
    def from_seed(cls, ledger, seed):
        # This hard-coded message string seems to be coin-independent...
        hmac = hmac_sha512(b'Bitcoin seed', seed)
        privkey, chain_code = hmac[:32], hmac[32:]
        return cls(ledger, privkey, chain_code, 0, 0)

    @cachedproperty
    def private_key_bytes(self):
        """ Return the serialized private key (no leading zero byte). """
        return self.signing_key.secret

    @cachedproperty
    def public_key(self):
        """ Return the corresponding extended public key. """
        verifying_key = self.signing_key.public_key
        parent_pubkey = self.parent.public_key if self.parent else None
        return PubKey(self.ledger, verifying_key, self.chain_code, self.n, self.depth,
                      parent_pubkey)

    def ec_point(self):
        return self.public_key.ec_point()

    def secret_exponent(self):
        """ Return the private key as a secret exponent. """
        return self.signing_key.to_int()

    def wif(self):
        """ Return the private key encoded in Wallet Import Format. """
        return self.ledger.private_key_to_wif(self.private_key_bytes)

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

        msg = serkey + n.to_bytes(4, 'big')
        L_b, R_b = self._hmac_sha512(msg)  # pylint: disable=invalid-name
        derived_key = self.signing_key.add(L_b)
        return PrivateKey(self.ledger, derived_key, R_b, n, self.depth + 1, self)

    def sign(self, data):
        """ Produce a signature for piece of data by double hashing it and signing the hash. """
        return self.signing_key.sign(data, hasher=double_sha256)

    def identifier(self):
        """Return the key's identifier as 20 bytes."""
        return self.public_key.identifier()

    def extended_key(self):
        """Return a raw extended private key."""
        return self._extended_key(
            self.ledger.extended_private_key_prefix,
            b'\0' + self.private_key_bytes
        )


def _from_extended_key(ledger, ekey):
    """Return a PubKey or PrivateKey from an extended key raw bytes."""
    if not isinstance(ekey, (bytes, bytearray)):
        raise TypeError('extended key must be raw bytes')
    if len(ekey) != 78:
        raise ValueError('extended key must have length 78')

    depth = ekey[4]
    n = int.from_bytes(ekey[9:13], 'big')
    chain_code = ekey[13:45]

    if ekey[:4] == ledger.extended_public_key_prefix:
        pubkey = ekey[45:]
        key = PubKey(ledger, pubkey, chain_code, n, depth)
    elif ekey[:4] == ledger.extended_private_key_prefix:
        if ekey[45] != 0:
            raise ValueError('invalid extended private key prefix byte')
        privkey = ekey[46:]
        key = PrivateKey(ledger, privkey, chain_code, n, depth)
    else:
        raise ValueError('version bytes unrecognised')

    return key


def from_extended_key_string(ledger, ekey_str):
    """Given an extended key string, such as

    xpub6BsnM1W2Y7qLMiuhi7f7dbAwQZ5Cz5gYJCRzTNainXzQXYjFwtuQXHd
    3qfi3t3KJtHxshXezfjft93w4UE7BGMtKwhqEHae3ZA7d823DVrL

    return a PubKey or PrivateKey.
    """
    return _from_extended_key(ledger, Base58.decode_check(ekey_str))
