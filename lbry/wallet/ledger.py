import os
import copy
import time
import asyncio
import logging
from datetime import datetime
from functools import partial
from operator import itemgetter
from collections import defaultdict
from binascii import hexlify, unhexlify
from typing import Dict, Tuple, Type, Iterable, List, Optional, DefaultDict, NamedTuple

from lbry.schema.result import Outputs, INVALID, NOT_FOUND
from lbry.schema.url import URL
from lbry.crypto.hash import hash160, double_sha256, sha256
from lbry.crypto.base58 import Base58
from lbry.utils import LRUCacheWithMetrics

from lbry.wallet.tasks import TaskGroup
from lbry.wallet.database import Database
from lbry.wallet.stream import StreamController
from lbry.wallet.dewies import dewies_to_lbc
from lbry.wallet.account import Account, AddressManager, SingleKey
from lbry.wallet.network import Network
from lbry.wallet.transaction import Transaction, Output
from lbry.wallet.header import Headers, UnvalidatedHeaders
from lbry.wallet.checkpoints import HASHES
from lbry.wallet.constants import TXO_TYPES, CLAIM_TYPES, COIN, NULL_HASH32
from lbry.wallet.bip32 import PublicKey, PrivateKey
from lbry.wallet.coinselection import CoinSelector

log = logging.getLogger(__name__)

LedgerType = Type['BaseLedger']


class LedgerRegistry(type):

    ledgers: Dict[str, LedgerType] = {}

    def __new__(mcs, name, bases, attrs):
        cls: LedgerType = super().__new__(mcs, name, bases, attrs)
        if not (name == 'BaseLedger' and not bases):
            ledger_id = cls.get_id()
            assert ledger_id not in mcs.ledgers, \
                f'Ledger with id "{ledger_id}" already registered.'
            mcs.ledgers[ledger_id] = cls
        return cls

    @classmethod
    def get_ledger_class(mcs, ledger_id: str) -> LedgerType:
        return mcs.ledgers[ledger_id]


class TransactionEvent(NamedTuple):
    address: str
    tx: Transaction


class AddressesGeneratedEvent(NamedTuple):
    address_manager: AddressManager
    addresses: List[str]


class BlockHeightEvent(NamedTuple):
    height: int
    change: int


class TransactionCacheItem:
    __slots__ = '_tx', 'lock', 'has_tx', 'pending_verifications'

    def __init__(self, tx: Optional[Transaction] = None, lock: Optional[asyncio.Lock] = None):
        self.has_tx = asyncio.Event()
        self.lock = lock or asyncio.Lock()
        self._tx = self.tx = tx
        self.pending_verifications = 0

    @property
    def tx(self) -> Optional[Transaction]:
        return self._tx

    @tx.setter
    def tx(self, tx: Transaction):
        self._tx = tx
        if tx is not None:
            self.has_tx.set()


