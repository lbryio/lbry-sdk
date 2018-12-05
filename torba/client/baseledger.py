import os
import asyncio
import logging
from functools import partial
from binascii import hexlify, unhexlify
from io import StringIO

from typing import Dict, Type, Iterable, List, Optional
from operator import itemgetter
from collections import namedtuple

from torba.client import baseaccount, basenetwork, basetransaction
from torba.client.basedatabase import BaseDatabase
from torba.client.baseheader import BaseHeaders
from torba.client.coinselection import CoinSelector
from torba.client.constants import COIN, NULL_HASH32
from torba.stream import StreamController
from torba.client.hash import hash160, double_sha256, sha256, Base58

log = logging.getLogger(__name__)

LedgerType = Type['BaseLedger']


class LedgerRegistry(type):

    ledgers: Dict[str, LedgerType] = {}

    def __new__(mcs, name, bases, attrs):
        cls: LedgerType = super().__new__(mcs, name, bases, attrs)
        if not (name == 'BaseLedger' and not bases):
            ledger_id = cls.get_id()
            assert ledger_id not in mcs.ledgers,\
                'Ledger with id "{}" already registered.'.format(ledger_id)
            mcs.ledgers[ledger_id] = cls
        return cls

    @classmethod
    def get_ledger_class(mcs, ledger_id: str) -> LedgerType:
        return mcs.ledgers[ledger_id]


class TransactionEvent(namedtuple('TransactionEvent', ('address', 'tx'))):
    pass


class AddressesGeneratedEvent(namedtuple('AddressesGeneratedEvent', ('address_manager', 'addresses'))):
    pass


class BlockHeightEvent(namedtuple('BlockHeightEvent', ('height', 'change'))):
    pass


class TransactionCacheItem:
    __slots__ = '_tx', 'lock', 'has_tx'

    def __init__(self,
                 tx: Optional[basetransaction.BaseTransaction] = None,
                 lock: Optional[asyncio.Lock] = None):
        self.has_tx = asyncio.Event()
        self.lock = lock or asyncio.Lock()
        self._tx = self.tx = tx

    @property
    def tx(self) -> Optional[basetransaction.BaseTransaction]:
        return self._tx

    @tx.setter
    def tx(self, tx: basetransaction.BaseTransaction):
        self._tx = tx
        if tx is not None:
            self.has_tx.set()


class SynchronizationMonitor:

    def __init__(self, loop=None):
        self.done = asyncio.Event()
        self.tasks = []
        self.loop = loop or asyncio.get_event_loop()

    def add(self, coro):
        len(self.tasks) < 1 and self.done.clear()
        self.loop.create_task(self._monitor(coro))

    def cancel(self):
        for task in self.tasks:
            task.cancel()

    async def _monitor(self, coro):
        task = self.loop.create_task(coro)
        self.tasks.append(task)
        try:
            await task
        finally:
            self.tasks.remove(task)
            len(self.tasks) < 1 and self.done.set()


