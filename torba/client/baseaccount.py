import asyncio
import random
import typing
from typing import Dict, Tuple, Type, Optional, Any, List

from torba.client.mnemonic import Mnemonic
from torba.client.bip32 import PrivateKey, PubKey, from_extended_key_string
from torba.client.hash import aes_encrypt, aes_decrypt
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

    def to_dict_instance(self) -> Optional[dict]:
        raise NotImplementedError

    def _query_addresses(self, **constraints):
        return self.account.ledger.db.get_addresses(
            account=self.account,
            chain=self.chain_number,
            **constraints
        )

    def get_private_key(self, index: int) -> PrivateKey:
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

    name = "deterministic-chain"

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

    def to_dict_instance(self):
        return {'gap': self.gap, 'maximum_uses_per_address': self.maximum_uses_per_address}

    def get_private_key(self, index: int) -> PrivateKey:
        return self.account.private_key.child(self.chain_number).child(index)

    async def get_max_gap(self) -> int:
        addresses = await self._query_addresses(order_by="position ASC")
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
            addresses = await self._query_addresses(limit=self.gap, order_by="position DESC")

            existing_gap = 0
            for address in addresses:
                if address['used_times'] == 0:
                    existing_gap += 1
                else:
                    break

            if existing_gap == self.gap:
                return []

            start = addresses[0]['position']+1 if addresses else 0
            end = start + (self.gap - existing_gap)
            new_keys = await self._generate_keys(start, end-1)
            await self.account.ledger.announce_addresses(self, new_keys)
            return new_keys

    async def _generate_keys(self, start: int, end: int) -> List[str]:
        if not self.address_generator_lock.locked():
            raise RuntimeError('Should not be called outside of address_generator_lock.')
        keys_batch, final_keys = [], []
        for index in range(start, end+1):
            keys_batch.append((index, self.public_key.child(index)))
            if index % 180 == 0 or index == end:
                await self.account.ledger.db.add_keys(
                    self.account, self.chain_number, keys_batch
                )
                final_keys.extend(keys_batch)
                keys_batch.clear()
        return [key[1].address for key in final_keys]

    def get_address_records(self, only_usable: bool = False, **constraints):
        if only_usable:
            constraints['used_times__lt'] = self.maximum_uses_per_address
        if 'order_by' not in constraints:
            constraints['order_by'] = "used_times ASC, position ASC"
        return self._query_addresses(**constraints)


