import os
import asyncio
from typing import List, Optional, Tuple, Iterable
from concurrent.futures import Executor, ThreadPoolExecutor, ProcessPoolExecutor
from functools import partial

from sqlalchemy import create_engine, text

from lbry.crypto.bip32 import PubKey
from lbry.blockchain.ledger import Ledger
from lbry.blockchain.transaction import Transaction, Output
from .constants import TXO_TYPES, CLAIM_TYPE_CODES
from . import queries as q


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


def add_channel_keys_to_txo_results(accounts: List, txos: Iterable[Output]):
    sub_channels = set()
    for txo in txos:
        if txo.claim.is_channel:
            for account in accounts:
                private_key = account.get_channel_private_key(
                    txo.claim.channel.public_key_bytes
                )
                if private_key:
                    txo.private_key = private_key
                    break
        if txo.channel is not None:
            sub_channels.add(txo.channel)
    if sub_channels:
        add_channel_keys_to_txo_results(accounts, sub_channels)


class Database:

    def __init__(self, ledger: Ledger, url: str, multiprocess=False):
        self.url = url
        self.ledger = ledger
        self.multiprocess = multiprocess
        self.executor: Optional[Executor] = None

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
        kwargs = dict(
            initializer=q.initialize,
            initargs=(self.url, self.ledger)
        )
        if self.multiprocess:
            self.executor = ProcessPoolExecutor(
                max_workers=max(os.cpu_count()-1, 4), **kwargs
            )
        else:
            self.executor = ThreadPoolExecutor(
                max_workers=1, **kwargs
            )
        return await self.run_in_executor(q.check_version_and_create_tables)

    async def close(self):
        if self.executor is not None:
            self.executor.shutdown()
            self.executor = None

    async def run_in_executor(self, func, *args, **kwargs):
        if kwargs:
            clean_wallet_account_ids(kwargs)
        return await asyncio.get_event_loop().run_in_executor(
            self.executor, partial(func, *args, **kwargs)
        )

    async def execute_fetchall(self, sql):
        return await self.run_in_executor(q.execute_fetchall, sql)

    async def get_best_height(self):
        return await self.run_in_executor(q.get_best_height)

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

    async def insert_transaction(self, tx):
        return await self.run_in_executor(q.insert_transaction, tx)

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

    async def get_supports_summary(self, **constraints):
        return await self.run_in_executor(self.get_supports_summary, **constraints)

    async def get_addresses(self, **constraints) -> Tuple[List[dict], Optional[int]]:
        addresses, count = await self.run_in_executor(q.get_addresses, **constraints)
        if addresses and 'pubkey' in addresses[0]:
            for address in addresses:
                address['pubkey'] = PubKey(
                    self.ledger, bytes(address.pop('pubkey')), bytes(address.pop('chain_code')),
                    address.pop('n'), address.pop('depth')
                )
        return addresses, count

    async def get_all_addresses(self):
        return await self.run_in_executor(q.get_all_addresses)

    async def get_address(self, **constraints):
        addresses, _ = await self.get_addresses(limit=1, **constraints)
        if addresses:
            return addresses[0]

    async def add_keys(self, account, chain, pubkeys):
        return await self.run_in_executor(q.add_keys, account, chain, pubkeys)

    async def get_raw_transactions(self, tx_hashes):
        return await self.run_in_executor(q.get_raw_transactions, tx_hashes)

    async def get_transactions(self, **constraints) -> Tuple[List[Transaction], Optional[int]]:
        return await self.run_in_executor(q.get_transactions, **constraints)

    async def get_transaction(self, **constraints) -> Optional[Transaction]:
        txs, _ = await self.get_transactions(limit=1, **constraints)
        if txs:
            return txs[0]

    async def get_purchases(self, **constraints) -> Tuple[List[Output], Optional[int]]:
        return await self.run_in_executor(q.get_purchases, **constraints)

    async def search_claims(self, **constraints):
        return await self.run_in_executor(q.search, **constraints)

    async def get_txo_sum(self, **constraints):
        return await self.run_in_executor(q.get_txo_sum, **constraints)

    async def get_txo_plot(self, **constraints):
        return await self.run_in_executor(q.get_txo_plot, **constraints)

    async def get_txos(self, **constraints) -> Tuple[List[Output], Optional[int]]:
        txos = await self.run_in_executor(q.get_txos, **constraints)
        if 'wallet' in constraints:
            add_channel_keys_to_txo_results(constraints['wallet'], txos)
        return txos

    async def get_utxos(self, **constraints) -> Tuple[List[Output], Optional[int]]:
        return await self.get_txos(is_spent=False, **constraints)

    async def get_supports(self, **constraints) -> Tuple[List[Output], Optional[int]]:
        return await self.get_utxos(txo_type=TXO_TYPES['support'], **constraints)

    async def get_claims(self, **constraints) -> Tuple[List[Output], Optional[int]]:
        txos, count = await self.run_in_executor(q.get_claims, **constraints)
        if 'wallet' in constraints:
            add_channel_keys_to_txo_results(constraints['wallet'].accounts, txos)
        return txos, count

    async def get_streams(self, **constraints) -> Tuple[List[Output], Optional[int]]:
        return await self.get_claims(txo_type=TXO_TYPES['stream'], **constraints)

    async def get_channels(self, **constraints) -> Tuple[List[Output], Optional[int]]:
        return await self.get_claims(txo_type=TXO_TYPES['channel'], **constraints)

    async def get_collections(self, **constraints) -> Tuple[List[Output], Optional[int]]:
        return await self.get_claims(txo_type=TXO_TYPES['collection'], **constraints)