class BaseLedger(metaclass=LedgerRegistry):

    name: str
    symbol: str
    network_name: str

    database_class = BaseDatabase
    account_class = baseaccount.BaseAccount
    network_class = basenetwork.BaseNetwork
    transaction_class = basetransaction.BaseTransaction

    headers_class: Type[BaseHeaders]

    pubkey_address_prefix: bytes
    script_address_prefix: bytes
    extended_public_key_prefix: bytes
    extended_private_key_prefix: bytes

    default_fee_per_byte = 10

    def __init__(self, config=None):
        self.config = config or {}
        self.db: BaseDatabase = self.config.get('db') or self.database_class(
            os.path.join(self.path, "blockchain.db")
        )
        self.db.ledger = self
        self.headers: BaseHeaders = self.config.get('headers') or self.headers_class(
            os.path.join(self.path, "headers")
        )
        self.network = self.config.get('network') or self.network_class(self)
        self.network.on_header.listen(self.receive_header)
        self.network.on_status.listen(self.process_status_update)

        self.accounts = []
        self.fee_per_byte: int = self.config.get('fee_per_byte', self.default_fee_per_byte)

        self._on_transaction_controller = StreamController()
        self.on_transaction = self._on_transaction_controller.stream
        self.on_transaction.listen(
            lambda e: log.info(
                '(%s) on_transaction: address=%s, height=%s, is_verified=%s, tx.id=%s',
                self.get_id(), e.address, e.tx.height, e.tx.is_verified, e.tx.id
            )
        )

        self._on_address_controller = StreamController()
        self.on_address = self._on_address_controller.stream
        self.on_address.listen(
            lambda e: log.info('(%s) on_address: %s', self.get_id(), e.addresses)
        )

        self._on_header_controller = StreamController()
        self.on_header = self._on_header_controller.stream
        self.on_header.listen(
            lambda change: log.info(
                '%s: added %s header blocks, final height %s',
                self.get_id(), change, self.headers.height
            )
        )

        self._tx_cache = {}
        self.sync = SynchronizationMonitor()
        self._utxo_reservation_lock = asyncio.Lock()
        self._header_processing_lock = asyncio.Lock()
        self._address_update_locks: Dict[str, asyncio.Lock] = {}

    @classmethod
    def get_id(cls):
        return '{}_{}'.format(cls.symbol.lower(), cls.network_name.lower())

    @classmethod
    def hash160_to_address(cls, h160):
        raw_address = cls.pubkey_address_prefix + h160
        return Base58.encode(bytearray(raw_address + double_sha256(raw_address)[0:4]))

    @staticmethod
    def address_to_hash160(address):
        return Base58.decode(address)[1:21]

    @classmethod
    def public_key_to_address(cls, public_key):
        return cls.hash160_to_address(hash160(public_key))

    @staticmethod
    def private_key_to_wif(private_key):
        return b'\x1c' + private_key + b'\x01'

    @property
    def path(self):
        return os.path.join(self.config['data_path'], self.get_id())

    def add_account(self, account: baseaccount.BaseAccount):
        self.accounts.append(account)

    async def get_private_key_for_address(self, address):
        match = await self.db.get_address(address=address)
        if match:
            for account in self.accounts:
                if match['account'] == account.public_key.address:
                    return account.get_private_key(match['chain'], match['position'])

    async def get_effective_amount_estimators(self, funding_accounts: Iterable[baseaccount.BaseAccount]):
        estimators = []
        for account in funding_accounts:
            utxos = await account.get_utxos()
            for utxo in utxos:
                estimators.append(utxo.get_estimator(self))
        return estimators

    async def get_spendable_utxos(self, amount: int, funding_accounts):
        async with self._utxo_reservation_lock:
            txos = await self.get_effective_amount_estimators(funding_accounts)
            selector = CoinSelector(
                txos, amount,
                self.transaction_class.output_class.pay_pubkey_hash(COIN, NULL_HASH32).get_fee(self)
            )
            spendables = selector.select()
            if spendables:
                await self.reserve_outputs(s.txo for s in spendables)
            return spendables

    def reserve_outputs(self, txos):
        return self.db.reserve_outputs(txos)

    def release_outputs(self, txos):
        return self.db.release_outputs(txos)

    async def get_local_status_and_history(self, address):
        address_details = await self.db.get_address(address=address)
        history = address_details['history'] or ''
        parts = history.split(':')[:-1]
        return (
            hexlify(sha256(history.encode())).decode() if history else None,
            list(zip(parts[0::2], map(int, parts[1::2])))
        )

    @staticmethod
    def get_root_of_merkle_tree(branches, branch_positions, working_branch):
        for i, branch in enumerate(branches):
            other_branch = unhexlify(branch)[::-1]
            other_branch_on_left = bool((branch_positions >> i) & 1)
            if other_branch_on_left:
                combined = other_branch + working_branch
            else:
                combined = working_branch + other_branch
            working_branch = double_sha256(combined)
        return hexlify(working_branch[::-1])

    async def start(self):
        if not os.path.exists(self.path):
            os.mkdir(self.path)
        await asyncio.wait([
            self.db.open(),
            self.headers.open()
        ])
        first_connection = self.network.on_connected.first
        asyncio.ensure_future(self.network.start())
        await first_connection
        await self.join_network()
        self.network.on_connected.listen(self.join_network)

    async def join_network(self, *args):
        log.info("Subscribing and updating accounts.")
        await self.update_headers()
        await self.network.subscribe_headers()
        await self.subscribe_accounts()
        await self.sync.done.wait()

    async def stop(self):
        self.sync.cancel()
        await self.sync.done.wait()
        await self.network.stop()
        await self.db.close()
        await self.headers.close()

    async def update_headers(self, height=None, headers=None, subscription_update=False):
        rewound = 0
        while True:

            if height is None or height > len(self.headers):
                # sometimes header subscription updates are for a header in the future
                # which can't be connected, so we do a normal header sync instead
                height = len(self.headers)
                headers = None
                subscription_update = False

            if not headers:
                header_response = await self.network.get_headers(height, 2001)
                headers = header_response['hex']

            if not headers:
                # Nothing to do, network thinks we're already at the latest height.
                return

            added = await self.headers.connect(height, unhexlify(headers))
            if added > 0:
                height += added
                self._on_header_controller.add(
                    BlockHeightEvent(self.headers.height, added))

                if rewound > 0:
                    # we started rewinding blocks and apparently found
                    # a new chain
                    rewound = 0
                    await self.db.rewind_blockchain(height)

                if subscription_update:
                    # subscription updates are for latest header already
                    # so we don't need to check if there are newer / more
                    # on another loop of update_headers(), just return instead
                    return

            elif added == 0:
                # we had headers to connect but none got connected, probably a reorganization
                height -= 1
                rewound += 1
                log.warning(
                    "Blockchain Reorganization: attempting rewind to height %s from starting height %s",
                    height, height+rewound
                )

            else:
                raise IndexError("headers.connect() returned negative number ({})".format(added))

            if height < 0:
                raise IndexError(
                    "Blockchain reorganization rewound all the way back to genesis hash. "
                    "Something is very wrong. Maybe you are on the wrong blockchain?"
                )

            if rewound >= 100:
                raise IndexError(
                    "Blockchain reorganization dropped {} headers. This is highly unusual. "
                    "Will not continue to attempt reorganizing. Please, delete the ledger "
                    "synchronization directory inside your wallet directory (folder: '{}') and "
                    "restart the program to synchronize from scratch."
                    .format(rewound, self.get_id())
                )

            headers = None  # ready to download some more headers

            # if we made it this far and this was a subscription_update
            # it means something went wrong and now we're doing a more
            # robust sync, turn off subscription update shortcut
            subscription_update = False

    async def receive_header(self, response):
        async with self._header_processing_lock:
            header = response[0]
            await self.update_headers(
                height=header['height'], headers=header['hex'], subscription_update=True
            )

    async def subscribe_accounts(self):
        if self.network.is_connected and self.accounts:
            await asyncio.wait([
                self.subscribe_account(a) for a in self.accounts
            ])

    async def subscribe_account(self, account: baseaccount.BaseAccount):
        for address_manager in account.address_managers.values():
            await self.subscribe_addresses(address_manager, await address_manager.get_addresses())
        await account.ensure_address_gap()

    async def announce_addresses(self, address_manager: baseaccount.AddressManager, addresses: List[str]):
        await self.subscribe_addresses(address_manager, addresses)
        await self._on_address_controller.add(
            AddressesGeneratedEvent(address_manager, addresses)
        )

    async def subscribe_addresses(self, address_manager: baseaccount.AddressManager, addresses: List[str]):
        if self.network.is_connected and addresses:
            await asyncio.wait([
                self.subscribe_address(address_manager, address) for address in addresses
            ])

    async def subscribe_address(self, address_manager: baseaccount.AddressManager, address: str):
        remote_status = await self.network.subscribe_address(address)
        self.sync.add(self.update_history(address, remote_status, address_manager))

    def process_status_update(self, update):
        address, remote_status = update
        self.sync.add(self.update_history(address, remote_status))

    async def update_history(self, address, remote_status,
                             address_manager: baseaccount.AddressManager = None):

        async with self._address_update_locks.setdefault(address, asyncio.Lock()):

            local_status, local_history = await self.get_local_status_and_history(address)

            if local_status == remote_status:
                return

            remote_history = await self.network.get_history(address)

            cache_tasks = []
            synced_history = StringIO()
            for i, (txid, remote_height) in enumerate(map(itemgetter('tx_hash', 'height'), remote_history)):
                if i < len(local_history) and local_history[i] == (txid, remote_height):
                    synced_history.write(f'{txid}:{remote_height}:')
                else:
                    cache_tasks.append(asyncio.ensure_future(
                        self.cache_transaction(txid, remote_height)
                    ))

            for task in cache_tasks:
                tx = await task

                check_db_for_txos = []
                for txi in tx.inputs:
                    if txi.txo_ref.txo is not None:
                        continue
                    cache_item = self._tx_cache.get(txi.txo_ref.tx_ref.id)
                    if cache_item is not None:
                        if cache_item.tx is None:
                            await cache_item.has_tx.wait()
                        assert cache_item.tx is not None
                        txi.txo_ref = cache_item.tx.outputs[txi.txo_ref.position].ref
                    else:
                        check_db_for_txos.append(txi.txo_ref.tx_ref.id)

                referenced_txos = {
                    txo.id: txo for txo in await self.db.get_txos(txoid__in=check_db_for_txos)
                }

                for txi in tx.inputs:
                    if txi.txo_ref.txo is not None:
                        continue
                    referenced_txo = referenced_txos.get(txi.txo_ref.tx_ref.id)
                    if referenced_txo is not None:
                        txi.txo_ref = referenced_txo.ref

                synced_history.write(f'{tx.id}:{tx.height}:')

                await self.db.save_transaction_io(
                    tx, address, self.address_to_hash160(address), synced_history.getvalue()
                )

                await self._on_transaction_controller.add(TransactionEvent(address, tx))

            if address_manager is None:
                address_manager = await self.get_address_manager_for_address(address)

            if address_manager is not None:
                await address_manager.ensure_address_gap()

    async def cache_transaction(self, txid, remote_height):
        cache_item = self._tx_cache.get(txid)
        if cache_item is None:
            cache_item = self._tx_cache[txid] = TransactionCacheItem()
        elif cache_item.tx is not None and \
                cache_item.tx.height >= remote_height and \
                (cache_item.tx.is_verified or remote_height < 1):
            return cache_item.tx  # cached tx is already up-to-date

        async with cache_item.lock:

            tx = cache_item.tx

            if tx is None:
                # check local db
                tx = cache_item.tx = await self.db.get_transaction(txid=txid)

            if tx is None:
                # fetch from network
                _raw = await self.network.get_transaction(txid)
                if _raw:
                    tx = self.transaction_class(unhexlify(_raw))
                    await self.maybe_verify_transaction(tx, remote_height)
                    await self.db.insert_transaction(tx)
                    cache_item.tx = tx  # make sure it's saved before caching it
                    return tx

            if tx is None:
                raise ValueError(f'Transaction {txid} was not in database and not on network.')

            if remote_height > 0 and not tx.is_verified:
                # tx from cache / db is not up-to-date
                await self.maybe_verify_transaction(tx, remote_height)
                await self.db.update_transaction(tx)

            return tx

    async def maybe_verify_transaction(self, tx, remote_height):
        tx.height = remote_height
        if 0 < remote_height <= len(self.headers):
            merkle = await self.network.get_merkle(tx.id, remote_height)
            merkle_root = self.get_root_of_merkle_tree(merkle['merkle'], merkle['pos'], tx.hash)
            header = self.headers[remote_height]
            tx.position = merkle['pos']
            tx.is_verified = merkle_root == header['merkle_root']

    async def get_address_manager_for_address(self, address) -> Optional[baseaccount.AddressManager]:
        details = await self.db.get_address(address=address)
        for account in self.accounts:
            if account.id == details['account']:
                return account.address_managers[details['chain']]
        return None

    def broadcast(self, tx):
        return self.network.broadcast(hexlify(tx.raw).decode())

    async def wait(self, tx: basetransaction.BaseTransaction, height=-1):
        addresses = set()
        for txi in tx.inputs:
            if txi.txo_ref.txo is not None:
                addresses.add(
                    self.hash160_to_address(txi.txo_ref.txo.script.values['pubkey_hash'])
                )
        for txo in tx.outputs:
            addresses.add(
                self.hash160_to_address(txo.script.values['pubkey_hash'])
            )
        records = await self.db.get_addresses(cols=('address',), address__in=addresses)
        await asyncio.wait([
            self.on_transaction.where(partial(
                lambda a, e: a == e.address and e.tx.height >= height and e.tx.id == tx.id,
                address_record['address']
            )) for address_record in records
        ])
