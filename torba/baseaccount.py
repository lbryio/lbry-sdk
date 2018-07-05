from typing import Dict
from twisted.internet import defer

import torba.baseledger
from torba.mnemonic import Mnemonic
from torba.bip32 import PrivateKey, PubKey, from_extended_key_string
from torba.hash import double_sha256, aes_encrypt, aes_decrypt


class KeyChain:

    def __init__(self, account, parent_key, chain_number, gap, maximum_use_per_address):
        # type: ('BaseAccount', PubKey, int, int, int) -> None
        self.account = account
        self.db = account.ledger.db
        self.main_key = parent_key.child(chain_number)
        self.chain_number = chain_number
        self.gap = gap
        self.maximum_use_per_address = maximum_use_per_address

    def get_addresses(self, limit=None, details=False):
        return self.db.get_addresses(self.account, self.chain_number, limit, details)

    def get_usable_addresses(self, limit=None):
        return self.db.get_usable_addresses(
            self.account, self.chain_number, self.maximum_use_per_address, limit
        )

    @defer.inlineCallbacks
    def generate_keys(self, start, end):
        new_keys = []
        for index in range(start, end+1):
            new_keys.append((index, self.main_key.child(index)))
        yield self.db.add_keys(
            self.account, self.chain_number, new_keys
        )
        defer.returnValue([key[1].address for key in new_keys])

    @defer.inlineCallbacks
    def ensure_address_gap(self):
        addresses = yield self.get_addresses(self.gap, True)

        existing_gap = 0
        for address in addresses:
            if address['used_times'] == 0:
                existing_gap += 1
            else:
                break

        if existing_gap == self.gap:
            defer.returnValue([])

        start = addresses[0]['position']+1 if addresses else 0
        end = start + (self.gap - existing_gap)
        new_keys = yield self.generate_keys(start, end-1)
        defer.returnValue(new_keys)

    @defer.inlineCallbacks
    def get_or_create_usable_address(self):
        addresses = yield self.get_usable_addresses(1)
        if addresses:
            defer.returnValue(addresses[0])
        addresses = yield self.ensure_address_gap()
        defer.returnValue(addresses[0])


class BaseAccount(object):

    mnemonic_class = Mnemonic
    private_key_class = PrivateKey
    public_key_class = PubKey

    def __init__(self, ledger, seed, encrypted, private_key,
                 public_key, receiving_gap=20, change_gap=6,
                 receiving_maximum_use_per_address=2, change_maximum_use_per_address=2):
        # type: (torba.baseledger.BaseLedger, str, bool, PrivateKey, PubKey, int, int, int, int) -> None
        self.ledger = ledger
        self.seed = seed
        self.encrypted = encrypted
        self.private_key = private_key
        self.public_key = public_key
        self.receiving, self.change = self.keychains = (
            KeyChain(self, public_key, 0, receiving_gap, receiving_maximum_use_per_address),
            KeyChain(self, public_key, 1, change_gap, change_maximum_use_per_address)
        )
        ledger.add_account(self)

    @classmethod
    def generate(cls, ledger, password):  # type: (torba.baseledger.BaseLedger, str) -> BaseAccount
        seed = cls.mnemonic_class().make_seed()
        return cls.from_seed(ledger, seed, password)

    @classmethod
    def from_seed(cls, ledger, seed, password):
        # type: (torba.baseledger.BaseLedger, str, str) -> BaseAccount
        private_key = cls.get_private_key_from_seed(ledger, seed, password)
        return cls(
            ledger=ledger, seed=seed, encrypted=False,
            private_key=private_key,
            public_key=private_key.public_key
        )

    @classmethod
    def get_private_key_from_seed(cls, ledger, seed, password):
        # type: (torba.baseledger.BaseLedger, str, str) -> PrivateKey
        return cls.private_key_class.from_seed(
            ledger, cls.mnemonic_class.mnemonic_to_seed(seed, password)
        )

    @classmethod
    def from_dict(cls, ledger, d):  # type: (torba.baseledger.BaseLedger, Dict) -> BaseAccount
        if not d['encrypted']:
            private_key = from_extended_key_string(ledger, d['private_key'])
            public_key = private_key.public_key
        else:
            private_key = d['private_key']
            public_key = from_extended_key_string(ledger, d['public_key'])
        return cls(
            ledger=ledger,
            seed=d['seed'],
            encrypted=d['encrypted'],
            private_key=private_key,
            public_key=public_key,
            receiving_gap=d['receiving_gap'],
            change_gap=d['change_gap'],
            receiving_maximum_use_per_address=d['receiving_maximum_use_per_address'],
            change_maximum_use_per_address=d['change_maximum_use_per_address']
        )

    def to_dict(self):
        return {
            'ledger': self.ledger.get_id(),
            'seed': self.seed,
            'encrypted': self.encrypted,
            'private_key': self.private_key if self.encrypted else
                           self.private_key.extended_key_string().decode(),
            'public_key': self.public_key.extended_key_string().decode(),
            'receiving_gap': self.receiving.gap,
            'change_gap': self.change.gap,
            'receiving_maximum_use_per_address': self.receiving.maximum_use_per_address,
            'change_maximum_use_per_address': self.change.maximum_use_per_address
        }

    def decrypt(self, password):
        assert self.encrypted, "Key is not encrypted."
        secret = double_sha256(password)
        self.seed = aes_decrypt(secret, self.seed)
        self.private_key = from_extended_key_string(self.ledger, aes_decrypt(secret, self.private_key))
        self.encrypted = False

    def encrypt(self, password):
        assert not self.encrypted, "Key is already encrypted."
        secret = double_sha256(password)
        self.seed = aes_encrypt(secret, self.seed)
        self.private_key = aes_encrypt(secret, self.private_key.extended_key_string())
        self.encrypted = True

    @defer.inlineCallbacks
    def ensure_address_gap(self):
        addresses = []
        for keychain in self.keychains:
            new_addresses = yield keychain.ensure_address_gap()
            addresses.extend(new_addresses)
        defer.returnValue(addresses)

    def get_addresses(self, limit=None, details=False):
        return self.ledger.db.get_addresses(self, None, limit, details)

    def get_unused_addresses(self):
        return self.ledger.db.get_unused_addresses(self, None)

    def get_private_key(self, chain, index):
        assert not self.encrypted, "Cannot get private key on encrypted wallet account."
        return self.private_key.child(chain).child(index)

    def get_balance(self):
        return self.ledger.db.get_balance_for_account(self)
