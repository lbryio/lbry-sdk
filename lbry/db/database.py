import os
import asyncio
import tempfile
import multiprocessing as mp
from typing import List, Optional, Iterable, Iterator, TypeVar, Generic, TYPE_CHECKING, Dict
from concurrent.futures import Executor, ThreadPoolExecutor, ProcessPoolExecutor
from functools import partial

from sqlalchemy import create_engine, text

from lbry.event import EventController
from lbry.crypto.bip32 import PubKey
from lbry.blockchain.transaction import Transaction, Output
from .constants import TXO_TYPES, CLAIM_TYPE_CODES
from .query_context import initialize, ProgressPublisher
from . import queries as q
from . import sync


if TYPE_CHECKING:
    from lbry.blockchain.ledger import Ledger


def clean_wallet_account_ids(constraints):
    wallet = constraints.pop('wallet', None)
    account = constraints.pop('account', None)
    accounts = constraints.pop('accounts', [])
    if account and not accounts:
        accounts = [account]
    if wallet:
        constraints['wallet_account_ids'] = [account.id for account in wallet.accounts]
        if not accounts:
            accounts = wallet.accounts
    if accounts:
        constraints['account_ids'] = [account.id for account in accounts]


async def add_channel_keys_to_txo_results(accounts: List, txos: Iterable[Output]):
    sub_channels = set()
    for txo in txos:
        if txo.claim.is_channel:
            for account in accounts:
                private_key = await account.get_channel_private_key(
                    txo.claim.channel.public_key_bytes
                )
                if private_key:
                    txo.private_key = private_key
                    break
        if txo.channel is not None:
            sub_channels.add(txo.channel)
    if sub_channels:
        await add_channel_keys_to_txo_results(accounts, sub_channels)

ResultType = TypeVar('ResultType')


class Result(Generic[ResultType]):

    __slots__ = 'rows', 'total', 'censor'

    def __init__(self, rows: List[ResultType], total, censor=None):
        self.rows = rows
        self.total = total
        self.censor = censor

    def __getitem__(self, item: int) -> ResultType:
        return self.rows[item]

    def __iter__(self) -> Iterator[ResultType]:
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)

    def __repr__(self):
        return repr(self.rows)


