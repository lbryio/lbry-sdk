from typing import Dict
from twisted.internet import defer

import torba.baseledger
from torba.mnemonic import Mnemonic
from torba.bip32 import PrivateKey, PubKey, from_extended_key_string
from torba.hash import double_sha256, aes_encrypt, aes_decrypt


class KeyManager(object):

    __slots__ = 'account', 'public_key', 'chain_number'

    def __init__(self, account, public_key, chain_number):
        self.account = account
        self.public_key = public_key
        self.chain_number = chain_number

    @property
    def db(self):
        return self.account.ledger.db

    def _query_addresses(self, limit=None, max_used_times=None, order_by=None):
        return self.db.get_addresses(
            self.account, self.chain_number, limit, max_used_times, order_by
        )

    def ensure_address_gap(self):  # type: () -> defer.Deferred
        raise NotImplementedError

    def get_address_records(self, limit=None, only_usable=False):  # type: (int, bool) -> defer.Deferred
        raise NotImplementedError

    @defer.inlineCallbacks
    def get_addresses(self, limit=None, only_usable=False):  # type: (int, bool) -> defer.Deferred
        records = yield self.get_address_records(limit=limit, only_usable=only_usable)
        defer.returnValue([r['address'] for r in records])

    @defer.inlineCallbacks
    def get_or_create_usable_address(self):  # type: () -> defer.Deferred
        addresses = yield self.get_addresses(limit=1, only_usable=True)
        if addresses:
            defer.returnValue(addresses[0])
        addresses = yield self.ensure_address_gap()
        defer.returnValue(addresses[0])


class KeyChain(KeyManager):
    """ Implements simple version of Bitcoin Hierarchical Deterministic key management. """

    __slots__ = 'gap', 'maximum_uses_per_address'

    def __init__(self, account, root_public_key, chain_number, gap, maximum_uses_per_address):
        # type: ('BaseAccount', PubKey, int, int, int) -> None
        super(KeyChain, self).__init__(account, root_public_key.child(chain_number), chain_number)
        self.gap = gap
        self.maximum_uses_per_address = maximum_uses_per_address

    @defer.inlineCallbacks
    def generate_keys(self, start, end):
        new_keys = []
        for index in range(start, end+1):
            new_keys.append((index, self.public_key.child(index)))
        yield self.db.add_keys(
            self.account, self.chain_number, new_keys
        )
        defer.returnValue([key[1].address for key in new_keys])

    @defer.inlineCallbacks
    def ensure_address_gap(self):
        addresses = yield self._query_addresses(self.gap, None, "position DESC")

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

    def get_address_records(self, limit=None, only_usable=False):
        return self._query_addresses(
            limit, self.maximum_uses_per_address if only_usable else None,
            "used_times ASC, position ASC"
        )


class SingleKey(KeyManager):
    """ Single Key manager always returns the same address for all operations. """

    __slots__ = ()

    def __init__(self, account, root_public_key, chain_number):
        # type: ('BaseAccount', PubKey) -> None
        super(SingleKey, self).__init__(account, root_public_key, chain_number)

    @defer.inlineCallbacks
    def ensure_address_gap(self):
        exists = yield self.get_address_records()
        if not exists:
            yield self.db.add_keys(
                self.account, self.chain_number, [(0, self.public_key)]
            )
            defer.returnValue([self.public_key.address])
        defer.returnValue([])

    def get_address_records(self, **kwargs):
        return self._query_addresses()


