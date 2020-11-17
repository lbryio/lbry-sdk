import os
import time
import json
import logging
import asyncio
import random
from functools import partial
from hashlib import sha256
from typing import Type, Dict, Tuple, Optional, Any, List

import ecdsa

from lbry.constants import COIN
from lbry.db import Database, CLAIM_TYPE_CODES, TXO_TYPES
from lbry.db.tables import AccountAddress
from lbry.blockchain import Ledger
from lbry.error import InvalidPasswordError
from lbry.crypto.crypt import aes_encrypt, aes_decrypt
from lbry.crypto.bip32 import PrivateKey, PubKey, from_extended_key_string

from . import mnemonic


log = logging.getLogger(__name__)


class AddressManager:

    name: str

    __slots__ = 'account', 'public_key', 'chain_number', 'address_generator_lock'

    def __init__(self, account: 'Account', public_key, chain_number):
        self.account = account
        self.public_key = public_key
        self.chain_number = chain_number
        self.address_generator_lock = asyncio.Lock()

    @classmethod
    def from_dict(cls, account: 'Account', d: dict) -> Tuple['AddressManager', 'AddressManager']:
        raise NotImplementedError

    @classmethod
    def to_dict(cls, receiving: 'AddressManager', change: 'AddressManager') -> Dict:
        d: Dict[str, Any] = {'name': cls.name}
        receiving_dict = receiving.to_dict_instance()
        if receiving_dict:
            d['receiving'] = receiving_dict
        change_dict = change.to_dict_instance()
        if change_dict:
            d['change'] = change_dict
        return d

    def merge(self, d: dict):
        pass

    def to_dict_instance(self) -> Optional[dict]:
        raise NotImplementedError

    async def _query_addresses(self, **constraints):
        return await self.account.db.get_addresses(
            account=self.account,
            chain=self.chain_number,
            **constraints
        )

    def get_private_key(self, index: int) -> PrivateKey:
        raise NotImplementedError

    def get_public_key(self, index: int) -> PubKey:
        raise NotImplementedError

    async def get_max_gap(self):
        raise NotImplementedError

    async def ensure_address_gap(self):
        raise NotImplementedError

    async def get_address_records(self, only_usable: bool = False, **constraints):
        raise NotImplementedError

    async def get_addresses(self, only_usable: bool = False, **constraints) -> List[str]:
        records = await self.get_address_records(only_usable=only_usable, **constraints)
        return [r['address'] for r in records]

    async def get_or_create_usable_address(self) -> str:
        addresses = await self.get_addresses(only_usable=True, limit=10)
        if addresses:
            return random.choice(addresses)
        addresses = await self.ensure_address_gap()
        return addresses[0]


class HierarchicalDeterministic(AddressManager):
    """ Implements simple version of Bitcoin Hierarchical Deterministic key management. """

    name: str = "deterministic-chain"

    __slots__ = 'gap', 'maximum_uses_per_address'

    def __init__(self, account: 'Account', chain: int, gap: int, maximum_uses_per_address: int) -> None:
        super().__init__(account, account.public_key.child(chain), chain)
        self.gap = gap
        self.maximum_uses_per_address = maximum_uses_per_address

    @classmethod
    def from_dict(cls, account: 'Account', d: dict) -> Tuple[AddressManager, AddressManager]:
        return (
            cls(account, 0, **d.get('receiving', {'gap': 20, 'maximum_uses_per_address': 1})),
            cls(account, 1, **d.get('change', {'gap': 6, 'maximum_uses_per_address': 1}))
        )

    def merge(self, d: dict):
        self.gap = d.get('gap', self.gap)
        self.maximum_uses_per_address = d.get('maximum_uses_per_address', self.maximum_uses_per_address)

    def to_dict_instance(self):
        return {'gap': self.gap, 'maximum_uses_per_address': self.maximum_uses_per_address}

    def get_private_key(self, index: int) -> PrivateKey:
        return self.account.private_key.child(self.chain_number).child(index)

    def get_public_key(self, index: int) -> PubKey:
        return self.account.public_key.child(self.chain_number).child(index)

    async def get_max_gap(self) -> int:
        addresses = await self._query_addresses(order_by="n asc")
        max_gap = 0
        current_gap = 0
        for address in addresses:
            if address['used_times'] == 0:
                current_gap += 1
            else:
                max_gap = max(max_gap, current_gap)
                current_gap = 0
        return max_gap

    async def ensure_address_gap(self) -> List[str]:
        async with self.address_generator_lock:
            addresses = await self._query_addresses(limit=self.gap, order_by="n desc")

            existing_gap = 0
            for address in addresses:
                if address['used_times'] == 0:
                    existing_gap += 1
                else:
                    break

            if existing_gap == self.gap:
                return []

            start = addresses[0]['pubkey'].n+1 if addresses else 0
            end = start + (self.gap - existing_gap)
            new_keys = await self._generate_keys(start, end-1)
            #await self.account.ledger.announce_addresses(self, new_keys)
            return new_keys

    async def _generate_keys(self, start: int, end: int) -> List[str]:
        if not self.address_generator_lock.locked():
            raise RuntimeError('Should not be called outside of address_generator_lock.')
        keys = [self.public_key.child(index) for index in range(start, end+1)]
        await self.account.db.add_keys(self.account, self.chain_number, keys)
        return [key.address for key in keys]

    async def get_address_records(self, only_usable: bool = False, **constraints):
        if only_usable:
            constraints['used_times__lt'] = self.maximum_uses_per_address
        if 'order_by' not in constraints:
            constraints['order_by'] = "used_times asc, n asc"
        return await self._query_addresses(**constraints)


