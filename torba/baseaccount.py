from typing import Dict
from binascii import unhexlify
from twisted.internet import defer

from torba.mnemonic import Mnemonic
from torba.bip32 import PrivateKey, PubKey, from_extended_key_string
from torba.hash import double_sha256, aes_encrypt, aes_decrypt


class KeyChain:

    def __init__(self, account, parent_key, chain_number, minimum_usable_addresses):
        self.account = account
        self.db = account.ledger.db
        self.main_key = parent_key.child(chain_number)  # type: PubKey
        self.chain_number = chain_number
        self.minimum_usable_addresses = minimum_usable_addresses

    def get_keys(self):
        return self.db.get_keys(self.account, self.chain_number)

    def get_addresses(self):
        return self.db.get_addresses(self.account, self.chain_number)

    @defer.inlineCallbacks
    def ensure_enough_useable_addresses(self):
        usable_address_count = yield self.db.get_usable_address_count(
            self.account, self.chain_number
        )

        if usable_address_count >= self.minimum_usable_addresses:
            defer.returnValue([])

        new_addresses_needed = self.minimum_usable_addresses - usable_address_count

        start = yield self.db.get_last_address_index(
            self.account, self.chain_number
        )
        end = start + new_addresses_needed

        new_keys = []
        for index in range(start+1, end+1):
            new_keys.append((index, self.main_key.child(index)))

        yield self.db.add_keys(
            self.account, self.chain_number, new_keys
        )

        defer.returnValue([
            key[1].address for key in new_keys
        ])

    @defer.inlineCallbacks
    def has_gap(self):
        if len(self.addresses) < self.minimum_gap:
            defer.returnValue(False)
        for address in self.addresses[-self.minimum_gap:]:
            if (yield self.ledger.is_address_old(address)):
                defer.returnValue(False)
        defer.returnValue(True)


class BaseAccount:

    mnemonic_class = Mnemonic
    private_key_class = PrivateKey
    public_key_class = PubKey

    def __init__(self, ledger, seed, encrypted, private_key,
                 public_key, receiving_gap=20, change_gap=6):
        self.ledger = ledger  # type: baseledger.BaseLedger
        self.seed = seed  # type: str
        self.encrypted = encrypted  # type: bool
        self.private_key = private_key  # type: PrivateKey
        self.public_key = public_key  # type: PubKey
        self.receiving, self.change = self.keychains = (
            KeyChain(self, public_key, 0, receiving_gap),
            KeyChain(self, public_key, 1, change_gap)
        )
        ledger.account_created(self)

    @classmethod
    def generate(cls, ledger, password):  # type: (baseledger.BaseLedger, str) -> BaseAccount
        seed = cls.mnemonic_class().make_seed()
        return cls.from_seed(ledger, seed, password)

    @classmethod
    def from_seed(cls, ledger, seed, password):
        # type: (baseledger.BaseLedger, str, str) -> BaseAccount
        private_key = cls.get_private_key_from_seed(ledger, seed, password)
        return cls(
            ledger=ledger, seed=seed, encrypted=False,
            private_key=private_key,
            public_key=private_key.public_key
        )

    @classmethod
    def get_private_key_from_seed(cls, ledger, seed, password):
        # type: (baseledger.BaseLedger, str, str) -> PrivateKey
        return cls.private_key_class.from_seed(
            ledger, cls.mnemonic_class.mnemonic_to_seed(seed, password)
        )

    @classmethod
    def from_dict(cls, ledger, d):  # type: (baseledger.BaseLedger, Dict) -> BaseAccount
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
            change_gap=d['change_gap']
        )

    def to_dict(self):
        return {
            'ledger': self.ledger.get_id(),
            'seed': self.seed,
            'encrypted': self.encrypted,
            'private_key': self.private_key if self.encrypted else
                           self.private_key.extended_key_string(),
            'public_key': self.public_key.extended_key_string(),
            'receiving_gap': self.receiving.minimum_usable_addresses,
            'change_gap': self.change.minimum_usable_addresses,
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
    def ensure_enough_useable_addresses(self):
        addresses = []
        for keychain in self.keychains:
            new_addresses = yield keychain.ensure_enough_useable_addresses()
            addresses.extend(new_addresses)
        defer.returnValue(addresses)

    def get_private_key(self, chain, index):
        assert not self.encrypted, "Cannot get private key on encrypted wallet account."
        return self.private_key.child(chain).child(index)

    def get_least_used_receiving_address(self, max_transactions=1000):
        return self._get_least_used_address(
            self.receiving_keys,
            max_transactions
        )

    def get_least_used_change_address(self, max_transactions=100):
        return self._get_least_used_address(
            self.change_keys,
            max_transactions
        )

    def _get_least_used_address(self, keychain, max_transactions):
        ledger = self.ledger
        address = ledger.get_least_used_address(self, keychain, max_transactions)
        if address:
            return address
        address = keychain.generate_next_address()
        ledger.subscribe_history(address)
        return address

    @defer.inlineCallbacks
    def get_balance(self):
        utxos = yield self.ledger.get_unspent_outputs(self)
        defer.returnValue(sum(utxo.amount for utxo in utxos))