class BaseAccount(object):

    mnemonic_class = Mnemonic
    private_key_class = PrivateKey
    public_key_class = PubKey

    def __init__(self, ledger, name, seed, encrypted, is_hd, private_key,
                 public_key, receiving_gap=20, change_gap=6,
                 receiving_maximum_uses_per_address=2, change_maximum_uses_per_address=2):
        # type: (torba.baseledger.BaseLedger, str, str, bool, bool, PrivateKey, PubKey, int, int, int, int) -> None
        self.ledger = ledger
        self.name = name
        self.seed = seed
        self.encrypted = encrypted
        self.private_key = private_key
        self.public_key = public_key
        if is_hd:
            receiving, change = self.keychains = (
                KeyChain(self, public_key, 0, receiving_gap, receiving_maximum_uses_per_address),
                KeyChain(self, public_key, 1, change_gap, change_maximum_uses_per_address)
            )
        else:
            self.keychains = SingleKey(self, public_key, 0),
            receiving = change = self.keychains[0]
        self.receiving = receiving  # type: KeyManager
        self.change = change  # type: KeyManager
        ledger.add_account(self)

    @classmethod
    def generate(cls, ledger, password, **kwargs):  # type: (torba.baseledger.BaseLedger, str) -> BaseAccount
        seed = cls.mnemonic_class().make_seed()
        return cls.from_seed(ledger, seed, password, **kwargs)

    @classmethod
    def from_seed(cls, ledger, seed, password, is_hd=True, **kwargs):
        # type: (torba.baseledger.BaseLedger, str, str) -> BaseAccount
        private_key = cls.get_private_key_from_seed(ledger, seed, password)
        return cls(
            ledger=ledger, name='Account #{}'.format(private_key.public_key.address),
            seed=seed, encrypted=False, is_hd=is_hd,
            private_key=private_key,
            public_key=private_key.public_key,
            **kwargs
        )

    @classmethod
    def get_private_key_from_seed(cls, ledger, seed, password):
        # type: (torba.baseledger.BaseLedger, str, str) -> PrivateKey
        return cls.private_key_class.from_seed(
            ledger, cls.mnemonic_class.mnemonic_to_seed(seed, password)
        )

    @classmethod
    def from_dict(cls, ledger, d):  # type: (torba.baseledger.BaseLedger, Dict) -> BaseAccount
        if not d['encrypted'] and d['private_key']:
            private_key = from_extended_key_string(ledger, d['private_key'])
            public_key = private_key.public_key
        else:
            private_key = d['private_key']
            public_key = from_extended_key_string(ledger, d['public_key'])

        kwargs = dict(
            ledger=ledger,
            name=d['name'],
            seed=d['seed'],
            encrypted=d['encrypted'],
            private_key=private_key,
            public_key=public_key,
            is_hd=False
        )

        if d['is_hd']:
            kwargs.update(dict(
                receiving_gap=d['receiving_gap'],
                change_gap=d['change_gap'],
                receiving_maximum_uses_per_address=d['receiving_maximum_uses_per_address'],
                change_maximum_uses_per_address=d['change_maximum_uses_per_address'],
                is_hd=True
            ))

        return cls(**kwargs)

    def to_dict(self):
        private_key = self.private_key
        if not self.encrypted and self.private_key:
            private_key = self.private_key.extended_key_string().decode()

        d = {
            'ledger': self.ledger.get_id(),
            'name': self.name,
            'seed': self.seed,
            'encrypted': self.encrypted,
            'private_key': private_key,
            'public_key': self.public_key.extended_key_string().decode(),
            'is_hd': False
        }

        if isinstance(self.receiving, KeyChain) and isinstance(self.change, KeyChain):
            d.update({
                'receiving_gap': self.receiving.gap,
                'change_gap': self.change.gap,
                'receiving_maximum_uses_per_address': self.receiving.maximum_uses_per_address,
                'change_maximum_uses_per_address': self.change.maximum_uses_per_address,
                'is_hd': True
            })

        return d

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

    @defer.inlineCallbacks
    def get_addresses(self, limit=None, max_used_times=None):  # type: (int, int) -> defer.Deferred
        records = yield self.get_address_records(limit, max_used_times)
        defer.returnValue([r['address'] for r in records])

    def get_address_records(self, limit=None, max_used_times=None):  # type: (int, int) -> defer.Deferred
        return self.ledger.db.get_addresses(self, None, limit, max_used_times)

    def get_private_key(self, chain, index):
        assert not self.encrypted, "Cannot get private key on encrypted wallet account."
        if isinstance(self.receiving, SingleKey):
            return self.private_key
        else:
            return self.private_key.child(chain).child(index)

    def get_balance(self, confirmations, **constraints):
        if confirmations == 0:
            return self.ledger.db.get_balance_for_account(self, **constraints)
        else:
            height = self.ledger.headers.height - (confirmations-1)
            return self.ledger.db.get_balance_for_account(
                self, height__lte=height, height__not=-1, **constraints
            )

    def get_unspent_outputs(self, **constraints):
        return self.ledger.db.get_utxos_for_account(self, **constraints)
