import itertools
from typing import Dict, Generator
from binascii import hexlify, unhexlify

from torba.basecoin import BaseCoin
from torba.mnemonic import Mnemonic
from torba.bip32 import PrivateKey, PubKey, from_extended_key_string
from torba.hash import double_sha256, aes_encrypt, aes_decrypt


class KeyChain:

    def __init__(self, parent_key, child_keys, gap):
        self.coin = parent_key.coin
        self.parent_key = parent_key  # type: PubKey
        self.child_keys = child_keys
        self.minimum_gap = gap
        self.addresses = [
            self.coin.public_key_to_address(key)
            for key in child_keys
        ]

    @property
    def has_gap(self):
        if len(self.addresses) < self.minimum_gap:
            return False
        for address in self.addresses[-self.minimum_gap:]:
            if self.coin.ledger.is_address_old(address):
                return False
        return True

    def generate_next_address(self):
        child_key = self.parent_key.child(len(self.child_keys))
        self.child_keys.append(child_key.pubkey_bytes)
        self.addresses.append(child_key.address)
        return child_key.address

    def ensure_enough_addresses(self):
        starting_length = len(self.addresses)
        while not self.has_gap:
            self.generate_next_address()
        return self.addresses[starting_length:]


class Account:

    def __init__(self, coin, seed, encrypted, private_key, public_key,
                 receiving_keys=None, receiving_gap=20,
                 change_keys=None, change_gap=6):
        self.coin = coin  # type: BaseCoin
        self.seed = seed  # type: str
        self.encrypted = encrypted  # type: bool
        self.private_key = private_key  # type: PrivateKey
        self.public_key = public_key  # type: PubKey
        self.keychains = (
            KeyChain(public_key.child(0), receiving_keys or [], receiving_gap),
            KeyChain(public_key.child(1), change_keys or [], change_gap)
        )
        self.receiving_keys, self.change_keys = self.keychains

    @classmethod
    def generate(cls, coin, password):  # type: (BaseCoin, unicode) -> Account
        seed = Mnemonic().make_seed()
        return cls.from_seed(coin, seed, password)

    @classmethod
    def from_seed(cls, coin, seed, password):  # type: (BaseCoin, unicode, unicode) -> Account
        private_key = cls.get_private_key_from_seed(coin, seed, password)
        return cls(
            coin=coin, seed=seed, encrypted=False,
            private_key=private_key,
            public_key=private_key.public_key
        )

    @staticmethod
    def get_private_key_from_seed(coin, seed, password):  # type: (BaseCoin, unicode, unicode) -> PrivateKey
        return PrivateKey.from_seed(coin, Mnemonic.mnemonic_to_seed(seed, password))

    @classmethod
    def from_dict(cls, coin, d):  # type: (BaseCoin, Dict) -> Account
        if not d['encrypted']:
            private_key = from_extended_key_string(coin, d['private_key'])
            public_key = private_key.public_key
        else:
            private_key = d['private_key']
            public_key = from_extended_key_string(coin, d['public_key'])
        return cls(
            coin=coin,
            seed=d['seed'],
            encrypted=d['encrypted'],
            private_key=private_key,
            public_key=public_key,
            receiving_keys=[unhexlify(k) for k in d['receiving_keys']],
            receiving_gap=d['receiving_gap'],
            change_keys=[unhexlify(k) for k in d['change_keys']],
            change_gap=d['change_gap']
        )

    def to_dict(self):
        return {
            'coin': self.coin.get_id(),
            'seed': self.seed,
            'encrypted': self.encrypted,
            'private_key': self.private_key if self.encrypted else
                           self.private_key.extended_key_string().decode(),
            'public_key': self.public_key.extended_key_string().decode(),
            'receiving_keys': [hexlify(k).decode() for k in self.receiving_keys.child_keys],
            'receiving_gap': self.receiving_keys.minimum_gap,
            'change_keys': [hexlify(k).decode() for k in self.change_keys.child_keys],
            'change_gap': self.change_keys.minimum_gap
        }

    def decrypt(self, password):
        assert self.encrypted, "Key is not encrypted."
        secret = double_sha256(password)
        self.seed = aes_decrypt(secret, self.seed)
        self.private_key = from_extended_key_string(self.coin, aes_decrypt(secret, self.private_key))
        self.encrypted = False

    def encrypt(self, password):
        assert not self.encrypted, "Key is already encrypted."
        secret = double_sha256(password)
        self.seed = aes_encrypt(secret, self.seed)
        self.private_key = aes_encrypt(secret, self.private_key.extended_key_string())
        self.encrypted = True

    @property
    def addresses(self):
        return itertools.chain(self.receiving_keys.addresses, self.change_keys.addresses)

    def get_private_key_for_address(self, address):
        assert not self.encrypted, "Cannot get private key on encrypted wallet account."
        for a, keychain in enumerate(self.keychains):
            for b, match in enumerate(keychain.addresses):
                if address == match:
                    return self.private_key.child(a).child(b)

    def ensure_enough_addresses(self):
        return [
            address
            for keychain in self.keychains
            for address in keychain.ensure_enough_addresses()
        ]

    def addresses_without_history(self):
        for address in self.addresses:
            if not self.coin.ledger.has_address(address):
                yield address

    def get_least_used_receiving_address(self, max_transactions=1000):
        return self._get_least_used_address(
            self.receiving_keys.addresses,
            self.receiving_keys,
            max_transactions
        )

    def get_least_used_change_address(self, max_transactions=100):
        return self._get_least_used_address(
            self.change_keys.addresses,
            self.change_keys,
            max_transactions
        )

    def _get_least_used_address(self, addresses, keychain, max_transactions):
        ledger = self.coin.ledger
        address = ledger.get_least_used_address(addresses, max_transactions)
        if address:
            return address
        address = keychain.generate_next_address()
        ledger.subscribe_history(address)
        return address

    def get_unspent_utxos(self):
        return [
            utxo
            for address in self.addresses
            for utxo in self.coin.ledger.get_unspent_outputs(address)
        ]

    def get_balance(self):
        return sum(utxo.amount for utxo in self.get_unspent_utxos())


class AccountsView:

    def __init__(self, accounts):
        self._accounts_generator = accounts

    def __iter__(self):  # type: () -> Generator[Account]
        return self._accounts_generator()