class SingleKey(AddressManager):
    """ Single Key address manager always returns the same address for all operations. """

    name: str = "single-address"

    __slots__ = ()

    @classmethod
    def from_dict(cls, account: 'Account', d: dict) \
            -> Tuple[AddressManager, AddressManager]:
        same_address_manager = cls(account, account.public_key, 0)
        return same_address_manager, same_address_manager

    def to_dict_instance(self):
        return None

    def get_private_key(self, index: int) -> PrivateKey:
        return self.account.private_key

    def get_public_key(self, index: int) -> PubKey:
        return self.account.public_key

    async def get_max_gap(self) -> int:
        return 0

    async def ensure_address_gap(self) -> List[str]:
        async with self.address_generator_lock:
            exists = await self.get_address_records()
            if not exists:
                await self.account.db.add_keys(self.account, self.chain_number, [self.public_key])
                new_keys = [self.public_key.address]
                #await self.account.ledger.announce_addresses(self, new_keys)
                return new_keys
            return []

    async def get_address_records(self, only_usable: bool = False, **constraints):
        return await self._query_addresses(**constraints)


class Account:
    address_generators: Dict[str, Type[AddressManager]] = {
        SingleKey.name: SingleKey,
        HierarchicalDeterministic.name: HierarchicalDeterministic,
    }

    def __init__(self, db: Database, name: str,
                 phrase: str, language: str, private_key_string: str,
                 encrypted: bool, private_key: Optional[PrivateKey], public_key: PubKey,
                 address_generator: dict, modified_on: float, channel_keys: dict) -> None:
        self.db = db
        self.ledger = db.ledger
        self.id = public_key.address
        self.name = name
        self.phrase = phrase
        self.language = language
        self.modified_on = modified_on
        self.private_key_string = private_key_string
        self.init_vectors: Dict[str, bytes] = {}
        self.encrypted = encrypted
        self.private_key = private_key
        self.public_key = public_key
        generator_name = address_generator.get('name', HierarchicalDeterministic.name)
        self.address_generator = self.address_generators[generator_name]
        self.receiving, self.change = self.address_generator.from_dict(self, address_generator)
        self.address_managers = {am.chain_number: am for am in {self.receiving, self.change}}
        self.channel_keys = channel_keys
        self._channel_keys_deserialized = {}

    def get_init_vector(self, key) -> Optional[bytes]:
        init_vector = self.init_vectors.get(key, None)
        if init_vector is None:
            init_vector = self.init_vectors[key] = os.urandom(16)
        return init_vector

    @classmethod
    async def generate(
        cls, db: Database, name: str = None,
        language: str = 'en', address_generator: dict = None
    ):
        return await cls.from_dict(db, {
            'name': name,
            'seed': await mnemonic.generate_phrase(language),
            'language': language,
            'address_generator': address_generator or {}
        })

    @classmethod
    async def keys_from_dict(cls, ledger: Ledger, d: dict) -> Tuple[str, Optional[PrivateKey], PubKey]:
        phrase = d.get('seed', '')
        private_key_string = d.get('private_key', '')
        private_key = None
        public_key = None
        encrypted = d.get('encrypted', False)
        if not encrypted:
            if phrase:
                private_key = PrivateKey.from_seed(
                    ledger, await mnemonic.derive_key_from_phrase(phrase)
                )
                public_key = private_key.public_key
            elif private_key_string:
                private_key = from_extended_key_string(ledger, private_key_string)
                public_key = private_key.public_key
        if public_key is None:
            public_key = from_extended_key_string(ledger, d['public_key'])
        return phrase, private_key, public_key

    @classmethod
    async def from_dict(cls, db: Database, d: dict):
        phrase, private_key, public_key = await cls.keys_from_dict(db.ledger, d)
        name = d.get('name')
        if not name:
            name = f'Account #{public_key.address}'
        return cls(
            db=db,
            name=name,
            phrase=phrase,
            language=d.get('lang', 'en'),
            private_key_string=d.get('private_key', ''),
            encrypted=d.get('encrypted', False),
            private_key=private_key,
            public_key=public_key,
            address_generator=d.get('address_generator', {}),
            modified_on=d.get('modified_on', time.time()),
            channel_keys=d.get('certificates', {})
        )

    def to_dict(self, encrypt_password: str = None, include_channel_keys: bool = True):
        private_key_string, phrase = self.private_key_string, self.phrase
        if not self.encrypted and self.private_key:
            private_key_string = self.private_key.extended_key_string()
        if not self.encrypted and encrypt_password:
            if private_key_string:
                private_key_string = aes_encrypt(
                    encrypt_password, private_key_string, self.get_init_vector('private_key')
                )
            if phrase:
                phrase = aes_encrypt(encrypt_password, self.phrase, self.get_init_vector('phrase'))
        d = {
            'name': self.name,
            'seed': phrase,
            'lang': self.language,
            'encrypted': bool(self.encrypted or encrypt_password),
            'private_key': private_key_string,
            'public_key': self.public_key.extended_key_string(),
            'address_generator': self.address_generator.to_dict(self.receiving, self.change),
            'modified_on': self.modified_on
        }
        if include_channel_keys:
            d['certificates'] = self.channel_keys
        return d

    def merge(self, d: dict):
        if d.get('modified_on', 0) > self.modified_on:
            self.name = d['name']
            self.modified_on = d.get('modified_on', time.time())
            assert self.address_generator.name == d['address_generator']['name']
            for chain_name in ('change', 'receiving'):
                if chain_name in d['address_generator']:
                    chain_object = getattr(self, chain_name)
                    chain_object.merge(d['address_generator'][chain_name])
        self.channel_keys.update(d.get('certificates', {}))

    @property
    def hash(self) -> bytes:
        assert not self.encrypted, "Cannot hash an encrypted account."
        h = sha256(json.dumps(self.to_dict(include_channel_keys=False)).encode())
        for cert in sorted(self.channel_keys.keys()):
            h.update(cert.encode())
        return h.digest()

    async def get_details(self, show_seed=False, **kwargs):
        satoshis = await self.get_balance(**kwargs)
        details = {
            'id': self.id,
            'name': self.name,
            'coins': round(satoshis/COIN, 2),
            'satoshis': satoshis,
            'encrypted': self.encrypted,
            'public_key': self.public_key.extended_key_string(),
            'address_generator': self.address_generator.to_dict(self.receiving, self.change)
        }
        if show_seed:
            details['seed'] = self.phrase
        details['certificates'] = len(self.channel_keys)
        return details

    def decrypt(self, password: str) -> bool:
        assert self.encrypted, "Key is not encrypted."
        try:
            phrase = self._decrypt_phrase(password)
        except (ValueError, InvalidPasswordError):
            return False
        try:
            private_key = self._decrypt_private_key_string(password)
        except (TypeError, ValueError, InvalidPasswordError):
            return False
        self.phrase = phrase
        self.private_key = private_key
        self.private_key_string = ""
        self.encrypted = False
        return True

    def _decrypt_private_key_string(self, password: str) -> Optional[PrivateKey]:
        if not self.private_key_string:
            return None
        private_key_string, self.init_vectors['private_key'] = aes_decrypt(password, self.private_key_string)
        if not private_key_string:
            return None
        return from_extended_key_string(
            self.ledger, private_key_string
        )

    def _decrypt_phrase(self, password: str) -> str:
        if not self.phrase:
            return ""
        phrase, self.init_vectors['phrase'] = aes_decrypt(password, self.phrase)
        if not phrase:
            return ""
        if not mnemonic.is_phrase_valid(self.language, phrase):
            raise ValueError("Failed to decode seed phrase.")
        return phrase

    def encrypt(self, password: str) -> bool:
        assert not self.encrypted, "Key is already encrypted."
        if self.phrase:
            self.phrase = aes_encrypt(password, self.phrase, self.get_init_vector('phrase'))
        if isinstance(self.private_key, PrivateKey):
            self.private_key_string = aes_encrypt(
                password, self.private_key.extended_key_string(), self.get_init_vector('private_key')
            )
            self.private_key = None
        self.encrypted = True
        return True

    async def ensure_address_gap(self):
        addresses = []
        for address_manager in self.address_managers.values():
            new_addresses = await address_manager.ensure_address_gap()
            addresses.extend(new_addresses)
        return addresses

    async def get_address_records(self, **constraints):
        return await self.db.get_addresses(account=self, **constraints)

    async def get_addresses(self, **constraints) -> List[str]:
        rows = await self.get_address_records(cols=[AccountAddress.c.address], **constraints)
        return [r['address'] for r in rows]

    async def get_valid_receiving_address(self, default_address: str) -> str:
        if default_address is None:
            return await self.receiving.get_or_create_usable_address()
        self.ledger.valid_address_or_error(default_address)
        return default_address

    def get_private_key(self, chain: int, index: int) -> PrivateKey:
        assert not self.encrypted, "Cannot get private key on encrypted wallet account."
        return self.address_managers[chain].get_private_key(index)

    def get_public_key(self, chain: int, index: int) -> PubKey:
        return self.address_managers[chain].get_public_key(index)

    async def get_max_gap(self):
        change_gap = await self.change.get_max_gap()
        receiving_gap = await self.receiving.get_max_gap()
        return {
            'max_change_gap': change_gap,
            'max_receiving_gap': receiving_gap,
        }

    def add_channel_private_key(self, private_key):
        public_key_bytes = private_key.get_verifying_key().to_der()
        channel_pubkey_hash = self.ledger.public_key_to_address(public_key_bytes)
        self.channel_keys[channel_pubkey_hash] = private_key.to_pem().decode()
        self._channel_keys_deserialized[channel_pubkey_hash] = private_key

    async def get_channel_private_key(self, public_key_bytes):
        channel_pubkey_hash = self.ledger.public_key_to_address(public_key_bytes)
        private_key = self._channel_keys_deserialized.get(channel_pubkey_hash)
        if private_key:
            return private_key
        private_key_pem = self.channel_keys.get(channel_pubkey_hash)
        if private_key_pem:
            private_key = await asyncio.get_running_loop().run_in_executor(
                None, ecdsa.SigningKey.from_pem, private_key_pem, sha256
            )
            self._channel_keys_deserialized[channel_pubkey_hash] = private_key
            return private_key

    async def maybe_migrate_certificates(self):
        def to_der(private_key_pem):
            return ecdsa.SigningKey.from_pem(private_key_pem, hashfunc=sha256).get_verifying_key().to_der()

        if not self.channel_keys:
            return
        channel_keys = {}
        for private_key_pem in self.channel_keys.values():
            if not isinstance(private_key_pem, str):
                continue
            if "-----BEGIN EC PRIVATE KEY-----" not in private_key_pem:
                continue
            public_key_der = await asyncio.get_running_loop().run_in_executor(None, to_der, private_key_pem)
            channel_keys[self.ledger.public_key_to_address(public_key_der)] = private_key_pem
        if self.channel_keys != channel_keys:
            self.channel_keys = channel_keys

    async def save_max_gap(self):
        gap_changed = False
        if issubclass(self.address_generator, HierarchicalDeterministic):
            gap = await self.get_max_gap()
            new_receiving_gap = max(20, gap['max_receiving_gap'] + 1)
            if self.receiving.gap != new_receiving_gap:
                self.receiving.gap = new_receiving_gap
                gap_changed = True
            new_change_gap = max(6, gap['max_change_gap'] + 1)
            if self.change.gap != new_change_gap:
                self.change.gap = new_change_gap
                gap_changed = True
        return gap_changed

    async def get_balance(self, **constraints):
        return await self.db.get_balance(account=self, **constraints)
