import os
import zlib
import base64
import asyncio
import logging
from io import StringIO
from datetime import datetime
from functools import partial
from operator import itemgetter
from collections import defaultdict
from binascii import hexlify, unhexlify
from typing import Dict, Tuple, Type, Iterable, List, Optional, DefaultDict, NamedTuple

import pylru
from lbry.schema.result import Outputs, INVALID, NOT_FOUND
from lbry.schema.url import URL
from lbry.crypto.hash import hash160, double_sha256, sha256
from lbry.crypto.base58 import Base58

from .tasks import TaskGroup
from .database import Database
from .stream import StreamController
from .dewies import dewies_to_lbc
from .account import Account, AddressManager, SingleKey
from .network import Network
from .transaction import Transaction, Output
from .header import Headers, UnvalidatedHeaders
from .constants import TXO_TYPES, COIN, NULL_HASH32
from .bip32 import PubKey, PrivateKey
from .coinselection import CoinSelector


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
    __slots__ = '_tx', 'lock', 'has_tx'

    def __init__(self, tx: Optional[Transaction] = None, lock: Optional[asyncio.Lock] = None):
        self.has_tx = asyncio.Event()
        self.lock = lock or asyncio.Lock()
        self._tx = self.tx = tx

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
    default_fee_per_name_char = 200000

    def __init__(self, config=None):
        self.config = config or {}
        self.db: Database = self.config.get('db') or Database(
            os.path.join(self.path, "blockchain.db")
        )
        self.db.ledger = self
        self.headers: Headers = self.config.get('headers') or self.headers_class(
            os.path.join(self.path, "headers")
        )
        self.network: Network = self.config.get('network') or Network(self)
        self.network.on_header.listen(self.receive_header)
        self.network.on_status.listen(self.process_status_update)
        self.network.on_connected.listen(self.join_network)

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

        self._tx_cache = pylru.lrucache(100000)
        self._update_tasks = TaskGroup()
        self._utxo_reservation_lock = asyncio.Lock()
        self._header_processing_lock = asyncio.Lock()
        self._address_update_locks: DefaultDict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

        self.coin_selection_strategy = None
        self._known_addresses_out_of_sync = set()

        self.fee_per_name_char = self.config.get('fee_per_name_char', self.default_fee_per_name_char)
        self._balance_cache = pylru.lrucache(100000)

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
    def is_valid_address(cls, address):
        decoded = Base58.decode_check(address)
        return decoded[0] == cls.pubkey_address_prefix[0]

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

    async def get_public_key_for_address(self, wallet, address) -> Optional[PubKey]:
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
            utxos = await account.get_utxos()
            for utxo in utxos:
                estimators.append(utxo.get_estimator(self))
        return estimators

    async def get_addresses(self, **constraints):
        return await self.db.get_addresses(**constraints)

    def get_address_count(self, **constraints):
        return self.db.get_address_count(**constraints)

    async def get_spendable_utxos(self, amount: int, funding_accounts):
        async with self._utxo_reservation_lock:
            txos = await self.get_effective_amount_estimators(funding_accounts)
            fee = Output.pay_pubkey_hash(COIN, NULL_HASH32).get_fee(self)
            selector = CoinSelector(amount, fee)
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

    async def get_txos(self, resolve=False, **constraints):
        txos = await self.db.get_txos(**constraints)
        if resolve:
            return await self._resolve_for_local_results(constraints.get('accounts', []), txos)
        return txos

    def get_txo_count(self, **constraints):
        return self.db.get_txo_count(**constraints)

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
        first_connection = self.network.on_connected.first
        asyncio.ensure_future(self.network.start())
        await first_connection
        async with self._header_processing_lock:
            await self._update_tasks.add(self.initial_headers_sync())
        await self._on_ready_controller.stream.first
        await asyncio.gather(*(a.maybe_migrate_certificates() for a in self.accounts))
        await asyncio.gather(*(a.save_max_gap() for a in self.accounts))
        if len(self.accounts) > 10:
            log.info("Loaded %i accounts", len(self.accounts))
        else:
            await self._report_state()
        self.on_transaction.listen(self._reset_balance_cache)

    async def join_network(self, *_):
        log.info("Subscribing and updating accounts.")
        async with self._header_processing_lock:
            await self.update_headers()
        await self.subscribe_accounts()
        await self._update_tasks.done.wait()
        self._on_ready_controller.add(True)

    async def stop(self):
        self._update_tasks.cancel()
        await self._update_tasks.done.wait()
        await self.network.stop()
        await self.db.close()
        await self.headers.close()

    @property
    def local_height_including_downloaded_height(self):
        return max(self.headers.height, self._download_height)

    async def initial_headers_sync(self):
        target = self.network.remote_height + 1
        current = len(self.headers)
        get_chunk = partial(self.network.retriable_call, self.network.get_headers, count=4096, b64=True)
        chunks = [asyncio.create_task(get_chunk(height)) for height in range(current, target, 4096)]
        total = 0
        async with self.headers.checkpointed_connector() as buffer:
            for chunk in chunks:
                headers = await chunk
                total += buffer.write(
                    zlib.decompress(base64.b64decode(headers['base64']), wbits=-15, bufsize=600_000)
                )
                self._download_height = current + total // self.headers.header_size
                log.info("Headers sync: %s / %s", self._download_height, target)

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
                log.info("subscribed to %i/%i addresses on %s:%i", len(addresses) - len(addresses_remaining),
                         len(addresses), *self.network.client.server_address_and_port)
            log.info(
                "finished subscribing to %i addresses on %s:%i", len(addresses),
                *self.network.client.server_address_and_port
            )

    def process_status_update(self, update):
        address, remote_status = update
        self._update_tasks.add(self.update_history(address, remote_status))

    async def update_history(self, address, remote_status, address_manager: AddressManager = None):
        async with self._address_update_locks[address]:
            self._known_addresses_out_of_sync.discard(address)

            local_status, local_history = await self.get_local_status_and_history(address)

            if local_status == remote_status:
                return True

            remote_history = await self.network.retriable_call(self.network.get_history, address)
            remote_history = list(map(itemgetter('tx_hash', 'height'), remote_history))
            we_need = set(remote_history) - set(local_history)
            if not we_need:
                return True

            cache_tasks: List[asyncio.Future[Transaction]] = []
            synced_history = StringIO()
            for i, (txid, remote_height) in enumerate(remote_history):
                if i < len(local_history) and local_history[i] == (txid, remote_height) and not cache_tasks:
                    synced_history.write(f'{txid}:{remote_height}:')
                else:
                    check_local = (txid, remote_height) not in we_need
                    cache_tasks.append(asyncio.ensure_future(
                        self.cache_transaction(txid, remote_height, check_local=check_local)
                    ))

            synced_txs = []
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
                        check_db_for_txos.append(txi.txo_ref.id)

                referenced_txos = {} if not check_db_for_txos else {
                    txo.id: txo for txo in await self.db.get_txos(txoid__in=check_db_for_txos, no_tx=True)
                }

                for txi in tx.inputs:
                    if txi.txo_ref.txo is not None:
                        continue
                    referenced_txo = referenced_txos.get(txi.txo_ref.id)
                    if referenced_txo is not None:
                        txi.txo_ref = referenced_txo.ref

                synced_history.write(f'{tx.id}:{tx.height}:')
                synced_txs.append(tx)

            await self.db.save_transaction_io_batch(
                synced_txs, address, self.address_to_hash160(address), synced_history.getvalue()
            )
            await asyncio.wait([
                self._on_transaction_controller.add(TransactionEvent(address, tx))
                for tx in synced_txs
            ])

            if address_manager is None:
                address_manager = await self.get_address_manager_for_address(address)

            if address_manager is not None:
                await address_manager.ensure_address_gap()

            local_status, local_history = \
                await self.get_local_status_and_history(address, synced_history.getvalue())
            if local_status != remote_status:
                if local_history == remote_history:
                    return True
                log.warning(
                    "Wallet is out of sync after syncing. Remote: %s with %d items, local: %s with %d items",
                    remote_status, len(remote_history), local_status, len(local_history)
                )
                log.warning("local: %s", local_history)
                log.warning("remote: %s", remote_history)
                self._known_addresses_out_of_sync.add(address)
                return False
            else:
                return True

    async def cache_transaction(self, txid, remote_height, check_local=True):
        cache_item = self._tx_cache.get(txid)
        if cache_item is None:
            cache_item = self._tx_cache[txid] = TransactionCacheItem()
        elif cache_item.tx is not None and \
                cache_item.tx.height >= remote_height and \
                (cache_item.tx.is_verified or remote_height < 1):
            return cache_item.tx  # cached tx is already up-to-date

        async with cache_item.lock:

            tx = cache_item.tx

            if tx is None and check_local:
                # check local db
                tx = cache_item.tx = await self.db.get_transaction(txid=txid)

            if tx is None:
                # fetch from network
                _raw = await self.network.retriable_call(self.network.get_transaction, txid, remote_height)
                tx = Transaction(unhexlify(_raw))
                cache_item.tx = tx  # make sure it's saved before caching it

            await self.maybe_verify_transaction(tx, remote_height)
            return tx

    async def maybe_verify_transaction(self, tx, remote_height):
        tx.height = remote_height
        if 0 < remote_height < len(self.headers):
            merkle = await self.network.retriable_call(self.network.get_merkle, tx.id, remote_height)
            merkle_root = self.get_root_of_merkle_tree(merkle['merkle'], merkle['pos'], tx.hash)
            header = self.headers[remote_height]
            tx.position = merkle['pos']
            tx.is_verified = merkle_root == header['merkle_root']

    async def get_address_manager_for_address(self, address) -> Optional[AddressManager]:
        details = await self.db.get_address(address=address)
        for account in self.accounts:
            if account.id == details['account']:
                return account.address_managers[details['chain']]
        return None

    def broadcast(self, tx):
        # broadcast can't be a retriable call yet
        return self.network.broadcast(hexlify(tx.raw).decode())

    async def wait(self, tx: Transaction, height=-1, timeout=1):
        addresses = set()
        for txi in tx.inputs:
            if txi.txo_ref.txo is not None:
                addresses.add(
                    self.hash160_to_address(txi.txo_ref.txo.pubkey_hash)
                )
        for txo in tx.outputs:
            if txo.has_address:
                addresses.add(self.hash160_to_address(txo.pubkey_hash))
        records = await self.db.get_addresses(address__in=addresses)
        _, pending = await asyncio.wait([
            self.on_transaction.where(partial(
                lambda a, e: a == e.address and e.tx.height >= height and e.tx.id == tx.id,
                address_record['address']
            )) for address_record in records
        ], timeout=timeout)
        if pending:
            records = await self.db.get_addresses(address__in=addresses)
            for record in records:
                found = False
                local_history = (await self.get_local_status_and_history(
                    record['address'], history=record['history']
                ))[1] if record['history'] else []
                for txid, local_height in local_history:
                    if txid == tx.id and local_height >= height:
                        found = True
                if not found:
                    print(record['history'], addresses, tx.id)
                    raise asyncio.TimeoutError('Timed out waiting for transaction.')

    async def _inflate_outputs(self, query, accounts) -> Tuple[List[Output], dict, int, int]:
        encoded_outputs = await query
        outputs = Outputs.from_base64(encoded_outputs or b'')  # TODO: why is the server returning None?
        txs = []
        if len(outputs.txs) > 0:
            txs: List[Transaction] = await asyncio.gather(*(
                self.cache_transaction(*tx) for tx in outputs.txs
            ))
            if accounts:
                priced_claims = []
                for tx in txs:
                    for txo in tx.outputs:
                        if txo.has_price:
                            priced_claims.append(txo)
                if priced_claims:
                    receipts = {
                        txo.purchased_claim_id: txo for txo in
                        await self.db.get_purchases(
                            accounts=accounts,
                            purchased_claim_id__in=[c.claim_id for c in priced_claims]
                        )
                    }
                    for txo in priced_claims:
                        txo.purchase_receipt = receipts.get(txo.claim_id)
        txos, blocked = outputs.inflate(txs)
        return txos, blocked, outputs.offset, outputs.total

    async def resolve(self, accounts, urls):
        resolve = partial(self.network.retriable_call, self.network.resolve)
        txos = (await self._inflate_outputs(resolve(urls), accounts))[0]
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

    async def claim_search(self, accounts, **kwargs) -> Tuple[List[Output], dict, int, int]:
        return await self._inflate_outputs(self.network.claim_search(**kwargs), accounts)

    async def get_claim_by_claim_id(self, accounts, claim_id) -> Output:
        for claim in (await self.claim_search(accounts, claim_id=claim_id))[0]:
            return claim

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
        claim_ids = collection.claim.collection.claims.ids[offset:page_size+offset]
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

    async def get_collections(self, resolve_claims=0, **constraints):
        collections = await self.db.get_collections(**constraints)
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

    async def get_transaction_history(self, read_only: bool = False, **constraints):
        txs: List[Transaction] = await self.db.get_transactions(read_only=read_only, **constraints)
        headers = self.headers
        history = []
        for tx in txs:  # pylint: disable=too-many-nested-blocks
            ts = headers[tx.height]['timestamp'] if tx.height > 0 else None
            item = {
                'txid': tx.id,
                'timestamp': ts,
                'date': datetime.fromtimestamp(ts).isoformat(' ')[:-3] if tx.height > 0 else None,
                'confirmations': (headers.height+1) - tx.height if tx.height > 0 else 0,
                'claim_info': [],
                'update_info': [],
                'support_info': [],
                'abandon_info': [],
                'purchase_info': []
            }
            is_my_inputs = all([txi.is_my_account for txi in tx.inputs])
            if is_my_inputs:
                # fees only matter if we are the ones paying them
                item['value'] = dewies_to_lbc(tx.net_account_balance+tx.fee)
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
                            'balance_delta': dewies_to_lbc(previous.amount-txo.amount),
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

    def get_transaction_history_count(self, read_only: bool = False, **constraints):
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
                balance = self._balance_cache[account.id] =\
                    await account.get_detailed_balance(confirmations, reserved_subtotals=True)
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
