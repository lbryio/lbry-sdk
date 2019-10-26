import os
import json
import time
import asyncio
import random
import typing
from typing import Dict, Tuple, Type, Optional, Any, List

from torba.client.mnemonic import Mnemonic
from torba.client.bip32 import PrivateKey, PubKey, from_extended_key_string
from torba.client.hash import aes_encrypt, aes_decrypt, sha256
from torba.client.constants import COIN

if typing.TYPE_CHECKING:
    from torba.client import baseledger, wallet as basewallet


class AddressManager:

    name: str

    __slots__ = 'account', 'public_key', 'chain_number', 'address_generator_lock'

    def __init__(self, account, public_key, chain_number):
        self.account = account
        self.public_key = public_key
        self.chain_number = chain_number
        self.address_generator_lock = asyncio.Lock()

    @classmethod
    def from_dict(cls, account: 'BaseAccount', d: dict) \
            -> Tuple['AddressManager', 'AddressManager']:
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

    def _query_addresses(self, **constraints):
        return self.account.ledger.db.get_addresses(
            accounts=[self.account],
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

    def get_address_records(self, only_usable: bool = False, **constraints):
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

    def __init__(self, account: 'BaseAccount', chain: int, gap: int, maximum_uses_per_address: int) -> None:
        super().__init__(account, account.public_key.child(chain), chain)
        self.gap = gap
        self.maximum_uses_per_address = maximum_uses_per_address

    @classmethod
    def from_dict(cls, account: 'BaseAccount', d: dict) -> Tuple[AddressManager, AddressManager]:
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
            await self.account.ledger.announce_addresses(self, new_keys)
            return new_keys

    async def _generate_keys(self, start: int, end: int) -> List[str]:
        if not self.address_generator_lock.locked():
            raise RuntimeError('Should not be called outside of address_generator_lock.')
        keys = [self.public_key.child(index) for index in range(start, end+1)]
        await self.account.ledger.db.add_keys(self.account, self.chain_number, keys)
        return [key.address for key in keys]

    def get_address_records(self, only_usable: bool = False, **constraints):
        if only_usable:
            constraints['used_times__lt'] = self.maximum_uses_per_address
        if 'order_by' not in constraints:
            constraints['order_by'] = "used_times asc, n asc"
        return self._query_addresses(**constraints)


class SingleKey(AddressManager):
    """ Single Key address manager always returns the same address for all operations. """

    name: str = "single-address"

    __slots__ = ()

    @classmethod
    def from_dict(cls, account: 'BaseAccount', d: dict)\
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
                await self.account.ledger.db.add_keys(self.account, self.chain_number, [self.public_key])
                new_keys = [self.public_key.address]
                await self.account.ledger.announce_addresses(self, new_keys)
                return new_keys
            return []

    def get_address_records(self, only_usable: bool = False, **constraints):
        return self._query_addresses(**constraints)


class BaseAccount:

    mnemonic_class = Mnemonic
    private_key_class = PrivateKey
    public_key_class = PubKey
    address_generators: Dict[str, Type[AddressManager]] = {
        SingleKey.name: SingleKey,
        HierarchicalDeterministic.name: HierarchicalDeterministic,
    }

    def __init__(self, ledger: 'baseledger.BaseLedger', wallet: 'basewallet.Wallet', name: str,
                 seed: str, private_key_string: str, encrypted: bool,
                 private_key: Optional[PrivateKey], public_key: PubKey,
                 address_generator: dict, modified_on: float) -> None:
        self.ledger = ledger
        self.wallet = wallet
        self.id = public_key.address
        self.name = name
        self.seed = seed
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
        ledger.add_account(self)
        wallet.add_account(self)

    def get_init_vector(self, key) -> Optional[bytes]:
        init_vector = self.init_vectors.get(key, None)
        if init_vector is None:
            init_vector = self.init_vectors[key] = os.urandom(16)
        return init_vector

    @classmethod
    def generate(cls, ledger: 'baseledger.BaseLedger', wallet: 'basewallet.Wallet',
                 name: str = None, address_generator: dict = None):
        return cls.from_dict(ledger, wallet, {
            'name': name,
            'seed': cls.mnemonic_class().make_seed(),
            'address_generator': address_generator or {}
        })

    @classmethod
    def get_private_key_from_seed(cls, ledger: 'baseledger.BaseLedger', seed: str, password: str):
        return cls.private_key_class.from_seed(
            ledger, cls.mnemonic_class.mnemonic_to_seed(seed, password)
        )

    @classmethod
    def keys_from_dict(cls, ledger: 'baseledger.BaseLedger', d: dict) \
            -> Tuple[str, Optional[PrivateKey], PubKey]:
        seed = d.get('seed', '')
        private_key_string = d.get('private_key', '')
        private_key = None
        public_key = None
        encrypted = d.get('encrypted', False)
        if not encrypted:
            if seed:
                private_key = cls.get_private_key_from_seed(ledger, seed, '')
                public_key = private_key.public_key
            elif private_key_string:
                private_key = from_extended_key_string(ledger, private_key_string)
                public_key = private_key.public_key
        if public_key is None:
            public_key = from_extended_key_string(ledger, d['public_key'])
        return seed, private_key, public_key

    @classmethod
    def from_dict(cls, ledger: 'baseledger.BaseLedger', wallet: 'basewallet.Wallet', d: dict):
        seed, private_key, public_key = cls.keys_from_dict(ledger, d)
        name = d.get('name')
        if not name:
            name = f'Account #{public_key.address}'
        return cls(
            ledger=ledger,
            wallet=wallet,
            name=name,
            seed=seed,
            private_key_string=d.get('private_key', ''),
            encrypted=d.get('encrypted', False),
            private_key=private_key,
            public_key=public_key,
            address_generator=d.get('address_generator', {}),
            modified_on=d.get('modified_on', time.time())
        )

    def to_dict(self, encrypt_password: str = None):
        private_key_string, seed = self.private_key_string, self.seed
        if not self.encrypted and self.private_key:
            private_key_string = self.private_key.extended_key_string()
        if not self.encrypted and encrypt_password:
            if private_key_string:
                private_key_string = aes_encrypt(
                    encrypt_password, private_key_string, self.get_init_vector('private_key')
                )
            if seed:
                seed = aes_encrypt(encrypt_password, self.seed, self.get_init_vector('seed'))
        return {
            'ledger': self.ledger.get_id(),
            'name': self.name,
            'seed': seed,
            'encrypted': bool(self.encrypted or encrypt_password),
            'private_key': private_key_string,
            'public_key': self.public_key.extended_key_string(),
            'address_generator': self.address_generator.to_dict(self.receiving, self.change),
            'modified_on': self.modified_on
        }

    def merge(self, d: dict):
        if d.get('modified_on', 0) > self.modified_on:
            self.name = d['name']
            self.modified_on = d.get('modified_on', time.time())
            assert self.address_generator.name == d['address_generator']['name']
            for chain_name in ('change', 'receiving'):
                if chain_name in d['address_generator']:
                    chain_object = getattr(self, chain_name)
                    chain_object.merge(d['address_generator'][chain_name])

    @property
    def hash(self) -> bytes:
        assert not self.encrypted, "Cannot hash an encrypted account."
        return sha256(json.dumps(self.to_dict()).encode())

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
            details['seed'] = self.seed
        return details

    def decrypt(self, password: str) -> bool:
        assert self.encrypted, "Key is not encrypted."
        try:
            seed = self._decrypt_seed(password)
        except ValueError:
            return False
        try:
            private_key = self._decrypt_private_key_string(password)
        except (TypeError, ValueError):
            return False
        self.seed = seed
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

    def _decrypt_seed(self, password: str) -> str:
        if not self.seed:
            return ""
        seed, self.init_vectors['seed'] = aes_decrypt(password, self.seed)
        if not seed:
            return ""
        try:
            Mnemonic().mnemonic_decode(seed)
        except IndexError:
            # failed to decode the seed, this either means it decrypted and is invalid
            # or that we hit an edge case where an incorrect password gave valid padding
            raise ValueError("Failed to decode seed.")
        return seed

    def encrypt(self, password: str) -> bool:
        assert not self.encrypted, "Key is already encrypted."
        if self.seed:
            self.seed = aes_encrypt(password, self.seed, self.get_init_vector('seed'))
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

    async def get_addresses(self, **constraints) -> List[str]:
        rows = await self.ledger.db.select_addresses('address', accounts=[self], **constraints)
        return [r[0] for r in rows]

    def get_address_records(self, **constraints):
        return self.ledger.db.get_addresses(accounts=[self], **constraints)

    def get_address_count(self, **constraints):
        return self.ledger.db.get_address_count(accounts=[self], **constraints)

    def get_private_key(self, chain: int, index: int) -> PrivateKey:
        assert not self.encrypted, "Cannot get private key on encrypted wallet account."
        return self.address_managers[chain].get_private_key(index)

    def get_public_key(self, chain: int, index: int) -> PubKey:
        return self.address_managers[chain].get_public_key(index)

    def get_balance(self, confirmations: int = 0, **constraints):
        if confirmations > 0:
            height = self.ledger.headers.height - (confirmations-1)
            constraints.update({'height__lte': height, 'height__gt': 0})
        return self.ledger.db.get_balance(accounts=[self], **constraints)

    async def get_max_gap(self):
        change_gap = await self.change.get_max_gap()
        receiving_gap = await self.receiving.get_max_gap()
        return {
            'max_change_gap': change_gap,
            'max_receiving_gap': receiving_gap,
        }

    def get_utxos(self, **constraints):
        return self.ledger.get_utxos(wallet=self.wallet, accounts=[self], **constraints)

    def get_utxo_count(self, **constraints):
        return self.ledger.get_utxo_count(wallet=self.wallet, accounts=[self], **constraints)

    def get_transactions(self, **constraints):
        return self.ledger.get_transactions(wallet=self.wallet, accounts=[self], **constraints)

    def get_transaction_count(self, **constraints):
        return self.ledger.get_transaction_count(wallet=self.wallet, accounts=[self], **constraints)

    async def fund(self, to_account, amount=None, everything=False,
                   outputs=1, broadcast=False, **constraints):
        assert self.ledger == to_account.ledger, 'Can only transfer between accounts of the same ledger.'
        tx_class = self.ledger.transaction_class
        if everything:
            utxos = await self.get_utxos(**constraints)
            await self.ledger.reserve_outputs(utxos)
            tx = await tx_class.create(
                inputs=[tx_class.input_class.spend(txo) for txo in utxos],
                outputs=[],
                funding_accounts=[self],
                change_account=to_account
            )
        elif amount > 0:
            to_address = await to_account.change.get_or_create_usable_address()
            to_hash160 = to_account.ledger.address_to_hash160(to_address)
            tx = await tx_class.create(
                inputs=[],
                outputs=[
                    tx_class.output_class.pay_pubkey_hash(amount//outputs, to_hash160)
                    for _ in range(outputs)
                ],
                funding_accounts=[self],
                change_account=self
            )
        else:
            raise ValueError('An amount is required.')

        if broadcast:
            await self.ledger.broadcast(tx)
        else:
            await self.ledger.release_tx(tx)

        return tx