class Ledger(metaclass=LedgerRegistry):
    name = 'LBRY Credits'
    symbol = 'LBC'
    network_name = 'mainnet'

    headers_class = Headers

    secret_prefix = bytes((0x1c,))
    pubkey_address_prefix = bytes((0x55,))
    script_address_prefix = bytes((0x7a,))
    extended_public_key_prefix = unhexlify('0488b21e')
    extended_private_key_prefix = unhexlify('0488ade4')

    max_target = 0x0000ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = '9c89283ba0f3227f6c03b70216b9f665f0118d5e0fa729cedf4fb34d6a34f463'
    genesis_bits = 0x1f00ffff
    target_timespan = 150

    default_fee_per_byte = 50
    default_fee_per_name_char = 0

    checkpoints = HASHES

    def __init__(self, config=None):
        self.config = config or {}
        self.db: Database = self.config.get('db') or Database(
            os.path.join(self.path, "blockchain.db")
        )
        self.db.ledger = self
        self.headers: Headers = self.config.get('headers') or self.headers_class(
            os.path.join(self.path, "headers")
        )
        self.headers.checkpoints = self.checkpoints
        self.network: Network = self.config.get('network') or Network(self)
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
        self._download_height = 0

        self._on_ready_controller = StreamController()
        self.on_ready = self._on_ready_controller.stream

        self._tx_cache = LRUCacheWithMetrics(self.config.get("tx_cache_size", 1024), metric_name='tx')
        self._update_tasks = TaskGroup()
        self._other_tasks = TaskGroup()  # that we dont need to start
        self._utxo_reservation_lock = asyncio.Lock()
        self._header_processing_lock = asyncio.Lock()
        self._address_update_locks: DefaultDict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._history_lock = asyncio.Lock()

        self.coin_selection_strategy = None
        self._known_addresses_out_of_sync = set()

        self.fee_per_name_char = self.config.get('fee_per_name_char', self.default_fee_per_name_char)
        self._balance_cache = LRUCacheWithMetrics(2 ** 15)

    @classmethod
    def get_id(cls):
        return '{}_{}'.format(cls.symbol.lower(), cls.network_name.lower())

    @classmethod
    def hash160_to_address(cls, h160):
        raw_address = cls.pubkey_address_prefix + h160
        return Base58.encode(bytearray(raw_address + double_sha256(raw_address)[0:4]))

    @classmethod
    def hash160_to_script_address(cls, h160):
        raw_address = cls.script_address_prefix + h160
        return Base58.encode(bytearray(raw_address + double_sha256(raw_address)[0:4]))

    @staticmethod
    def address_to_hash160(address):
        return Base58.decode(address)[1:21]

    @classmethod
    def is_pubkey_address(cls, address):
        decoded = Base58.decode_check(address)
        return decoded[0] == cls.pubkey_address_prefix[0]

    @classmethod
    def is_script_address(cls, address):
        decoded = Base58.decode_check(address)
        return decoded[0] == cls.script_address_prefix[0]

    @classmethod
    def public_key_to_address(cls, public_key):
        return cls.hash160_to_address(hash160(public_key))

    @staticmethod
    def private_key_to_wif(private_key):
        return b'\x1c' + private_key + b'\x01'

    @property
    def path(self):
        return os.path.join(self.config['data_path'], self.get_id())

    def add_account(self, account: Account):
        self.accounts.append(account)

    async def _get_account_and_address_info_for_address(self, wallet, address):
        match = await self.db.get_address(accounts=wallet.accounts, address=address)
        if match:
            for account in wallet.accounts:
                if match['account'] == account.public_key.address:
                    return account, match

    async def get_private_key_for_address(self, wallet, address) -> Optional[PrivateKey]:
        match = await self._get_account_and_address_info_for_address(wallet, address)
        if match:
            account, address_info = match
            return account.get_private_key(address_info['chain'], address_info['pubkey'].n)
        return None

    async def get_public_key_for_address(self, wallet, address) -> Optional[PublicKey]:
        match = await self._get_account_and_address_info_for_address(wallet, address)
        if match:
            _, address_info = match
            return address_info['pubkey']
        return None

    async def get_account_for_address(self, wallet, address):
        match = await self._get_account_and_address_info_for_address(wallet, address)
        if match:
            return match[0]

    async def get_effective_amount_estimators(self, funding_accounts: Iterable[Account]):
        estimators = []
        for account in funding_accounts:
            utxos = await account.get_utxos(no_tx=True, no_channel_info=True)
            for utxo in utxos:
                estimators.append(utxo.get_estimator(self))
        return estimators

    async def get_addresses(self, **constraints):
        return await self.db.get_addresses(**constraints)

    def get_address_count(self, **constraints):
        return self.db.get_address_count(**constraints)

    async def get_spendable_utxos(self, amount: int, funding_accounts: Optional[Iterable['Account']], min_amount=1):
        min_amount = min(amount // 10, min_amount)
        fee = Output.pay_pubkey_hash(COIN, NULL_HASH32).get_fee(self)
        selector = CoinSelector(amount, fee)
        async with self._utxo_reservation_lock:
            if self.coin_selection_strategy == 'sqlite':
                return await self.db.get_spendable_utxos(self, amount + fee, funding_accounts, min_amount=min_amount,
                                                         fee_per_byte=self.fee_per_byte)
            txos = await self.get_effective_amount_estimators(funding_accounts)
            spendables = selector.select(txos, self.coin_selection_strategy)
            if spendables:
                await self.reserve_outputs(s.txo for s in spendables)
            return spendables

    def reserve_outputs(self, txos):
        return self.db.reserve_outputs(txos)

    def release_outputs(self, txos):
        return self.db.release_outputs(txos)

    def release_tx(self, tx):
        return self.release_outputs([txi.txo_ref.txo for txi in tx.inputs])

    def get_utxos(self, **constraints):
        self.constraint_spending_utxos(constraints)
        return self.db.get_utxos(**constraints)

    def get_utxo_count(self, **constraints):
        self.constraint_spending_utxos(constraints)
        return self.db.get_utxo_count(**constraints)

    async def get_txos(self, resolve=False, **constraints) -> List[Output]:
        txos = await self.db.get_txos(**constraints)
        if resolve:
            return await self._resolve_for_local_results(constraints.get('accounts', []), txos)
        return txos

    def get_txo_count(self, **constraints):
        return self.db.get_txo_count(**constraints)

    def get_txo_sum(self, **constraints):
        return self.db.get_txo_sum(**constraints)

    def get_txo_plot(self, **constraints):
        return self.db.get_txo_plot(**constraints)

    def get_transactions(self, **constraints):
        return self.db.get_transactions(**constraints)

    def get_transaction_count(self, **constraints):
        return self.db.get_transaction_count(**constraints)

    async def get_local_status_and_history(self, address, history=None):
        if not history:
            address_details = await self.db.get_address(address=address)
            history = (address_details['history'] if address_details else '') or ''
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
        fully_synced = self.on_ready.first
        asyncio.create_task(self.network.start())
        await self.network.on_connected.first
        async with self._header_processing_lock:
            await self._update_tasks.add(self.initial_headers_sync())
        self.network.on_connected.listen(self.join_network)
        asyncio.ensure_future(self.join_network())
        await fully_synced
        await self.db.release_all_outputs()
        await asyncio.gather(*(a.maybe_migrate_certificates() for a in self.accounts))
        await asyncio.gather(*(a.save_max_gap() for a in self.accounts))
        if len(self.accounts) > 10:
            log.info("Loaded %i accounts", len(self.accounts))
        else:
            await self._report_state()
        self.on_transaction.listen(self._reset_balance_cache)

    async def join_network(self, *_):
        log.info("Subscribing and updating accounts.")
        await self._update_tasks.add(self.subscribe_accounts())
        await self._update_tasks.done.wait()
        self._on_ready_controller.add(True)

    async def stop(self):
        self._update_tasks.cancel()
        self._other_tasks.cancel()
        await self._update_tasks.done.wait()
        await self._other_tasks.done.wait()
        await self.network.stop()
        await self.db.close()
        await self.headers.close()

    async def tasks_are_done(self):
        await self._update_tasks.done.wait()
        await self._other_tasks.done.wait()

    @property
    def local_height_including_downloaded_height(self):
        return max(self.headers.height, self._download_height)

    async def initial_headers_sync(self):
        get_chunk = partial(self.network.retriable_call, self.network.get_headers, count=1000, b64=True)
        self.headers.chunk_getter = get_chunk

        async def doit():
            for height in reversed(sorted(self.headers.known_missing_checkpointed_chunks)):
                async with self._header_processing_lock:
                    await self.headers.ensure_chunk_at(height)
        self._other_tasks.add(doit())
        await self.update_headers()

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
                header_response = await self.network.retriable_call(self.network.get_headers, height, 2001)
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
                self._tx_cache.clear()

            else:
                raise IndexError(f"headers.connect() returned negative number ({added})")

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
            log.info("Subscribe to %i accounts", len(self.accounts))
            await asyncio.wait([
                self.subscribe_account(a) for a in self.accounts
            ])

    async def subscribe_account(self, account: Account):
        for address_manager in account.address_managers.values():
            await self.subscribe_addresses(address_manager, await address_manager.get_addresses())
        await account.ensure_address_gap()
        await account.deterministic_channel_keys.ensure_cache_primed()

    async def unsubscribe_account(self, account: Account):
        for address in await account.get_addresses():
            await self.network.unsubscribe_address(address)

    async def announce_addresses(self, address_manager: AddressManager, addresses: List[str]):
        await self.subscribe_addresses(address_manager, addresses)
        await self._on_address_controller.add(
            AddressesGeneratedEvent(address_manager, addresses)
        )

    async def subscribe_addresses(self, address_manager: AddressManager, addresses: List[str], batch_size: int = 1000):
        if self.network.is_connected and addresses:
            addresses_remaining = list(addresses)
            while addresses_remaining:
                batch = addresses_remaining[:batch_size]
                results = await self.network.subscribe_address(*batch)
                for address, remote_status in zip(batch, results):
                    self._update_tasks.add(self.update_history(address, remote_status, address_manager))
                addresses_remaining = addresses_remaining[batch_size:]
                if self.network.client and self.network.client.server_address_and_port:
                    log.info("subscribed to %i/%i addresses on %s:%i", len(addresses) - len(addresses_remaining),
                             len(addresses), *self.network.client.server_address_and_port)
            if self.network.client and self.network.client.server_address_and_port:
                log.info(
                    "finished subscribing to %i addresses on %s:%i", len(addresses),
                    *self.network.client.server_address_and_port
                )

    def process_status_update(self, update):
        address, remote_status = update
        self._update_tasks.add(self.update_history(address, remote_status))

    async def update_history(self, address, remote_status, address_manager: AddressManager = None,
                             reattempt_update: bool = True):
        async with self._address_update_locks[address]:
            self._known_addresses_out_of_sync.discard(address)
            local_status, local_history = await self.get_local_status_and_history(address)

            if local_status == remote_status:
                return True

            remote_history = await self.network.retriable_call(self.network.get_history, address)
            remote_history = list(map(itemgetter('tx_hash', 'height'), remote_history))
            we_need = set(remote_history) - set(local_history)
            if not we_need:
                remote_missing = set(local_history) - set(remote_history)
                if remote_missing:
                    log.warning(
                        "%i transactions we have for %s are not in the remote address history",
                        len(remote_missing), address
                    )
                return True

            to_request = {}
            pending_synced_history = {}
            already_synced = set()

            already_synced_offset = 0
            for i, (txid, remote_height) in enumerate(remote_history):
                if i == already_synced_offset and i < len(local_history) and local_history[i] == (txid, remote_height):
                    pending_synced_history[i] = f'{txid}:{remote_height}:'
                    already_synced.add((txid, remote_height))
                    already_synced_offset += 1
                    continue

            tx_indexes = {}

            for i, (txid, remote_height) in enumerate(remote_history):
                tx_indexes[txid] = i
                if (txid, remote_height) in already_synced:
                    continue
                to_request[i] = (txid, remote_height)

            log.debug(
                "request %i transactions, %i/%i for %s are already synced", len(to_request), len(already_synced),
                len(remote_history), address
            )
            remote_history_txids = {txid for txid, _ in remote_history}
            async for tx in self.request_synced_transactions(to_request, remote_history_txids, address):
                self.maybe_has_channel_key(tx)
                pending_synced_history[tx_indexes[tx.id]] = f"{tx.id}:{tx.height}:"
                if len(pending_synced_history) % 100 == 0:
                    log.info("Syncing address %s: %d/%d", address, len(pending_synced_history), len(to_request))
            log.info("Sync finished for address %s: %d/%d", address, len(pending_synced_history), len(to_request))

            assert len(pending_synced_history) == len(remote_history), \
                f"{len(pending_synced_history)} vs {len(remote_history)} for {address}"
            synced_history = ""
            for remote_i, i in zip(range(len(remote_history)), sorted(pending_synced_history.keys())):
                assert i == remote_i, f"{i} vs {remote_i}"
                txid, height = remote_history[remote_i]
                if f"{txid}:{height}:" != pending_synced_history[i]:
                    log.warning("history mismatch: %s vs %s", remote_history[remote_i], pending_synced_history[i])
                synced_history += pending_synced_history[i]
            await self.db.set_address_history(address, synced_history)

            if address_manager is None:
                address_manager = await self.get_address_manager_for_address(address)

            if address_manager is not None:
                await address_manager.ensure_address_gap()

            local_status, local_history = \
                await self.get_local_status_and_history(address, synced_history)

            if local_status != remote_status:
                if local_history == remote_history:
                    log.warning(
                        "%s has a synced history but a mismatched status", address
                    )
                    return True
                remote_set = set(remote_history)
                local_set = set(local_history)
                log.warning(
                    "%s is out of sync after syncing.\n"
                    "Remote: %s with %d items (%i unique), local: %s with %d items (%i unique).\n"
                    "Histories are mismatched on %i items.\n"
                    "Local is missing\n"
                    "%s\n"
                    "Remote is missing\n"
                    "%s\n"
                    "******",
                    address, remote_status, len(remote_history), len(remote_set),
                    local_status, len(local_history), len(local_set), len(remote_set.symmetric_difference(local_set)),
                    "\n".join([f"{txid} - {height}" for txid, height in local_set.difference(remote_set)]),
                    "\n".join([f"{txid} - {height}" for txid, height in remote_set.difference(local_set)])
                )
                self._known_addresses_out_of_sync.add(address)
                return False
            else:
                log.debug("finished syncing transaction history for %s, %i known txs", address, len(local_history))
                return True

    async def maybe_verify_transaction(self, tx, remote_height, merkle=None):
        tx.height = remote_height
        if 0 < remote_height < len(self.headers):
            # can't be tx.pending_verifications == 1 because we have to handle the transaction_show case
            if not merkle:
                merkle = await self.network.retriable_call(self.network.get_merkle, tx.id, remote_height)
            if 'merkle' not in merkle:
                return
            merkle_root = self.get_root_of_merkle_tree(merkle['merkle'], merkle['pos'], tx.hash)
            header = await self.headers.get(remote_height)
            tx.position = merkle['pos']
            tx.is_verified = merkle_root == header['merkle_root']
        return tx

    def maybe_has_channel_key(self, tx):
        for txo in tx._outputs:
            if txo.can_decode_claim and txo.claim.is_channel:
                for account in self.accounts:
                    account.deterministic_channel_keys.maybe_generate_deterministic_key_for_channel(txo)

    async def request_transactions(self, to_request: Tuple[Tuple[str, int], ...], cached=False):
        batches = [[]]
        remote_heights = {}
        cache_hits = set()

        for txid, height in sorted(to_request, key=lambda x: x[1]):
            if cached:
                cached_tx = self._tx_cache.get(txid)
                if cached_tx is not None:
                    if cached_tx.tx is not None and cached_tx.tx.is_verified:
                        cache_hits.add(txid)
                        continue
                else:
                    self._tx_cache[txid] = TransactionCacheItem()
            remote_heights[txid] = height
            if len(batches[-1]) == 100:
                batches.append([])
            batches[-1].append(txid)
        if not batches[-1]:
            batches.pop()
        if cached and cache_hits:
            yield {txid: self._tx_cache[txid].tx for txid in cache_hits}

        for batch in batches:
            txs = await self._single_batch(batch, remote_heights)
            if cached:
                for txid, tx in txs.items():
                    self._tx_cache[txid].tx = tx
            yield txs

    async def request_synced_transactions(self, to_request, remote_history, address):
        async for txs in self.request_transactions(((txid, height) for txid, height in to_request.values())):
            for tx in txs.values():
                yield tx
            await self._sync_and_save_batch(address, remote_history, txs)

    async def _single_batch(self, batch, remote_heights):
        heights = {remote_heights[txid] for txid in batch}
        unrestriced = 0 < min(heights) < max(heights) < max(self.headers.checkpoints or [0])
        batch_result = await self.network.retriable_call(self.network.get_transaction_batch, batch, not unrestriced)
        txs = {}
        for txid, (raw, merkle) in batch_result.items():
            remote_height = remote_heights[txid]
            tx = Transaction(unhexlify(raw), height=remote_height)
            txs[tx.id] = tx
            await self.maybe_verify_transaction(tx, remote_height, merkle)
        return txs

    async def _sync_and_save_batch(self, address, remote_history, pending_txs):
        await asyncio.gather(*(self._sync(tx, remote_history, pending_txs) for tx in pending_txs.values()))
        await self.db.save_transaction_io_batch(
            pending_txs.values(), address, self.address_to_hash160(address), ""
        )
        while pending_txs:
            self._on_transaction_controller.add(TransactionEvent(address, pending_txs.popitem()[1]))

    async def _sync(self, tx, remote_history, pending_txs):
        check_db_for_txos = {}
        for txi in tx.inputs:
            if txi.txo_ref.txo is not None:
                continue
            wanted_txid = txi.txo_ref.tx_ref.id
            if wanted_txid not in remote_history:
                continue
            if wanted_txid in pending_txs:
                txi.txo_ref = pending_txs[wanted_txid].outputs[txi.txo_ref.position].ref
            else:
                check_db_for_txos[txi] = txi.txo_ref.id

        referenced_txos = {} if not check_db_for_txos else {
            txo.id: txo for txo in await self.db.get_txos(
                txoid__in=list(check_db_for_txos.values()), order_by='txo.txoid', no_tx=True
            )
        }

        for txi in check_db_for_txos:
            if txi.txo_ref.id in referenced_txos:
                txi.txo_ref = referenced_txos[txi.txo_ref.id].ref
            else:
                tx_from_db = await self.db.get_transaction(txid=txi.txo_ref.tx_ref.id)
                if tx_from_db is None:
                    log.warning("%s not on db, not on cache, but on remote history!", txi.txo_ref.id)
                else:
                    txi.txo_ref = tx_from_db.outputs[txi.txo_ref.position].ref
        return tx

    async def get_address_manager_for_address(self, address) -> Optional[AddressManager]:
        details = await self.db.get_address(address=address)
        for account in self.accounts:
            if account.id == details['account']:
                return account.address_managers[details['chain']]
        return None

    async def broadcast_or_release(self, tx, blocking=False):
        try:
            await self.broadcast(tx)
        except:
            await self.release_tx(tx)
            raise
        if blocking:
            await self.wait(tx, timeout=None)

    def broadcast(self, tx):
        # broadcast can't be a retriable call yet
        return self.network.broadcast(hexlify(tx.raw).decode())

    async def wait(self, tx: Transaction, height=-1, timeout=1):
        timeout = timeout or 600  # after 10 minutes there is almost 0 hope
        addresses = set()
        for txi in tx.inputs:
            if txi.txo_ref.txo is not None:
                addresses.add(
                    self.hash160_to_address(txi.txo_ref.txo.pubkey_hash)
                )
        for txo in tx.outputs:
            if txo.is_pubkey_hash:
                addresses.add(self.hash160_to_address(txo.pubkey_hash))
            elif txo.is_script_hash:
                addresses.add(self.hash160_to_script_address(txo.script_hash))
        start = int(time.perf_counter())
        while timeout and (int(time.perf_counter()) - start) <= timeout:
            if await self._wait_round(tx, height, addresses):
                return
        raise asyncio.TimeoutError(f'Timed out waiting for transaction. {tx.id}')

    async def _wait_round(self, tx: Transaction, height: int, addresses: Iterable[str]):
        records = await self.db.get_addresses(address__in=addresses)
        _, pending = await asyncio.wait([
            self.on_transaction.where(partial(
                lambda a, e: a == e.address and e.tx.height >= height and e.tx.id == tx.id,
                address_record['address']
            )) for address_record in records
        ], timeout=1)
        if not pending:
            return True
        records = await self.db.get_addresses(address__in=addresses)
        for record in records:
            local_history = (await self.get_local_status_and_history(
                record['address'], history=record['history']
            ))[1] if record['history'] else []
            for txid, local_height in local_history:
                if txid == tx.id:
                    if local_height >= height or (local_height == 0 and height > local_height):
                        return True
                    log.warning(
                        "local history has higher height than remote for %s (%i vs %i)", txid,
                        local_height, height
                    )
                    return False
            log.warning(
                "local history does not contain %s, requested height %i", tx.id, height
            )
        return False

    async def _inflate_outputs(
            self, query, accounts,
            include_purchase_receipt=False,
            include_is_my_output=False,
            include_sent_supports=False,
            include_sent_tips=False,
            include_received_tips=False) -> Tuple[List[Output], dict, int, int]:
        encoded_outputs = await query
        outputs = Outputs.from_base64(encoded_outputs or '')  # TODO: why is the server returning None?
        txs: List[Transaction] = []
        if len(outputs.txs) > 0:
            async for tx in self.request_transactions(tuple(outputs.txs), cached=True):
                txs.extend(tx.values())

        _txos, blocked = outputs.inflate(txs)

        txos = []
        for txo in _txos:
            if isinstance(txo, Output):
                # transactions and outputs are cached and shared between wallets
                # we don't want to leak informaion between wallet so we add the
                # wallet specific metadata on throw away copies of the txos
                txo = copy.copy(txo)
                channel = txo.channel
                txo.purchase_receipt = None
                txo.update_annotations(None)
                txo.channel = channel
            txos.append(txo)

        includes = (
            include_purchase_receipt, include_is_my_output,
            include_sent_supports, include_sent_tips
        )
        if accounts and any(includes):
            receipts = {}
            if include_purchase_receipt:
                priced_claims = []
                for txo in txos:
                    if isinstance(txo, Output) and txo.has_price:
                        priced_claims.append(txo)
                if priced_claims:
                    receipts = {
                        txo.purchased_claim_id: txo for txo in
                        await self.db.get_purchases(
                            accounts=accounts,
                            purchased_claim_id__in=[c.claim_id for c in priced_claims]
                        )
                    }
            for txo in txos:
                if isinstance(txo, Output) and txo.can_decode_claim:
                    if include_purchase_receipt:
                        txo.purchase_receipt = receipts.get(txo.claim_id)
                    if include_is_my_output:
                        mine = await self.db.get_txo_count(
                            claim_id=txo.claim_id, txo_type__in=CLAIM_TYPES, is_my_output=True,
                            is_spent=False, accounts=accounts
                        )
                        if mine:
                            txo.is_my_output = True
                        else:
                            txo.is_my_output = False
                    if include_sent_supports:
                        supports = await self.db.get_txo_sum(
                            claim_id=txo.claim_id, txo_type=TXO_TYPES['support'],
                            is_my_input=True, is_my_output=True,
                            is_spent=False, accounts=accounts
                        )
                        txo.sent_supports = supports
                    if include_sent_tips:
                        tips = await self.db.get_txo_sum(
                            claim_id=txo.claim_id, txo_type=TXO_TYPES['support'],
                            is_my_input=True, is_my_output=False,
                            accounts=accounts
                        )
                        txo.sent_tips = tips
                    if include_received_tips:
                        tips = await self.db.get_txo_sum(
                            claim_id=txo.claim_id, txo_type=TXO_TYPES['support'],
                            is_my_input=False, is_my_output=True,
                            accounts=accounts
                        )
                        txo.received_tips = tips
        # For reposts, apply any deletions/edits specified.
        for txo in txos:
            if isinstance(txo, Output) and txo.can_decode_claim:
                if not txo.claim.is_repost:
                    continue
                reposted_txo = txo.original_reposted_claim
                if isinstance(reposted_txo, Output) and reposted_txo.can_decode_claim:
                    modified_claim = txo.claim.repost.apply(reposted_txo.claim)
                    if modified_claim is reposted_txo.claim:
                        # Claim was not modified. The reposted_claim is the
                        # same as original_reposted_claim.
                        txo.reposted_claim = txo.original_reposted_claim
                        continue
                    # Make a deep copy so we can modify the txo without
                    # disturbing the TX cache contents.
                    modified_txo = copy.deepcopy(reposted_txo)
                    modified_txo.claim.message.CopyFrom(modified_claim.message)
                    # Set the reposted_claim field reported in results.
                    txo.reposted_claim = modified_txo
        return txos, blocked, outputs.offset, outputs.total

    async def resolve(self, accounts, urls, **kwargs):
        txos = []
        urls_copy = list(urls)
        resolve = partial(self.network.retriable_call, self.network.resolve)
        while urls_copy:
            batch, urls_copy = urls_copy[:100], urls_copy[100:]
            txos.extend(
                (await self._inflate_outputs(
                    resolve(batch), accounts, **kwargs
                ))[0]
            )

        assert len(urls) == len(txos), "Mismatch between urls requested for resolve and responses received."
        result = {}
        for url, txo in zip(urls, txos):
            if txo:
                if isinstance(txo, Output) and URL.parse(url).has_stream_in_channel:
                    if not txo.channel or not txo.is_signed_by(txo.channel, self):
                        txo = {'error': {'name': INVALID, 'text': f'{url} has invalid channel signature'}}
            else:
                txo = {'error': {'name': NOT_FOUND, 'text': f'{url} did not resolve to a claim'}}
            result[url] = txo
        return result

    async def sum_supports(self, new_sdk_server, **kwargs) -> List[Dict]:
        return await self.network.sum_supports(new_sdk_server, **kwargs)

    async def claim_search(
            self, accounts,
            include_purchase_receipt=False,
            include_is_my_output=False,
            **kwargs) -> Tuple[List[Output], dict, int, int]:
        return await self._inflate_outputs(
            self.network.claim_search(**kwargs), accounts,
            include_purchase_receipt=include_purchase_receipt,
            include_is_my_output=include_is_my_output
        )

    # async def get_claim_by_claim_id(self, accounts, claim_id, **kwargs) -> Output:
    #     return await self.network.get_claim_by_id(claim_id)

    async def get_claim_by_claim_id(self, claim_id, accounts=None, include_purchase_receipt=False,
                                    include_is_my_output=False):
        accounts = accounts or []
        # return await self.network.get_claim_by_id(claim_id)
        inflated = await self._inflate_outputs(
            self.network.get_claim_by_id(claim_id), accounts,
            include_purchase_receipt=include_purchase_receipt,
            include_is_my_output=include_is_my_output,
        )
        txos = inflated[0]
        if txos:
            return txos[0]

    async def _report_state(self):
        try:
            for account in self.accounts:
                balance = dewies_to_lbc(await account.get_balance(include_claims=True))
                channel_count = await account.get_channel_count()
                claim_count = await account.get_claim_count()
                if isinstance(account.receiving, SingleKey):
                    log.info("Loaded single key account %s with %s LBC. "
                             "%d channels, %d certificates and %d claims",
                             account.id, balance, channel_count, len(account.channel_keys), claim_count)
                else:
                    total_receiving = len(await account.receiving.get_addresses())
                    total_change = len(await account.change.get_addresses())
                    log.info("Loaded account %s with %s LBC, %d receiving addresses (gap: %d), "
                             "%d change addresses (gap: %d), %d channels, %d certificates and %d claims. ",
                             account.id, balance, total_receiving, account.receiving.gap, total_change,
                             account.change.gap, channel_count, len(account.channel_keys), claim_count)
        except Exception as err:
            if isinstance(err, asyncio.CancelledError):  # TODO: remove when updated to 3.8
                raise
            log.exception(
                'Failed to display wallet state, please file issue '
                'for this bug along with the traceback you see below:')

    async def _reset_balance_cache(self, e: TransactionEvent):
        account_ids = [
            r['account'] for r in await self.db.get_addresses(('account',), address=e.address)
        ]
        for account_id in account_ids:
            if account_id in self._balance_cache:
                del self._balance_cache[account_id]

    @staticmethod
    def constraint_spending_utxos(constraints):
        constraints['txo_type__in'] = (0, TXO_TYPES['purchase'])

    async def get_purchases(self, resolve=False, **constraints):
        purchases = await self.db.get_purchases(**constraints)
        if resolve:
            claim_ids = [p.purchased_claim_id for p in purchases]
            try:
                resolved, _, _, _ = await self.claim_search([], claim_ids=claim_ids)
            except Exception as err:
                if isinstance(err, asyncio.CancelledError):  # TODO: remove when updated to 3.8
                    raise
                log.exception("Resolve failed while looking up purchased claim ids:")
                resolved = []
            lookup = {claim.claim_id: claim for claim in resolved}
            for purchase in purchases:
                purchase.purchased_claim = lookup.get(purchase.purchased_claim_id)
        return purchases

    def get_purchase_count(self, resolve=False, **constraints):
        return self.db.get_purchase_count(**constraints)

    async def _resolve_for_local_results(self, accounts, txos):
        txos = await self._resolve_for_local_claim_results(accounts, txos)
        txos = await self._resolve_for_local_support_results(accounts, txos)
        return txos

    async def _resolve_for_local_claim_results(self, accounts, txos):
        results = []
        response = await self.resolve(
            accounts, [txo.permanent_url for txo in txos if txo.can_decode_claim]
        )
        for txo in txos:
            resolved = response.get(txo.permanent_url) if txo.can_decode_claim else None
            if isinstance(resolved, Output):
                resolved.update_annotations(txo)
                results.append(resolved)
            else:
                if isinstance(resolved, dict) and 'error' in resolved:
                    txo.meta['error'] = resolved['error']
                results.append(txo)
        return results

    async def _resolve_for_local_support_results(self, accounts, txos):
        channel_ids = set()
        signed_support_txos = []
        for txo in txos:
            support = txo.can_decode_support
            if support and support.signing_channel_id:
                channel_ids.add(support.signing_channel_id)
                signed_support_txos.append(txo)
        if channel_ids:
            channels = {
                channel.claim_id: channel for channel in
                (await self.claim_search(accounts, claim_ids=list(channel_ids)))[0]
            }
            for txo in signed_support_txos:
                txo.channel = channels.get(txo.support.signing_channel_id)
        return txos

    async def get_claims(self, resolve=False, **constraints):
        claims = await self.db.get_claims(**constraints)
        if resolve:
            return await self._resolve_for_local_results(constraints.get('accounts', []), claims)
        return claims

    def get_claim_count(self, **constraints):
        return self.db.get_claim_count(**constraints)

    async def get_streams(self, resolve=False, **constraints):
        streams = await self.db.get_streams(**constraints)
        if resolve:
            return await self._resolve_for_local_results(constraints.get('accounts', []), streams)
        return streams

    def get_stream_count(self, **constraints):
        return self.db.get_stream_count(**constraints)

    async def get_channels(self, resolve=False, **constraints):
        channels = await self.db.get_channels(**constraints)
        if resolve:
            return await self._resolve_for_local_results(constraints.get('accounts', []), channels)
        return channels

    def get_channel_count(self, **constraints):
        return self.db.get_channel_count(**constraints)

    async def resolve_collection(self, collection, offset=0, page_size=1):
        claim_ids = collection.claim.collection.claims.ids[offset:page_size + offset]
        try:
            resolve_results, _, _, _ = await self.claim_search([], claim_ids=claim_ids)
        except Exception as err:
            if isinstance(err, asyncio.CancelledError):  # TODO: remove when updated to 3.8
                raise
            log.exception("Resolve failed while looking up collection claim ids:")
            return []
        claims = []
        for claim_id in claim_ids:
            found = False
            for txo in resolve_results:
                if txo.claim_id == claim_id:
                    claims.append(txo)
                    found = True
                    break
            if not found:
                claims.append(None)
        return claims

    async def get_collections(self, resolve_claims=0, resolve=False, **constraints):
        collections = await self.db.get_collections(**constraints)
        if resolve:
            collections = await self._resolve_for_local_results(constraints.get('accounts', []), collections)
        if resolve_claims > 0:
            for collection in collections:
                collection.claims = await self.resolve_collection(collection, page_size=resolve_claims)
        return collections

    def get_collection_count(self, resolve_claims=0, **constraints):
        return self.db.get_collection_count(**constraints)

    def get_supports(self, **constraints):
        return self.db.get_supports(**constraints)

    def get_support_count(self, **constraints):
        return self.db.get_support_count(**constraints)

    async def get_transaction_history(self, read_only=False, **constraints):
        txs: List[Transaction] = await self.db.get_transactions(
            include_is_my_output=True, include_is_spent=True,
            read_only=read_only, **constraints
        )
        headers = self.headers
        history = []
        for tx in txs:  # pylint: disable=too-many-nested-blocks
            ts = headers.estimated_timestamp(tx.height)
            item = {
                'txid': tx.id,
                'timestamp': ts,
                'date': datetime.fromtimestamp(ts).isoformat(' ')[:-3] if tx.height > 0 else None,
                'confirmations': (headers.height + 1) - tx.height if tx.height > 0 else 0,
                'claim_info': [],
                'update_info': [],
                'support_info': [],
                'abandon_info': [],
                'purchase_info': []
            }
            is_my_inputs = all(txi.is_my_input for txi in tx.inputs)
            if is_my_inputs:
                # fees only matter if we are the ones paying them
                item['value'] = dewies_to_lbc(tx.net_account_balance + tx.fee)
                item['fee'] = dewies_to_lbc(-tx.fee)
            else:
                # someone else paid the fees
                item['value'] = dewies_to_lbc(tx.net_account_balance)
                item['fee'] = '0.0'
            for txo in tx.my_claim_outputs:
                item['claim_info'].append({
                    'address': txo.get_address(self),
                    'balance_delta': dewies_to_lbc(-txo.amount),
                    'amount': dewies_to_lbc(txo.amount),
                    'claim_id': txo.claim_id,
                    'claim_name': txo.claim_name,
                    'nout': txo.position,
                    'is_spent': txo.is_spent,
                })
            for txo in tx.my_update_outputs:
                if is_my_inputs:  # updating my own claim
                    previous = None
                    for txi in tx.inputs:
                        if txi.txo_ref.txo is not None:
                            other_txo = txi.txo_ref.txo
                            if (other_txo.is_claim or other_txo.script.is_support_claim) \
                                and other_txo.claim_id == txo.claim_id:
                                previous = other_txo
                                break
                    if previous is not None:
                        item['update_info'].append({
                            'address': txo.get_address(self),
                            'balance_delta': dewies_to_lbc(previous.amount - txo.amount),
                            'amount': dewies_to_lbc(txo.amount),
                            'claim_id': txo.claim_id,
                            'claim_name': txo.claim_name,
                            'nout': txo.position,
                            'is_spent': txo.is_spent,
                        })
                else:  # someone sent us their claim
                    item['update_info'].append({
                        'address': txo.get_address(self),
                        'balance_delta': dewies_to_lbc(0),
                        'amount': dewies_to_lbc(txo.amount),
                        'claim_id': txo.claim_id,
                        'claim_name': txo.claim_name,
                        'nout': txo.position,
                        'is_spent': txo.is_spent,
                    })
            for txo in tx.my_support_outputs:
                item['support_info'].append({
                    'address': txo.get_address(self),
                    'balance_delta': dewies_to_lbc(txo.amount if not is_my_inputs else -txo.amount),
                    'amount': dewies_to_lbc(txo.amount),
                    'claim_id': txo.claim_id,
                    'claim_name': txo.claim_name,
                    'is_tip': not is_my_inputs,
                    'nout': txo.position,
                    'is_spent': txo.is_spent,
                })
            if is_my_inputs:
                for txo in tx.other_support_outputs:
                    item['support_info'].append({
                        'address': txo.get_address(self),
                        'balance_delta': dewies_to_lbc(-txo.amount),
                        'amount': dewies_to_lbc(txo.amount),
                        'claim_id': txo.claim_id,
                        'claim_name': txo.claim_name,
                        'is_tip': is_my_inputs,
                        'nout': txo.position,
                        'is_spent': txo.is_spent,
                    })
            for txo in tx.my_abandon_outputs:
                item['abandon_info'].append({
                    'address': txo.get_address(self),
                    'balance_delta': dewies_to_lbc(txo.amount),
                    'amount': dewies_to_lbc(txo.amount),
                    'claim_id': txo.claim_id,
                    'claim_name': txo.claim_name,
                    'nout': txo.position
                })
            for txo in tx.any_purchase_outputs:
                item['purchase_info'].append({
                    'address': txo.get_address(self),
                    'balance_delta': dewies_to_lbc(txo.amount if not is_my_inputs else -txo.amount),
                    'amount': dewies_to_lbc(txo.amount),
                    'claim_id': txo.purchased_claim_id,
                    'nout': txo.position,
                    'is_spent': txo.is_spent,
                })
            history.append(item)
        return history

    def get_transaction_history_count(self, read_only=False, **constraints):
        return self.db.get_transaction_count(read_only=read_only, **constraints)

    async def get_detailed_balance(self, accounts, confirmations=0):
        result = {
            'total': 0,
            'available': 0,
            'reserved': 0,
            'reserved_subtotals': {
                'claims': 0,
                'supports': 0,
                'tips': 0
            }
        }
        for account in accounts:
            balance = self._balance_cache.get(account.id)
            if not balance:
                balance = self._balance_cache[account.id] = \
                    await account.get_detailed_balance(confirmations)
            for key, value in balance.items():
                if key == 'reserved_subtotals':
                    for subkey, subvalue in value.items():
                        result['reserved_subtotals'][subkey] += subvalue
                else:
                    result[key] += value
        return result


class TestNetLedger(Ledger):
    network_name = 'testnet'
    pubkey_address_prefix = bytes((111,))
    script_address_prefix = bytes((196,))
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')
    checkpoints = {}


class RegTestLedger(Ledger):
    network_name = 'regtest'
    headers_class = UnvalidatedHeaders
    pubkey_address_prefix = bytes((111,))
    script_address_prefix = bytes((196,))
    extended_public_key_prefix = unhexlify('043587cf')
    extended_private_key_prefix = unhexlify('04358394')

    max_target = 0x7fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    genesis_hash = '6e3fcf1299d4ec5d79c3a4c91d624a4acf9e2e173d95a1a0504f677669687556'
    genesis_bits = 0x207fffff
    target_timespan = 1
    checkpoints = {}