class SingleKey(AddressManager):
    """ Single Key address manager always returns the same address for all operations. """

    name = "single-address"

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

    async def get_max_gap(self) -> int:
        return 0

    async def ensure_address_gap(self) -> List[str]:
        async with self.address_generator_lock:
            exists = await self.get_address_records()
            if not exists:
                await self.account.ledger.db.add_keys(
                    self.account, self.chain_number, [(0, self.public_key)]
                )
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
                 address_generator: dict) -> None:
        self.ledger = ledger
        self.wallet = wallet
        self.id = public_key.address
        self.name = name
        self.seed = seed
        self.private_key_string = private_key_string
        self.password: Optional[str] = None
        self.private_key_encryption_init_vector: Optional[bytes] = None
        self.seed_encryption_init_vector: Optional[bytes] = None

        self.encrypted = encrypted
        self.serialize_encrypted = encrypted
        self.private_key = private_key
        self.public_key = public_key
        generator_name = address_generator.get('name', HierarchicalDeterministic.name)
        self.address_generator = self.address_generators[generator_name]
        self.receiving, self.change = self.address_generator.from_dict(self, address_generator)
        self.address_managers = {am.chain_number: am for am in {self.receiving, self.change}}
        ledger.add_account(self)
        wallet.add_account(self)

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
    def from_dict(cls, ledger: 'baseledger.BaseLedger', wallet: 'basewallet.Wallet', d: dict):
        seed = d.get('seed', '')
        private_key_string = d.get('private_key', '')
        private_key = None
        public_key = None
        encrypted = d.get('encrypted', False)
        if not encrypted:
            if seed:
                private_key = cls.get_private_key_from_seed(ledger, seed, '')
                public_key = private_key.public_key
            elif private_key:
                private_key = from_extended_key_string(ledger, private_key_string)
                public_key = private_key.public_key
        if public_key is None:
            public_key = from_extended_key_string(ledger, d['public_key'])
        name = d.get('name')
        if not name:
            name = 'Account #{}'.format(public_key.address)
        return cls(
            ledger=ledger,
            wallet=wallet,
            name=name,
            seed=seed,
            private_key_string=private_key_string,
            encrypted=encrypted,
            private_key=private_key,
            public_key=public_key,
            address_generator=d.get('address_generator', {})
        )

    def to_dict(self):
        private_key_string, seed = self.private_key_string, self.seed
        if not self.encrypted and self.private_key:
            private_key_string = self.private_key.extended_key_string()
        if not self.encrypted and self.serialize_encrypted:
            assert None not in [self.seed_encryption_init_vector, self.private_key_encryption_init_vector]
            private_key_string = aes_encrypt(
                self.password, private_key_string, self.private_key_encryption_init_vector
            )
            seed = aes_encrypt(self.password, self.seed, self.seed_encryption_init_vector)
        return {
            'ledger': self.ledger.get_id(),
            'name': self.name,
            'seed': seed,
            'encrypted': self.serialize_encrypted,
            'private_key': private_key_string,
            'public_key': self.public_key.extended_key_string(),
            'address_generator': self.address_generator.to_dict(self.receiving, self.change)
        }

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

    def decrypt(self, password: str) -> None:
        assert self.encrypted, "Key is not encrypted."
        try:
            seed, seed_iv = aes_decrypt(password, self.seed)
            pk_string, pk_iv = aes_decrypt(password, self.private_key_string)
        except ValueError:  # failed to remove padding, password is wrong
            return
        try:
            Mnemonic().mnemonic_decode(seed)
        except IndexError:  # failed to decode the seed, this either means it decrypted and is invalid
                            # or that we hit an edge case where an incorrect password gave valid padding
            return
        try:
            private_key = from_extended_key_string(
                self.ledger, pk_string
            )
        except (TypeError, ValueError):
            return
        self.seed = seed
        self.seed_encryption_init_vector = seed_iv
        self.private_key = private_key
        self.private_key_encryption_init_vector = pk_iv
        self.password = password
        self.encrypted = False

    def encrypt(self, password: str) -> None:
        assert not self.encrypted, "Key is already encrypted."
        assert isinstance(self.private_key, PrivateKey)

        self.seed = aes_encrypt(password, self.seed, self.seed_encryption_init_vector)
        self.private_key_string = aes_encrypt(
            password, self.private_key.extended_key_string(), self.private_key_encryption_init_vector
        )
        self.private_key = None
        self.password = None
        self.encrypted = True

    async def ensure_address_gap(self):
        addresses = []
        for address_manager in self.address_managers.values():
            new_addresses = await address_manager.ensure_address_gap()
            addresses.extend(new_addresses)
        return addresses

    async def get_addresses(self, **constraints) -> List[str]:
        rows = await self.ledger.db.select_addresses('address', account=self, **constraints)
        return [r[0] for r in rows]

    def get_address_records(self, **constraints):
        return self.ledger.db.get_addresses(account=self, **constraints)

    def get_address_count(self, **constraints):
        return self.ledger.db.get_address_count(account=self, **constraints)

    def get_private_key(self, chain: int, index: int) -> PrivateKey:
        assert not self.encrypted, "Cannot get private key on encrypted wallet account."
        return self.address_managers[chain].get_private_key(index)

    def get_balance(self, confirmations: int = 0, **constraints):
        if confirmations > 0:
            height = self.ledger.headers.height - (confirmations-1)
            constraints.update({'height__lte': height, 'height__gt': 0})
        return self.ledger.db.get_balance(account=self, **constraints)

    async def get_max_gap(self):
        change_gap = await self.change.get_max_gap()
        receiving_gap = await self.receiving.get_max_gap()
        return {
            'max_change_gap': change_gap,
            'max_receiving_gap': receiving_gap,
        }

    def get_utxos(self, **constraints):
        return self.ledger.db.get_utxos(account=self, **constraints)

    def get_utxo_count(self, **constraints):
        return self.ledger.db.get_utxo_count(account=self, **constraints)

    def get_transactions(self, **constraints):
        return self.ledger.db.get_transactions(account=self, **constraints)

    def get_transaction_count(self, **constraints):
        return self.ledger.db.get_transaction_count(account=self, **constraints)

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
            await self.ledger.release_outputs(
                [txi.txo_ref.txo for txi in tx.inputs]
            )

        return tx
