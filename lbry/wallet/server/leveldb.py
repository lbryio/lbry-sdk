# Copyright (c) 2016, Neil Booth
# Copyright (c) 2017, the ElectrumX authors
#
# All rights reserved.
#
# See the file "LICENCE" for information about the copyright
# and warranty status of this software.

"""Interface to the blockchain database."""


import asyncio
import array
import ast
import os
import time
import zlib
import typing
from typing import Optional, List, Tuple, Iterable
from asyncio import sleep
from bisect import bisect_right
from collections import namedtuple
from glob import glob
from struct import pack, unpack
from concurrent.futures.thread import ThreadPoolExecutor
import attr
from lbry.utils import LRUCacheWithMetrics
from lbry.wallet.server import util
from lbry.wallet.server.hash import hash_to_hex_str, HASHX_LEN
from lbry.wallet.server.merkle import Merkle, MerkleCache
from lbry.wallet.server.util import formatted_time
from lbry.wallet.server.storage import db_class
from lbry.wallet.server.history import History


UTXO = namedtuple("UTXO", "tx_num tx_pos tx_hash height value")
HEADER_PREFIX = b'H'
TX_COUNT_PREFIX = b'T'
TX_HASH_PREFIX = b'X'
TX_PREFIX = b'B'
TX_NUM_PREFIX = b'N'
BLOCK_HASH_PREFIX = b'C'



@attr.s(slots=True)
class FlushData:
    height = attr.ib()
    tx_count = attr.ib()
    headers = attr.ib()
    block_hashes = attr.ib()
    block_txs = attr.ib()
    # The following are flushed to the UTXO DB if undo_infos is not None
    undo_infos = attr.ib()
    adds = attr.ib()
    deletes = attr.ib()
    tip = attr.ib()


