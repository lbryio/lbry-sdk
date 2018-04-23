from binascii import hexlify, unhexlify
from itertools import chain
from lbrynet.wallet import get_wallet_manager
from lbrynet.wallet.mnemonic import Mnemonic
from lbrynet.wallet.bip32 import PrivateKey, PubKey, from_extended_key_string
from lbrynet.wallet.hash import double_sha256, aes_encrypt, aes_decrypt

from lbryschema.address import public_key_to_address


class KeyChain:

    def __init__(self, parent_key, child_keys, gap):
        self.parent_key = parent_key  # type: PubKey
        self.child_keys = child_keys
        self.minimum_gap = gap
        self.addresses = [
            public_key_to_address(key)
            for key in child_keys
        ]

    @property
    def has_gap(self):
        if len(self.addresses) < self.minimum_gap:
            return False
        ledger = get_wallet_manager().ledger
        for address in self.addresses[-self.minimum_gap:]:
            if ledger.is_address_old(address):
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

    def __init__(self, seed, encrypted, private_key, public_key, **kwargs):
        self.seed = seed
        self.encrypted = encrypted
        self.private_key = private_key  # type: PrivateKey
        self.public_key = public_key  # type: PubKey
        self.receiving_gap = kwargs.get('receiving_gap', 20)
        self.receiving_keys = kwargs.get('receiving_keys') or \
            KeyChain(self.public_key.child(0), [], self.receiving_gap)
        self.change_gap = kwargs.get('change_gap', 6)
        self.change_keys = kwargs.get('change_keys') or \
            KeyChain(self.public_key.child(1), [], self.change_gap)
        self.keychains = [
            self.receiving_keys,  # child: 0
            self.change_keys      # child: 1
        ]

    @classmethod
    def generate(cls):
        seed = Mnemonic().make_seed()
        return cls.generate_from_seed(seed)

    @classmethod
    def generate_from_seed(cls, seed):
        private_key = cls.get_private_key_from_seed(seed)
        return cls(
            seed=seed, encrypted=False,
            private_key=private_key,
            public_key=private_key.public_key,
        )

    @classmethod
    def from_json(cls, json_data):
        data = json_data.copy()
        if not data['encrypted']:
            data['private_key'] = from_extended_key_string(data['private_key'])
        data['public_key'] = from_extended_key_string(data['public_key'])
        data['receiving_keys'] = KeyChain(
            data['public_key'].child(0),
            [unhexlify(k) for k in data['receiving_keys']],
            data['receiving_gap']
        )
        data['change_keys'] = KeyChain(
            data['public_key'].child(1),
            [unhexlify(k) for k in data['change_keys']],
            data['change_gap']
        )
        return cls(**data)

    def to_json(self):
        return {
            'seed': self.seed,
            'encrypted': self.encrypted,
            'private_key': self.private_key.extended_key_string(),
            'public_key': self.public_key.extended_key_string(),
            'receiving_keys': [hexlify(k) for k in self.receiving_keys.child_keys],
            'receiving_gap': self.receiving_gap,
            'change_keys': [hexlify(k) for k in self.change_keys.child_keys],
            'change_gap': self.change_gap
        }

    def decrypt(self, password):
        assert self.encrypted, "Key is not encrypted."
        secret = double_sha256(password)
        self.seed = aes_decrypt(secret, self.seed)
        self.private_key = from_extended_key_string(aes_decrypt(secret, self.private_key))
        self.encrypted = False

    def encrypt(self, password):
        assert not self.encrypted, "Key is already encrypted."
        secret = double_sha256(password)
        self.seed = aes_encrypt(secret, self.seed)
        self.private_key = aes_encrypt(secret, self.private_key.extended_key_string())
        self.encrypted = True

    @staticmethod
    def get_private_key_from_seed(seed):
        return PrivateKey.from_seed(Mnemonic.mnemonic_to_seed(seed))

    @property
    def addresses(self):
        return chain(self.receiving_keys.addresses, self.change_keys.addresses)

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
