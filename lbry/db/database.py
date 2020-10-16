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
from .query_context import initialize, uninitialize, ProgressPublisher
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
        self.workers = self._normalize_worker_processes(ledger.conf.workers)
        self.executor: Optional[Executor] = None
        self.message_queue = mp.Queue()
        self.stop_event = mp.Event()
        self._on_progress_controller = EventController()
        self.on_progress = self._on_progress_controller.stream
        self.progress_publisher = ProgressPublisher(
            self.message_queue, self._on_progress_controller
        )

    @staticmethod
    def _normalize_worker_processes(workers):
        if workers == 0:
            return os.cpu_count()
        elif workers > 0:
            return workers
        return 1

    @classmethod
    def temp_from_url_regtest(cls, db_url, lbrycrd_dir=None):
        from lbry import Config, RegTestLedger  # pylint: disable=import-outside-toplevel
        directory = tempfile.mkdtemp()
        conf = Config.with_same_dir(directory).set(db_url=db_url)
        if lbrycrd_dir is not None:
            conf.lbrycrd_dir = lbrycrd_dir
        ledger = RegTestLedger(conf)
        return cls(ledger)

    @classmethod
    def temp_sqlite_regtest(cls, lbrycrd_dir=None):
        from lbry import Config, RegTestLedger  # pylint: disable=import-outside-toplevel
        directory = tempfile.mkdtemp()
        conf = Config.with_same_dir(directory).set(blockchain="regtest")
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
    def from_url(cls, db_url):
        from lbry import Config, Ledger  # pylint: disable=import-outside-toplevel
        return cls(Ledger(Config.with_null_dir().set(db_url=db_url)))

    @classmethod
    def in_memory(cls):
        return cls.from_url('sqlite:///:memory:')

    def sync_create(self, name):
        engine = create_engine(self.url)
        db = engine.connect()
        db.execute(text("COMMIT"))
        db.execute(text(f"CREATE DATABASE {name}"))

    async def create(self, name):
        return await asyncio.get_running_loop().run_in_executor(None, self.sync_create, name)

    def sync_drop(self, name):
        engine = create_engine(self.url)
        db = engine.connect()
        db.execute(text("COMMIT"))
        db.execute(text(f"DROP DATABASE IF EXISTS {name}"))

    async def drop(self, name):
        return await asyncio.get_running_loop().run_in_executor(None, self.sync_drop, name)

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
        if self.workers > 1:
            self.executor = ProcessPoolExecutor(max_workers=self.workers, **kwargs)
        else:
            self.executor = ThreadPoolExecutor(max_workers=1, **kwargs)
        return await self.run(q.check_version_and_create_tables)

    async def close(self):
        self.progress_publisher.stop()
        if self.executor is not None:
            if isinstance(self.executor, ThreadPoolExecutor):
                await self.run(uninitialize)
            self.executor.shutdown()
            self.executor = None
            # fixes "OSError: handle is closed"
            # seems to only happen when running in PyCharm
            # https://github.com/python/cpython/pull/6084#issuecomment-564585446
            # TODO: delete this in Python 3.8/3.9?
            from concurrent.futures.process import _threads_wakeups  # pylint: disable=import-outside-toplevel
            _threads_wakeups.clear()

    async def run(self, func, *args, **kwargs):
        if kwargs:
            clean_wallet_account_ids(kwargs)
        return await asyncio.get_running_loop().run_in_executor(
            self.executor, partial(func, *args, **kwargs)
        )

    async def fetch_result(self, func, *args, **kwargs) -> Result:
        rows, total = await self.run(func, *args, **kwargs)
        return Result(rows, total)

    async def execute(self, sql):
        return await self.run(q.execute, sql)

    async def execute_fetchall(self, sql):
        return await self.run(q.execute_fetchall, sql)

    async def has_filters(self):
        return await self.run(q.has_filters)

    async def has_claims(self):
        return await self.run(q.has_claims)

    async def has_supports(self):
        return await self.run(q.has_supports)

    async def get_best_block_height(self) -> int:
        return await self.run(q.get_best_block_height)

    async def process_all_things_after_sync(self):
        return await self.run(sync.process_all_things_after_sync)

    async def insert_block(self, block):
        return await self.run(q.insert_block, block)

    async def insert_transaction(self, block_hash, tx):
        return await self.run(q.insert_transaction, block_hash, tx)

    async def update_address_used_times(self, addresses):
        return await self.run(q.update_address_used_times, addresses)

    async def reserve_outputs(self, txos, is_reserved=True):
        txo_hashes = [txo.hash for txo in txos]
        if txo_hashes:
            return await self.run(
                q.reserve_outputs, txo_hashes, is_reserved
            )

    async def release_outputs(self, txos):
        return await self.reserve_outputs(txos, is_reserved=False)

    async def release_tx(self, tx):
        return await self.release_outputs([txi.txo_ref.txo for txi in tx.inputs])

    async def release_all_outputs(self, account):
        return await self.run(q.release_all_outputs, account.id)

    async def get_balance(self, **constraints):
        return await self.run(q.get_balance, **constraints)

    async def get_report(self, accounts):
        return await self.run(q.get_report, accounts=accounts)

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
        return await self.run(q.get_all_addresses)

    async def get_address(self, **constraints):
        for address in await self.get_addresses(limit=1, **constraints):
            return address

    async def add_keys(self, account, chain, pubkeys):
        return await self.run(q.add_keys, account, chain, pubkeys)

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
        claims, total, censor = await self.run(q.search_claims, **constraints)
        return Result(claims, total, censor)

    async def protobuf_search_claims(self, **constraints) -> str:
        return await self.run(q.protobuf_search_claims, **constraints)

    async def search_supports(self, **constraints) -> Result[Output]:
        return await self.fetch_result(q.search_supports, **constraints)

    async def sum_supports(self, claim_hash, include_channel_content=False, exclude_own_supports=False) -> List[Dict]:
        return await self.run(q.sum_supports, claim_hash, include_channel_content, exclude_own_supports)

    async def resolve(self, urls, **kwargs) -> Dict[str, Output]:
        return await self.run(q.resolve, urls, **kwargs)

    async def protobuf_resolve(self, urls, **kwargs) -> str:
        return await self.run(q.protobuf_resolve, urls, **kwargs)

    async def get_txo_sum(self, **constraints) -> int:
        return await self.run(q.get_txo_sum, **constraints)

    async def get_txo_plot(self, **constraints) -> List[dict]:
        return await self.run(q.get_txo_plot, **constraints)

    async def get_txos(self, **constraints) -> Result[Output]:
        txos = await self.fetch_result(q.get_txos, **constraints)
        if 'wallet' in constraints:
            await add_channel_keys_to_txo_results(constraints['wallet'].accounts, txos)
        return txos

    async def get_utxos(self, **constraints) -> Result[Output]:
        return await self.get_txos(spent_height=0, **constraints)

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