class LevelDB:
    """Simple wrapper of the backend database for querying.

    Performs no DB update, though the DB will be cleaned on opening if
    it was shutdown uncleanly.
    """

    DB_VERSIONS = [6]

    class DBError(Exception):
        """Raised on general DB errors generally indicating corruption."""

    def __init__(self, env):
        self.logger = util.class_logger(__name__, self.__class__.__name__)
        self.env = env
        self.coin = env.coin
        self.executor = None

        self.logger.info(f'switching current directory to {env.db_dir}')

        self.db_class = db_class(env.db_dir, self.env.db_engine)
        self.history = History()
        self.utxo_db = None
        self.tx_counts = None
        self.headers = None
        self.last_flush = time.time()

        self.logger.info(f'using {self.env.db_engine} for DB backend')

        # Header merkle cache
        self.merkle = Merkle()
        self.header_mc = MerkleCache(self.merkle, self.fs_block_hashes)

        self.headers_db = None
        self.tx_db = None

        self._tx_and_merkle_cache = LRUCacheWithMetrics(2 ** 17, metric_name='tx_and_merkle', namespace="wallet_server")
        self.total_transactions = None

    async def _read_tx_counts(self):
        if self.tx_counts is not None:
            return
        # tx_counts[N] has the cumulative number of txs at the end of
        # height N.  So tx_counts[0] is 1 - the genesis coinbase

        def get_counts():
            return tuple(
                util.unpack_be_uint64(tx_count)
                for tx_count in self.tx_db.iterator(prefix=TX_COUNT_PREFIX, include_key=False)
            )

        tx_counts = await asyncio.get_event_loop().run_in_executor(self.executor, get_counts)
        assert len(tx_counts) == self.db_height + 1, f"{len(tx_counts)} vs {self.db_height + 1}"
        self.tx_counts = array.array('I', tx_counts)

        if self.tx_counts:
            assert self.db_tx_count == self.tx_counts[-1], \
                f"{self.db_tx_count} vs {self.tx_counts[-1]} ({len(self.tx_counts)} counts)"
        else:
            assert self.db_tx_count == 0

    async def _read_txids(self):
        def get_txids():
            return list(self.tx_db.iterator(prefix=TX_HASH_PREFIX, include_key=False))

        start = time.perf_counter()
        self.logger.info("loading txids")
        txids = await asyncio.get_event_loop().run_in_executor(self.executor, get_txids)
        assert len(txids) == len(self.tx_counts) == 0 or len(txids) == self.tx_counts[-1]
        self.total_transactions = txids
        ts = time.perf_counter() - start
        self.logger.info("loaded %i txids in %ss", len(self.total_transactions), round(ts, 4))

    async def _read_headers(self):
        if self.headers is not None:
            return

        def get_headers():
            return [
                header for header in self.headers_db.iterator(prefix=HEADER_PREFIX, include_key=False)
            ]

        headers = await asyncio.get_event_loop().run_in_executor(self.executor, get_headers)
        assert len(headers) - 1 == self.db_height, f"{len(headers)} vs {self.db_height}"
        self.headers = headers

    async def _open_dbs(self, for_sync, compacting):
        if self.executor is None:
            self.executor = ThreadPoolExecutor(1)
        coin_path = os.path.join(self.env.db_dir, 'COIN')
        if not os.path.isfile(coin_path):
            with util.open_file(coin_path, create=True) as f:
                f.write(f'ElectrumX databases and metadata for '
                        f'{self.coin.NAME} {self.coin.NET}'.encode())

        assert self.headers_db is None
        self.headers_db = self.db_class('headers', for_sync)
        if self.headers_db.is_new:
            self.logger.info('created new headers db')
        self.logger.info(f'opened headers DB (for sync: {for_sync})')

        assert self.tx_db is None
        self.tx_db = self.db_class('tx', for_sync)
        if self.tx_db.is_new:
            self.logger.info('created new tx db')
        self.logger.info(f'opened tx DB (for sync: {for_sync})')

        assert self.utxo_db is None
        # First UTXO DB
        self.utxo_db = self.db_class('utxo', for_sync)
        if self.utxo_db.is_new:
            self.logger.info('created new utxo db')
        self.logger.info(f'opened utxo db (for sync: {for_sync})')
        self.read_utxo_state()

        # Then history DB
        self.utxo_flush_count = self.history.open_db(
            self.db_class, for_sync, self.utxo_flush_count, compacting
        )
        self.clear_excess_undo_info()

        # Read TX counts (requires meta directory)
        await self._read_tx_counts()
        if self.total_transactions is None:
            await self._read_txids()
        await self._read_headers()

    def close(self):
        self.utxo_db.close()
        self.history.close_db()
        self.headers_db.close()
        self.tx_db.close()
        self.executor.shutdown(wait=True)
        self.executor = None

    async def open_for_compacting(self):
        await self._open_dbs(True, True)

    async def open_for_sync(self):
        """Open the databases to sync to the daemon.

        When syncing we want to reserve a lot of open files for the
        synchronization.  When serving clients we want the open files for
        serving network connections.
        """
        self.logger.info("opened for sync")
        await self._open_dbs(True, False)

    async def open_for_serving(self):
        """Open the databases for serving.  If they are already open they are
        closed first.
        """
        self.logger.info('closing DBs to re-open for serving')
        if self.utxo_db:
            self.logger.info('closing DBs to re-open for serving')
            self.utxo_db.close()
            self.history.close_db()
            self.utxo_db = None
        if self.headers_db:
            self.headers_db.close()
            self.headers_db = None
        if self.tx_db:
            self.tx_db.close()
            self.tx_db = None

        await self._open_dbs(False, False)
        self.logger.info("opened for serving")

    # Header merkle cache

    async def populate_header_merkle_cache(self):
        self.logger.info('populating header merkle cache...')
        length = max(1, self.db_height - self.env.reorg_limit)
        start = time.time()
        await self.header_mc.initialize(length)
        elapsed = time.time() - start
        self.logger.info(f'header merkle cache populated in {elapsed:.1f}s')

    async def header_branch_and_root(self, length, height):
        return await self.header_mc.branch_and_root(length, height)

    # Flushing
    def assert_flushed(self, flush_data):
        """Asserts state is fully flushed."""
        assert flush_data.tx_count == self.fs_tx_count == self.db_tx_count
        assert flush_data.height == self.fs_height == self.db_height
        assert flush_data.tip == self.db_tip
        assert not flush_data.headers
        assert not flush_data.block_txs
        assert not flush_data.adds
        assert not flush_data.deletes
        assert not flush_data.undo_infos
        self.history.assert_flushed()

    def flush_dbs(self, flush_data, flush_utxos, estimate_txs_remaining):
        """Flush out cached state.  History is always flushed; UTXOs are
        flushed if flush_utxos."""
        if flush_data.height == self.db_height:
            self.assert_flushed(flush_data)
            return

        start_time = time.time()
        prior_flush = self.last_flush
        tx_delta = flush_data.tx_count - self.last_flush_tx_count

        # Flush to file system
        self.flush_fs(flush_data)

        # Then history
        self.flush_history()

        # Flush state last as it reads the wall time.
        with self.utxo_db.write_batch() as batch:
            if flush_utxos:
                self.flush_utxo_db(batch, flush_data)
            self.flush_state(batch)

        # Update and put the wall time again - otherwise we drop the
        # time it took to commit the batch
        self.flush_state(self.utxo_db)

        elapsed = self.last_flush - start_time
        self.logger.info(f'flush #{self.history.flush_count:,d} took '
                         f'{elapsed:.1f}s.  Height {flush_data.height:,d} '
                         f'txs: {flush_data.tx_count:,d} ({tx_delta:+,d})')

        # Catch-up stats
        if self.utxo_db.for_sync:
            flush_interval = self.last_flush - prior_flush
            tx_per_sec_gen = int(flush_data.tx_count / self.wall_time)
            tx_per_sec_last = 1 + int(tx_delta / flush_interval)
            eta = estimate_txs_remaining() / tx_per_sec_last
            self.logger.info(f'tx/sec since genesis: {tx_per_sec_gen:,d}, '
                             f'since last flush: {tx_per_sec_last:,d}')
            self.logger.info(f'sync time: {formatted_time(self.wall_time)}  '
                             f'ETA: {formatted_time(eta)}')

    def flush_fs(self, flush_data):
        """Write headers, tx counts and block tx hashes to the filesystem.

        The first height to write is self.fs_height + 1.  The FS
        metadata is all append-only, so in a crash we just pick up
        again from the height stored in the DB.
        """
        prior_tx_count = (self.tx_counts[self.fs_height]
                          if self.fs_height >= 0 else 0)
        assert len(flush_data.block_txs) == len(flush_data.headers)
        assert flush_data.height == self.fs_height + len(flush_data.headers)
        assert flush_data.tx_count == (self.tx_counts[-1] if self.tx_counts
                                       else 0)
        assert len(self.tx_counts) == flush_data.height + 1
        assert len(
            b''.join(hashes for hashes, _ in flush_data.block_txs)
        ) // 32 == flush_data.tx_count - prior_tx_count

        # Write the headers
        start_time = time.perf_counter()

        with self.headers_db.write_batch() as batch:
            batch_put = batch.put
            for i, header in enumerate(flush_data.headers):
                batch_put(HEADER_PREFIX + util.pack_be_uint64(self.fs_height + i + 1), header)
                self.headers.append(header)
        flush_data.headers.clear()

        height_start = self.fs_height + 1
        tx_num = prior_tx_count

        with self.tx_db.write_batch() as batch:
            batch_put = batch.put
            for block_hash, (tx_hashes, txs) in zip(flush_data.block_hashes, flush_data.block_txs):
                tx_count = self.tx_counts[height_start]
                batch_put(BLOCK_HASH_PREFIX + util.pack_be_uint64(height_start), block_hash[::-1])
                batch_put(TX_COUNT_PREFIX + util.pack_be_uint64(height_start), util.pack_be_uint64(tx_count))
                height_start += 1
                offset = 0
                while offset < len(tx_hashes):
                    batch_put(TX_HASH_PREFIX + util.pack_be_uint64(tx_num), tx_hashes[offset:offset+32])
                    batch_put(TX_NUM_PREFIX + tx_hashes[offset:offset+32], util.pack_be_uint64(tx_num))
                    batch_put(TX_PREFIX + tx_hashes[offset:offset+32], txs[offset // 32])
                    tx_num += 1
                    offset += 32

        flush_data.block_txs.clear()
        flush_data.block_hashes.clear()

        self.fs_height = flush_data.height
        self.fs_tx_count = flush_data.tx_count
        elapsed = time.perf_counter() - start_time
        self.logger.info(f'flushed filesystem data in {elapsed:.2f}s')

    def flush_history(self):
        self.history.flush()

    def flush_utxo_db(self, batch, flush_data):
        """Flush the cached DB writes and UTXO set to the batch."""
        # Care is needed because the writes generated by flushing the
        # UTXO state may have keys in common with our write cache or
        # may be in the DB already.
        start_time = time.time()
        add_count = len(flush_data.adds)
        spend_count = len(flush_data.deletes) // 2

        # Spends
        batch_delete = batch.delete
        for key in sorted(flush_data.deletes):
            batch_delete(key)
        flush_data.deletes.clear()

        # New UTXOs
        batch_put = batch.put
        for key, value in flush_data.adds.items():
            # suffix = tx_idx + tx_num
            hashX = value[:-12]
            suffix = key[-2:] + value[-12:-8]
            batch_put(b'h' + key[:4] + suffix, hashX)
            batch_put(b'u' + hashX + suffix, value[-8:])
        flush_data.adds.clear()

        # New undo information
        self.flush_undo_infos(batch_put, flush_data.undo_infos)
        flush_data.undo_infos.clear()

        if self.utxo_db.for_sync:
            block_count = flush_data.height - self.db_height
            tx_count = flush_data.tx_count - self.db_tx_count
            elapsed = time.time() - start_time
            self.logger.info(f'flushed {block_count:,d} blocks with '
                             f'{tx_count:,d} txs, {add_count:,d} UTXO adds, '
                             f'{spend_count:,d} spends in '
                             f'{elapsed:.1f}s, committing...')

        self.utxo_flush_count = self.history.flush_count
        self.db_height = flush_data.height
        self.db_tx_count = flush_data.tx_count
        self.db_tip = flush_data.tip

    def flush_state(self, batch):
        """Flush chain state to the batch."""
        now = time.time()
        self.wall_time += now - self.last_flush
        self.last_flush = now
        self.last_flush_tx_count = self.fs_tx_count
        self.write_utxo_state(batch)

    def flush_backup(self, flush_data, touched):
        """Like flush_dbs() but when backing up.  All UTXOs are flushed."""
        assert not flush_data.headers
        assert not flush_data.block_txs
        assert flush_data.height < self.db_height
        self.history.assert_flushed()

        start_time = time.time()
        tx_delta = flush_data.tx_count - self.last_flush_tx_count

        self.backup_fs(flush_data.height, flush_data.tx_count)
        self.history.backup(touched, flush_data.tx_count)
        with self.utxo_db.write_batch() as batch:
            self.flush_utxo_db(batch, flush_data)
            # Flush state last as it reads the wall time.
            self.flush_state(batch)

        elapsed = self.last_flush - start_time
        self.logger.info(f'backup flush #{self.history.flush_count:,d} took '
                         f'{elapsed:.1f}s.  Height {flush_data.height:,d} '
                         f'txs: {flush_data.tx_count:,d} ({tx_delta:+,d})')

    def backup_fs(self, height, tx_count):
        """Back up during a reorg.  This just updates our pointers."""
        while self.fs_height > height:
            self.fs_height -= 1
            self.headers.pop()
        self.fs_tx_count = tx_count
        # Truncate header_mc: header count is 1 more than the height.
        self.header_mc.truncate(height + 1)

    def raw_header(self, height):
        """Return the binary header at the given height."""
        header, n = self.read_headers(height, 1)
        if n != 1:
            raise IndexError(f'height {height:,d} out of range')
        return header

    def read_headers(self, start_height, count) -> typing.Tuple[bytes, int]:
        """Requires start_height >= 0, count >= 0.  Reads as many headers as
        are available starting at start_height up to count.  This
        would be zero if start_height is beyond self.db_height, for
        example.

        Returns a (binary, n) pair where binary is the concatenated
        binary headers, and n is the count of headers returned.
        """

        if start_height < 0 or count < 0:
            raise self.DBError(f'{count:,d} headers starting at '
                               f'{start_height:,d} not on disk')

        disk_count = max(0, min(count, self.db_height + 1 - start_height))
        if disk_count:
            return b''.join(self.headers[start_height:start_height + disk_count]), disk_count
        return b'', 0

    def fs_tx_hash(self, tx_num):
        """Return a par (tx_hash, tx_height) for the given tx number.

        If the tx_height is not on disk, returns (None, tx_height)."""
        tx_height = bisect_right(self.tx_counts, tx_num)
        if tx_height > self.db_height:
            return None, tx_height
        return self.total_transactions[tx_num], tx_height

    def _fs_transactions(self, txids: Iterable[str]):
        unpack_be_uint64 = util.unpack_be_uint64
        tx_counts = self.tx_counts
        tx_db_get = self.tx_db.get
        tx_cache = self._tx_and_merkle_cache

        tx_infos = {}

        for tx_hash in txids:
            cached_tx = tx_cache.get(tx_hash)
            if cached_tx:
                tx, merkle = cached_tx
            else:
                tx_hash_bytes = bytes.fromhex(tx_hash)[::-1]
                tx_num = tx_db_get(TX_NUM_PREFIX + tx_hash_bytes)
                tx = None
                tx_height = -1
                if tx_num is not None:
                    tx_num = unpack_be_uint64(tx_num)
                    tx_height = bisect_right(tx_counts, tx_num)
                    if tx_height < self.db_height:
                        tx = tx_db_get(TX_PREFIX + tx_hash_bytes)
                if tx_height == -1:
                    merkle = {
                        'block_height': -1
                    }
                else:
                    tx_pos = tx_num - tx_counts[tx_height - 1]
                    branch, root = self.merkle.branch_and_root(
                        self.total_transactions[tx_counts[tx_height - 1]:tx_counts[tx_height]], tx_pos
                    )
                    merkle = {
                        'block_height': tx_height,
                        'merkle': [
                            hash_to_hex_str(hash)
                            for hash in branch
                        ],
                        'pos': tx_pos
                    }
                if tx_height + 10 < self.db_height:
                    tx_cache[tx_hash] = tx, merkle
            tx_infos[tx_hash] = (None if not tx else tx.hex(), merkle)
        return tx_infos

    async def fs_transactions(self, txids):
        return await asyncio.get_event_loop().run_in_executor(self.executor, self._fs_transactions, txids)

    async def fs_block_hashes(self, height, count):
        if height + count > len(self.headers):
            raise self.DBError(f'only got {len(self.headers) - height:,d} headers starting at {height:,d}, not {count:,d}')
        return [self.coin.header_hash(header) for header in self.headers[height:height + count]]

    async def limited_history(self, hashX, *, limit=1000):
        """Return an unpruned, sorted list of (tx_hash, height) tuples of
        confirmed transactions that touched the address, earliest in
        the blockchain first.  Includes both spending and receiving
        transactions.  By default returns at most 1000 entries.  Set
        limit to None to get them all.
        """

        def read_history():
            db_height = self.db_height
            tx_counts = self.tx_counts

            cnt = 0
            txs = []

            for hist in self.history.db.iterator(prefix=hashX, include_key=False):
                a = array.array('I')
                a.frombytes(hist)
                for tx_num in a:
                    tx_height = bisect_right(tx_counts, tx_num)
                    if tx_height > db_height:
                        return
                    txs.append((tx_num, tx_height))
                    cnt += 1
                    if limit and cnt >= limit:
                        break
                if limit and cnt >= limit:
                    break
            return txs

        while True:
            history = await asyncio.get_event_loop().run_in_executor(self.executor, read_history)
            if history is not None:
                return [(self.total_transactions[tx_num], tx_height) for (tx_num, tx_height) in history]
            self.logger.warning(f'limited_history: tx hash '
                                f'not found (reorg?), retrying...')
            await sleep(0.25)

    # -- Undo information

    def min_undo_height(self, max_height):
        """Returns a height from which we should store undo info."""
        return max_height - self.env.reorg_limit + 1

    def undo_key(self, height):
        """DB key for undo information at the given height."""
        return b'U' + pack('>I', height)

    def read_undo_info(self, height):
        """Read undo information from a file for the current height."""
        return self.utxo_db.get(self.undo_key(height))

    def flush_undo_infos(self, batch_put, undo_infos):
        """undo_infos is a list of (undo_info, height) pairs."""
        for undo_info, height in undo_infos:
            batch_put(self.undo_key(height), b''.join(undo_info))

    def raw_block_prefix(self):
        return 'block'

    def raw_block_path(self, height):
        return os.path.join(self.env.db_dir, f'{self.raw_block_prefix()}{height:d}')

    async def read_raw_block(self, height):
        """Returns a raw block read from disk.  Raises FileNotFoundError
        if the block isn't on-disk."""

        def read():
            with util.open_file(self.raw_block_path(height)) as f:
                return f.read(-1)

        return await asyncio.get_event_loop().run_in_executor(self.executor, read)

    def write_raw_block(self, block, height):
        """Write a raw block to disk."""
        with util.open_truncate(self.raw_block_path(height)) as f:
            f.write(block)
        # Delete old blocks to prevent them accumulating
        try:
            del_height = self.min_undo_height(height) - 1
            os.remove(self.raw_block_path(del_height))
        except FileNotFoundError:
            pass

    def clear_excess_undo_info(self):
        """Clear excess undo info.  Only most recent N are kept."""
        prefix = b'U'
        min_height = self.min_undo_height(self.db_height)
        keys = []
        for key, hist in self.utxo_db.iterator(prefix=prefix):
            height, = unpack('>I', key[-4:])
            if height >= min_height:
                break
            keys.append(key)

        if keys:
            with self.utxo_db.write_batch() as batch:
                for key in keys:
                    batch.delete(key)
            self.logger.info(f'deleted {len(keys):,d} stale undo entries')

        # delete old block files
        prefix = self.raw_block_prefix()
        paths = [path for path in glob(f'{prefix}[0-9]*')
                 if len(path) > len(prefix)
                 and int(path[len(prefix):]) < min_height]
        if paths:
            for path in paths:
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
            self.logger.info(f'deleted {len(paths):,d} stale block files')

    # -- UTXO database

    def read_utxo_state(self):
        state = self.utxo_db.get(b'state')
        if not state:
            self.db_height = -1
            self.db_tx_count = 0
            self.db_tip = b'\0' * 32
            self.db_version = max(self.DB_VERSIONS)
            self.utxo_flush_count = 0
            self.wall_time = 0
            self.first_sync = True
        else:
            state = ast.literal_eval(state.decode())
            if not isinstance(state, dict):
                raise self.DBError('failed reading state from DB')
            self.db_version = state['db_version']
            if self.db_version not in self.DB_VERSIONS:
                raise self.DBError(f'your UTXO DB version is {self.db_version} but this '
                                   f'software only handles versions {self.DB_VERSIONS}')
            # backwards compat
            genesis_hash = state['genesis']
            if isinstance(genesis_hash, bytes):
                genesis_hash = genesis_hash.decode()
            if genesis_hash != self.coin.GENESIS_HASH:
                raise self.DBError(f'DB genesis hash {genesis_hash} does not '
                                   f'match coin {self.coin.GENESIS_HASH}')
            self.db_height = state['height']
            self.db_tx_count = state['tx_count']
            self.db_tip = state['tip']
            self.utxo_flush_count = state['utxo_flush_count']
            self.wall_time = state['wall_time']
            self.first_sync = state['first_sync']

        # These are our state as we move ahead of DB state
        self.fs_height = self.db_height
        self.fs_tx_count = self.db_tx_count
        self.last_flush_tx_count = self.fs_tx_count

        # Log some stats
        self.logger.info(f'DB version: {self.db_version:d}')
        self.logger.info(f'coin: {self.coin.NAME}')
        self.logger.info(f'network: {self.coin.NET}')
        self.logger.info(f'height: {self.db_height:,d}')
        self.logger.info(f'tip: {hash_to_hex_str(self.db_tip)}')
        self.logger.info(f'tx count: {self.db_tx_count:,d}')
        if self.utxo_db.for_sync:
            self.logger.info(f'flushing DB cache at {self.env.cache_MB:,d} MB')
        if self.first_sync:
            self.logger.info(f'sync time so far: {util.formatted_time(self.wall_time)}')

    def write_utxo_state(self, batch):
        """Write (UTXO) state to the batch."""
        state = {
            'genesis': self.coin.GENESIS_HASH,
            'height': self.db_height,
            'tx_count': self.db_tx_count,
            'tip': self.db_tip,
            'utxo_flush_count': self.utxo_flush_count,
            'wall_time': self.wall_time,
            'first_sync': self.first_sync,
            'db_version': self.db_version,
        }
        batch.put(b'state', repr(state).encode())

    def set_flush_count(self, count):
        self.utxo_flush_count = count
        with self.utxo_db.write_batch() as batch:
            self.write_utxo_state(batch)

    async def all_utxos(self, hashX):
        """Return all UTXOs for an address sorted in no particular order."""
        def read_utxos():
            utxos = []
            utxos_append = utxos.append
            s_unpack = unpack
            fs_tx_hash = self.fs_tx_hash
            # Key: b'u' + address_hashX + tx_idx + tx_num
            # Value: the UTXO value as a 64-bit unsigned integer
            prefix = b'u' + hashX
            for db_key, db_value in self.utxo_db.iterator(prefix=prefix):
                tx_pos, tx_num = s_unpack('<HI', db_key[-6:])
                value, = unpack('<Q', db_value)
                tx_hash, height = fs_tx_hash(tx_num)
                utxos_append(UTXO(tx_num, tx_pos, tx_hash, height, value))
            return utxos

        while True:
            utxos = await asyncio.get_event_loop().run_in_executor(self.executor, read_utxos)
            if all(utxo.tx_hash is not None for utxo in utxos):
                return utxos
            self.logger.warning(f'all_utxos: tx hash not '
                                f'found (reorg?), retrying...')
            await sleep(0.25)

    async def lookup_utxos(self, prevouts):
        """For each prevout, lookup it up in the DB and return a (hashX,
        value) pair or None if not found.

        Used by the mempool code.
        """
        def lookup_hashXs():
            """Return (hashX, suffix) pairs, or None if not found,
            for each prevout.
            """
            def lookup_hashX(tx_hash, tx_idx):
                idx_packed = pack('<H', tx_idx)

                # Key: b'h' + compressed_tx_hash + tx_idx + tx_num
                # Value: hashX
                prefix = b'h' + tx_hash[:4] + idx_packed

                # Find which entry, if any, the TX_HASH matches.
                for db_key, hashX in self.utxo_db.iterator(prefix=prefix):
                    tx_num_packed = db_key[-4:]
                    tx_num, = unpack('<I', tx_num_packed)
                    hash, height = self.fs_tx_hash(tx_num)
                    if hash == tx_hash:
                        return hashX, idx_packed + tx_num_packed
                return None, None
            return [lookup_hashX(*prevout) for prevout in prevouts]

        def lookup_utxos(hashX_pairs):
            def lookup_utxo(hashX, suffix):
                if not hashX:
                    # This can happen when the daemon is a block ahead
                    # of us and has mempool txs spending outputs from
                    # that new block
                    return None
                # Key: b'u' + address_hashX + tx_idx + tx_num
                # Value: the UTXO value as a 64-bit unsigned integer
                key = b'u' + hashX + suffix
                db_value = self.utxo_db.get(key)
                if not db_value:
                    # This can happen if the DB was updated between
                    # getting the hashXs and getting the UTXOs
                    return None
                value, = unpack('<Q', db_value)
                return hashX, value
            return [lookup_utxo(*hashX_pair) for hashX_pair in hashX_pairs]

        hashX_pairs = await asyncio.get_event_loop().run_in_executor(self.executor, lookup_hashXs)
        return await asyncio.get_event_loop().run_in_executor(self.executor, lookup_utxos, hashX_pairs)