class Database:

    def __init__(self, ledger: 'Ledger'):
        self.url = ledger.conf.db_url_or_default
        self.ledger = ledger
        self.processes = self._normalize_processes(ledger.conf.processes)
        self.executor: Optional[Executor] = None
        self.message_queue = mp.Queue()
        self.stop_event = mp.Event()
        self._on_progress_controller = EventController()
        self.on_progress = self._on_progress_controller.stream
        self.progress_publisher = ProgressPublisher(
            self.message_queue, self._on_progress_controller
        )

    @staticmethod
    def _normalize_processes(processes):
        if processes == 0:
            return os.cpu_count()
        elif processes > 0:
            return processes
        return 1

    @classmethod
    def temp_sqlite_regtest(cls, lbrycrd_dir=None):
        from lbry import Config, RegTestLedger  # pylint: disable=import-outside-toplevel
        directory = tempfile.mkdtemp()
        conf = Config.with_same_dir(directory)
        if lbrycrd_dir is not None:
            conf.lbrycrd_dir = lbrycrd_dir
        ledger = RegTestLedger(conf)
        return cls(ledger)

    @classmethod
    def temp_sqlite(cls):
        from lbry import Config, Ledger  # pylint: disable=import-outside-toplevel
        conf = Config.with_same_dir(tempfile.mkdtemp())
        return cls(Ledger(conf))

    @classmethod
    def in_memory(cls):
        from lbry import Config, Ledger  # pylint: disable=import-outside-toplevel
        conf = Config.with_same_dir('/dev/null')
        conf.db_url = 'sqlite:///:memory:'
        return cls(Ledger(conf))

    def sync_create(self, name):
        engine = create_engine(self.url)
        db = engine.connect()
        db.execute(text("COMMIT"))
        db.execute(text(f"CREATE DATABASE {name}"))

    async def create(self, name):
        return await asyncio.get_event_loop().run_in_executor(None, self.sync_create, name)

    def sync_drop(self, name):
        engine = create_engine(self.url)
        db = engine.connect()
        db.execute(text("COMMIT"))
        db.execute(text(f"DROP DATABASE IF EXISTS {name}"))

    async def drop(self, name):
        return await asyncio.get_event_loop().run_in_executor(None, self.sync_drop, name)

    async def open(self):
        assert self.executor is None, "Database already open."
        self.progress_publisher.start()
        kwargs = {
            "initializer": initialize,
            "initargs": (
                self.ledger,
                self.message_queue, self.stop_event
            )
        }
        if self.processes > 1:
            self.executor = ProcessPoolExecutor(max_workers=self.processes, **kwargs)
        else:
            self.executor = ThreadPoolExecutor(max_workers=1, **kwargs)
        return await self.run_in_executor(q.check_version_and_create_tables)

    async def close(self):
        self.progress_publisher.stop()
        if self.executor is not None:
            self.executor.shutdown()
            self.executor = None

    async def run_in_executor(self, func, *args, **kwargs):
        if kwargs:
            clean_wallet_account_ids(kwargs)
        return await asyncio.get_event_loop().run_in_executor(
            self.executor, partial(func, *args, **kwargs)
        )

    async def fetch_result(self, func, *args, **kwargs) -> Result:
        rows, total = await self.run_in_executor(func, *args, **kwargs)
        return Result(rows, total)

    async def execute(self, sql):
        return await self.run_in_executor(q.execute, sql)

    async def execute_fetchall(self, sql):
        return await self.run_in_executor(q.execute_fetchall, sql)

    async def process_all_things_after_sync(self):
        return await self.run_in_executor(sync.process_all_things_after_sync)

    async def needs_initial_sync(self) -> bool:
        return (await self.get_best_tx_height()) == -1

    async def get_best_tx_height(self) -> int:
        return await self.run_in_executor(q.get_best_tx_height)

    async def get_best_block_height_for_file(self, file_number) -> int:
        return await self.run_in_executor(q.get_best_block_height_for_file, file_number)

    async def get_blocks_without_filters(self):
        return await self.run_in_executor(q.get_blocks_without_filters)

    async def get_transactions_without_filters(self):
        return await self.run_in_executor(q.get_transactions_without_filters)

    async def get_block_tx_addresses(self, block_hash=None, tx_hash=None):
        return await self.run_in_executor(q.get_block_tx_addresses, block_hash, tx_hash)

    async def get_block_address_filters(self):
        return await self.run_in_executor(q.get_block_address_filters)

    async def get_transaction_address_filters(self, block_hash):
        return await self.run_in_executor(q.get_transaction_address_filters, block_hash)

    async def insert_block(self, block):
        return await self.run_in_executor(q.insert_block, block)

    async def insert_transaction(self, block_hash, tx):
        return await self.run_in_executor(q.insert_transaction, block_hash, tx)

    async def update_address_used_times(self, addresses):
        return await self.run_in_executor(q.update_address_used_times, addresses)

    async def reserve_outputs(self, txos, is_reserved=True):
        txo_hashes = [txo.hash for txo in txos]
        if txo_hashes:
            return await self.run_in_executor(
                q.reserve_outputs, txo_hashes, is_reserved
            )

    async def release_outputs(self, txos):
        return await self.reserve_outputs(txos, is_reserved=False)

    async def release_tx(self, tx):
        return await self.release_outputs([txi.txo_ref.txo for txi in tx.inputs])

    async def release_all_outputs(self, account):
        return await self.run_in_executor(q.release_all_outputs, account.id)

    async def get_balance(self, **constraints):
        return await self.run_in_executor(q.get_balance, **constraints)

    async def get_report(self, accounts):
        return await self.run_in_executor(q.get_report, accounts=accounts)

    async def get_addresses(self, **constraints) -> Result[dict]:
        addresses = await self.fetch_result(q.get_addresses, **constraints)
        if addresses and 'pubkey' in addresses[0]:
            for address in addresses:
                address['pubkey'] = PubKey(
                    self.ledger, bytes(address.pop('pubkey')), bytes(address.pop('chain_code')),
                    address.pop('n'), address.pop('depth')
                )
        return addresses

    async def get_all_addresses(self):
        return await self.run_in_executor(q.get_all_addresses)

    async def get_address(self, **constraints):
        for address in await self.get_addresses(limit=1, **constraints):
            return address

    async def add_keys(self, account, chain, pubkeys):
        return await self.run_in_executor(q.add_keys, account, chain, pubkeys)

    async def get_transactions(self, **constraints) -> Result[Transaction]:
        return await self.fetch_result(q.get_transactions, **constraints)

    async def get_transaction(self, **constraints) -> Optional[Transaction]:
        txs = await self.get_transactions(limit=1, **constraints)
        if txs:
            return txs[0]

    async def get_purchases(self, **constraints) -> Result[Output]:
        return await self.fetch_result(q.get_purchases, **constraints)

    async def search_claims(self, **constraints) -> Result[Output]:
        #assert set(constraints).issubset(SEARCH_PARAMS), \
        #    f"Search query contains invalid arguments: {set(constraints).difference(SEARCH_PARAMS)}"
        claims, total, censor = await self.run_in_executor(q.search_claims, **constraints)
        return Result(claims, total, censor)

    async def search_supports(self, **constraints) -> Result[Output]:
        return await self.fetch_result(q.search_supports, **constraints)

    async def resolve(self, *urls) -> Dict[str, Output]:
        return await self.run_in_executor(q.resolve, *urls)

    async def get_txo_sum(self, **constraints) -> int:
        return await self.run_in_executor(q.get_txo_sum, **constraints)

    async def get_txo_plot(self, **constraints) -> List[dict]:
        return await self.run_in_executor(q.get_txo_plot, **constraints)

    async def get_txos(self, **constraints) -> Result[Output]:
        txos = await self.fetch_result(q.get_txos, **constraints)
        if 'wallet' in constraints:
            await add_channel_keys_to_txo_results(constraints['wallet'].accounts, txos)
        return txos

    async def get_utxos(self, **constraints) -> Result[Output]:
        return await self.get_txos(is_spent=False, **constraints)

    async def get_supports(self, **constraints) -> Result[Output]:
        return await self.get_utxos(txo_type=TXO_TYPES['support'], **constraints)

    async def get_claims(self, **constraints) -> Result[Output]:
        if 'txo_type' not in constraints:
            constraints['txo_type__in'] = CLAIM_TYPE_CODES
        txos = await self.fetch_result(q.get_txos, **constraints)
        if 'wallet' in constraints:
            await add_channel_keys_to_txo_results(constraints['wallet'].accounts, txos)
        return txos

    async def get_streams(self, **constraints) -> Result[Output]:
        return await self.get_claims(txo_type=TXO_TYPES['stream'], **constraints)

    async def get_channels(self, **constraints) -> Result[Output]:
        return await self.get_claims(txo_type=TXO_TYPES['channel'], **constraints)

    async def get_collections(self, **constraints) -> Result[Output]:
        return await self.get_claims(txo_type=TXO_TYPES['collection'], **constraints)
