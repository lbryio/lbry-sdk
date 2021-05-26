import time
import asyncio
import typing
from bisect import bisect_right
from struct import pack, unpack
from concurrent.futures.thread import ThreadPoolExecutor
from typing import Optional, List, Tuple, Set, DefaultDict, Dict
from prometheus_client import Gauge, Histogram
from collections import defaultdict
import lbry
from lbry.schema.claim import Claim
from lbry.wallet.transaction import OutputScript, Output
from lbry.wallet.server.tx import Tx, TxOutput, TxInput
from lbry.wallet.server.daemon import DaemonError
from lbry.wallet.server.hash import hash_to_hex_str, HASHX_LEN
from lbry.wallet.server.util import chunks, class_logger
from lbry.crypto.hash import hash160
from lbry.wallet.server.leveldb import FlushData
from lbry.wallet.server.db import DB_PREFIXES
from lbry.wallet.server.db.claimtrie import StagedClaimtrieItem, StagedClaimtrieSupport
from lbry.wallet.server.db.claimtrie import get_takeover_name_ops, StagedActivation
from lbry.wallet.server.db.claimtrie import get_remove_name_ops
from lbry.wallet.server.db.prefixes import ACTIVATED_SUPPORT_TXO_TYPE, ACTIVATED_CLAIM_TXO_TYPE
from lbry.wallet.server.db.prefixes import PendingActivationKey, PendingActivationValue
from lbry.wallet.server.udp import StatusServer
if typing.TYPE_CHECKING:
    from lbry.wallet.server.leveldb import LevelDB
    from lbry.wallet.server.db.revertable import RevertableOp


class Prefetcher:
    """Prefetches blocks (in the forward direction only)."""

    def __init__(self, daemon, coin, blocks_event):
        self.logger = class_logger(__name__, self.__class__.__name__)
        self.daemon = daemon
        self.coin = coin
        self.blocks_event = blocks_event
        self.blocks = []
        self.caught_up = False
        # Access to fetched_height should be protected by the semaphore
        self.fetched_height = None
        self.semaphore = asyncio.Semaphore()
        self.refill_event = asyncio.Event()
        # The prefetched block cache size.  The min cache size has
        # little effect on sync time.
        self.cache_size = 0
        self.min_cache_size = 10 * 1024 * 1024
        # This makes the first fetch be 10 blocks
        self.ave_size = self.min_cache_size // 10
        self.polling_delay = 5

    async def main_loop(self, bp_height):
        """Loop forever polling for more blocks."""
        await self.reset_height(bp_height)
        while True:
            try:
                # Sleep a while if there is nothing to prefetch
                await self.refill_event.wait()
                if not await self._prefetch_blocks():
                    await asyncio.sleep(self.polling_delay)
            except DaemonError as e:
                self.logger.info(f'ignoring daemon error: {e}')

    def get_prefetched_blocks(self):
        """Called by block processor when it is processing queued blocks."""
        blocks = self.blocks
        self.blocks = []
        self.cache_size = 0
        self.refill_event.set()
        return blocks

    async def reset_height(self, height):
        """Reset to prefetch blocks from the block processor's height.

        Used in blockchain reorganisations.  This coroutine can be
        called asynchronously to the _prefetch_blocks coroutine so we
        must synchronize with a semaphore.
        """
        async with self.semaphore:
            self.blocks.clear()
            self.cache_size = 0
            self.fetched_height = height
            self.refill_event.set()

        daemon_height = await self.daemon.height()
        behind = daemon_height - height
        if behind > 0:
            self.logger.info(f'catching up to daemon height {daemon_height:,d} '
                             f'({behind:,d} blocks behind)')
        else:
            self.logger.info(f'caught up to daemon height {daemon_height:,d}')

    async def _prefetch_blocks(self):
        """Prefetch some blocks and put them on the queue.

        Repeats until the queue is full or caught up.
        """
        daemon = self.daemon
        daemon_height = await daemon.height()
        async with self.semaphore:
            while self.cache_size < self.min_cache_size:
                # Try and catch up all blocks but limit to room in cache.
                # Constrain fetch count to between 0 and 500 regardless;
                # testnet can be lumpy.
                cache_room = self.min_cache_size // self.ave_size
                count = min(daemon_height - self.fetched_height, cache_room)
                count = min(500, max(count, 0))
                if not count:
                    self.caught_up = True
                    return False

                first = self.fetched_height + 1
                hex_hashes = await daemon.block_hex_hashes(first, count)
                if self.caught_up:
                    self.logger.info('new block height {:,d} hash {}'
                                     .format(first + count-1, hex_hashes[-1]))
                blocks = await daemon.raw_blocks(hex_hashes)

                assert count == len(blocks)

                # Special handling for genesis block
                if first == 0:
                    blocks[0] = self.coin.genesis_block(blocks[0])
                    self.logger.info(f'verified genesis block with hash {hex_hashes[0]}')

                # Update our recent average block size estimate
                size = sum(len(block) for block in blocks)
                if count >= 10:
                    self.ave_size = size // count
                else:
                    self.ave_size = (size + (10 - count) * self.ave_size) // 10

                self.blocks.extend(blocks)
                self.cache_size += size
                self.fetched_height += count
                self.blocks_event.set()

        self.refill_event.clear()
        return True


class ChainError(Exception):
    """Raised on error processing blocks."""


NAMESPACE = "wallet_server"
HISTOGRAM_BUCKETS = (
    .005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0, 60.0, float('inf')
)


class BlockProcessor:
    """Process blocks and update the DB state to match.

    Employ a prefetcher to prefetch blocks in batches for processing.
    Coordinate backing up in case of chain reorganisations.
    """

    block_count_metric = Gauge(
        "block_count", "Number of processed blocks", namespace=NAMESPACE
    )
    block_update_time_metric = Histogram(
        "block_time", "Block update times", namespace=NAMESPACE, buckets=HISTOGRAM_BUCKETS
    )
    reorg_count_metric = Gauge(
        "reorg_count", "Number of reorgs", namespace=NAMESPACE
    )

    def __init__(self, env, db: 'LevelDB', daemon, notifications):
        self.env = env
        self.db = db
        self.daemon = daemon
        self.notifications = notifications

        self.coin = env.coin
        self.blocks_event = asyncio.Event()
        self.prefetcher = Prefetcher(daemon, env.coin, self.blocks_event)
        self.logger = class_logger(__name__, self.__class__.__name__)
        self.executor = ThreadPoolExecutor(1)

        # Meta
        self.next_cache_check = 0
        self.touched = set()
        self.reorg_count = 0

        # Caches of unflushed items.
        self.headers = []
        self.block_hashes = []
        self.block_txs = []
        self.undo_infos = []

        # UTXO cache
        self.utxo_cache = {}
        self.db_deletes = []

        # Claimtrie cache
        self.claimtrie_stash = []
        self.undo_claims = []

        # If the lock is successfully acquired, in-memory chain state
        # is consistent with self.height
        self.state_lock = asyncio.Lock()

        self.search_cache = {}
        self.history_cache = {}
        self.status_server = StatusServer()

        #################################
        # attributes used for calculating stake activations and takeovers per block
        #################################

        # txo to pending claim
        self.pending_claims: typing.Dict[Tuple[int, int], StagedClaimtrieItem] = {}
        # claim hash to pending claim txo
        self.pending_claim_txos: typing.Dict[bytes, Tuple[int, int]] = {}
        # claim hash to lists of pending support txos
        self.pending_supports: DefaultDict[bytes, List[Tuple[int, int]]] = defaultdict(list)
        # support txo: (supported claim hash, support amount)
        self.pending_support_txos: Dict[Tuple[int, int], Tuple[bytes, int]] = {}
        # removed supports {name: {claim_hash: [(tx_num, nout), ...]}}
        self.pending_removed_support: DefaultDict[str, DefaultDict[bytes, List[Tuple[int, int]]]] = defaultdict(
            lambda: defaultdict(list))
        self.staged_pending_abandoned: Dict[bytes, StagedClaimtrieItem] = {}
        # removed activated support amounts by claim hash
        self.removed_active_support: DefaultDict[bytes, List[int]] = defaultdict(list)
        # pending activated support amounts by claim hash
        self.staged_activated_support: DefaultDict[bytes, List[int]] = defaultdict(list)
        # pending activated name and claim hash to claim/update txo amount
        self.staged_activated_claim: Dict[Tuple[str, bytes], int] = {}
        # pending claim and support activations per claim hash per name,
        # used to process takeovers due to added activations
        self.pending_activated: DefaultDict[str, DefaultDict[bytes, List[Tuple[PendingActivationKey, int]]]] = \
            defaultdict(lambda: defaultdict(list))
        # these are used for detecting early takeovers by not yet activated claims/supports
        self.possible_future_activated_support: DefaultDict[bytes, List[int]] = defaultdict(list)
        self.possible_future_activated_claim: Dict[Tuple[str, bytes], int] = {}
        self.possible_future_support_txos: DefaultDict[bytes, List[Tuple[int, int]]] = defaultdict(list)

    async def run_in_thread_with_lock(self, func, *args):
        # Run in a thread to prevent blocking.  Shielded so that
        # cancellations from shutdown don't lose work - when the task
        # completes the data will be flushed and then we shut down.
        # Take the state lock to be certain in-memory state is
        # consistent and not being updated elsewhere.
        async def run_in_thread_locked():
            async with self.state_lock:
                return await asyncio.get_event_loop().run_in_executor(self.executor, func, *args)
        return await asyncio.shield(run_in_thread_locked())

    async def check_and_advance_blocks(self, raw_blocks):
        """Process the list of raw blocks passed.  Detects and handles
        reorgs.
        """
        if not raw_blocks:
            return
        first = self.height + 1
        blocks = [self.coin.block(raw_block, first + n)
                  for n, raw_block in enumerate(raw_blocks)]
        headers = [block.header for block in blocks]
        hprevs = [self.coin.header_prevhash(h) for h in headers]
        chain = [self.tip] + [self.coin.header_hash(h) for h in headers[:-1]]

        if hprevs == chain:
            start = time.perf_counter()
            try:
                for block in blocks:
                    await self.run_in_thread_with_lock(self.advance_block, block)
                    print("******************\n")
            except:
                self.logger.exception("advance blocks failed")
                raise
            # if self.sql:
            #     await self.db.search_index.claim_consumer(self.db.claim_producer())
            for cache in self.search_cache.values():
                cache.clear()
            self.history_cache.clear()  # TODO: is this needed?
            self.notifications.notified_mempool_txs.clear()

            processed_time = time.perf_counter() - start
            self.block_count_metric.set(self.height)
            self.block_update_time_metric.observe(processed_time)
            self.status_server.set_height(self.db.fs_height, self.db.db_tip)
            if not self.db.first_sync:
                s = '' if len(blocks) == 1 else 's'
                self.logger.info('processed {:,d} block{} in {:.1f}s'.format(len(blocks), s, processed_time))
            if self._caught_up_event.is_set():
                # if self.sql:
                #     await self.db.search_index.apply_filters(self.sql.blocked_streams, self.sql.blocked_channels,
                #                                              self.sql.filtered_streams, self.sql.filtered_channels)
                await self.notifications.on_block(self.touched, self.height)
            self.touched = set()
        elif hprevs[0] != chain[0]:
            await self.reorg_chain()
        else:
            # It is probably possible but extremely rare that what
            # bitcoind returns doesn't form a chain because it
            # reorg-ed the chain as it was processing the batched
            # block hash requests.  Should this happen it's simplest
            # just to reset the prefetcher and try again.
            self.logger.warning('daemon blocks do not form a chain; '
                                'resetting the prefetcher')
            await self.prefetcher.reset_height(self.height)

    async def reorg_chain(self, count: Optional[int] = None):
        """Handle a chain reorganisation.

        Count is the number of blocks to simulate a reorg, or None for
        a real reorg."""
        if count is None:
            self.logger.info('chain reorg detected')
        else:
            self.logger.info(f'faking a reorg of {count:,d} blocks')

        async def get_raw_blocks(last_height, hex_hashes):
            heights = range(last_height, last_height - len(hex_hashes), -1)
            try:
                blocks = [await self.db.read_raw_block(height) for height in heights]
                self.logger.info(f'read {len(blocks)} blocks from disk')
                return blocks
            except FileNotFoundError:
                return await self.daemon.raw_blocks(hex_hashes)

        try:
            await self.flush(True)
            start, last, hashes = await self.reorg_hashes(count)
            # Reverse and convert to hex strings.
            hashes = [hash_to_hex_str(hash) for hash in reversed(hashes)]
            self.logger.info("reorg %i block hashes", len(hashes))

            for hex_hashes in chunks(hashes, 50):
                raw_blocks = await get_raw_blocks(last, hex_hashes)
                self.logger.info("got %i raw blocks", len(raw_blocks))
                await self.run_in_thread_with_lock(self.backup_blocks, raw_blocks)
                last -= len(raw_blocks)

            await self.prefetcher.reset_height(self.height)
            self.reorg_count_metric.inc()
        except:
            self.logger.exception("boom")
            raise
        finally:
            self.logger.info("done with reorg")

    async def reorg_hashes(self, count):
        """Return a pair (start, last, hashes) of blocks to back up during a
        reorg.

        The hashes are returned in order of increasing height.  Start
        is the height of the first hash, last of the last.
        """
        start, count = await self.calc_reorg_range(count)
        last = start + count - 1
        s = '' if count == 1 else 's'
        self.logger.info(f'chain was reorganised replacing {count:,d} '
                         f'block{s} at heights {start:,d}-{last:,d}')

        return start, last, await self.db.fs_block_hashes(start, count)

    async def calc_reorg_range(self, count: Optional[int]):
        """Calculate the reorg range"""

        def diff_pos(hashes1, hashes2):
            """Returns the index of the first difference in the hash lists.
            If both lists match returns their length."""
            for n, (hash1, hash2) in enumerate(zip(hashes1, hashes2)):
                if hash1 != hash2:
                    return n
            return len(hashes)

        if count is None:
            # A real reorg
            start = self.height - 1
            count = 1
            while start > 0:
                hashes = await self.db.fs_block_hashes(start, count)
                hex_hashes = [hash_to_hex_str(hash) for hash in hashes]
                d_hex_hashes = await self.daemon.block_hex_hashes(start, count)
                n = diff_pos(hex_hashes, d_hex_hashes)
                if n > 0:
                    start += n
                    break
                count = min(count * 2, start)
                start -= count

            count = (self.height - start) + 1
        else:
            start = (self.height - count) + 1

        return start, count

    # - Flushing
    def flush_data(self):
        """The data for a flush.  The lock must be taken."""
        assert self.state_lock.locked()
        return FlushData(self.height, self.tx_count, self.headers, self.block_hashes,
                         self.block_txs, self.claimtrie_stash, self.undo_infos, self.utxo_cache,
                         self.db_deletes, self.tip, self.undo_claims)

    async def flush(self, flush_utxos):
        def flush():
            self.db.flush_dbs(self.flush_data())
        await self.run_in_thread_with_lock(flush)

    async def _maybe_flush(self):
        # If caught up, flush everything as client queries are
        # performed on the DB.
        if self._caught_up_event.is_set():
            await self.flush(True)
        elif time.perf_counter() > self.next_cache_check:
            await self.flush(True)
            self.next_cache_check = time.perf_counter() + 30

    def _add_claim_or_update(self, height: int, txo: 'Output', tx_hash: bytes, tx_num: int, nout: int,
                             spent_claims: typing.Dict[bytes, typing.Tuple[int, int, str]]) -> List['RevertableOp']:
        try:
            claim_name = txo.normalized_name
        except UnicodeDecodeError:
            claim_name = ''.join(chr(c) for c in txo.script.values['claim_name'])
        if txo.script.is_claim_name:
            claim_hash = hash160(tx_hash + pack('>I', nout))[::-1]
            print(f"\tnew lbry://{claim_name}#{claim_hash.hex()} ({tx_num} {txo.amount})")
        else:
            claim_hash = txo.claim_hash[::-1]
            print(f"\tupdate lbry://{claim_name}#{claim_hash.hex()} ({tx_num} {txo.amount})")
        try:
            signable = txo.signable
        except:  # google.protobuf.message.DecodeError: Could not parse JSON.
            signable = None

        ops = []
        signing_channel_hash = None
        if signable and signable.signing_channel_hash:
            signing_channel_hash = txo.signable.signing_channel_hash[::-1]
        if txo.script.is_claim_name:
            root_tx_num, root_idx = tx_num, nout
        else:
            if claim_hash not in spent_claims:
                print(f"\tthis is a wonky tx, contains unlinked claim update {claim_hash.hex()}")
                return []
            (prev_tx_num, prev_idx, _) = spent_claims.pop(claim_hash)
            print(f"\tupdate lbry://{claim_name}#{claim_hash.hex()} {tx_hash[::-1].hex()} {txo.amount}")
            if (prev_tx_num, prev_idx) in self.pending_claims:
                previous_claim = self.pending_claims.pop((prev_tx_num, prev_idx))
                root_tx_num, root_idx = previous_claim.root_claim_tx_num, previous_claim.root_claim_tx_position
            else:
                k, v = self.db.get_claim_txo(
                    claim_hash
                )
                root_tx_num, root_idx = v.root_tx_num, v.root_position
                activation = self.db.get_activation(prev_tx_num, prev_idx)
                ops.extend(
                    StagedActivation(
                        ACTIVATED_CLAIM_TXO_TYPE, claim_hash, prev_tx_num, prev_idx, activation, claim_name, v.amount
                    ).get_remove_activate_ops()
                )
        pending = StagedClaimtrieItem(
            claim_name, claim_hash, txo.amount, self.coin.get_expiration_height(height), tx_num, nout, root_tx_num,
            root_idx, signing_channel_hash
        )
        self.pending_claims[(tx_num, nout)] = pending
        self.pending_claim_txos[claim_hash] = (tx_num, nout)
        ops.extend(pending.get_add_claim_utxo_ops())
        return ops

    def _add_support(self, txo: 'Output', tx_num: int, nout: int) -> List['RevertableOp']:
        supported_claim_hash = txo.claim_hash[::-1]
        self.pending_supports[supported_claim_hash].append((tx_num, nout))
        self.pending_support_txos[(tx_num, nout)] = supported_claim_hash, txo.amount
        print(f"\tsupport claim {supported_claim_hash.hex()} +{txo.amount}")
        return StagedClaimtrieSupport(
            supported_claim_hash, tx_num, nout, txo.amount
        ).get_add_support_utxo_ops()

    def _add_claim_or_support(self, height: int, tx_hash: bytes, tx_num: int, nout: int, txo: 'Output',
                              spent_claims: typing.Dict[bytes, Tuple[int, int, str]]) -> List['RevertableOp']:
        if txo.script.is_claim_name or txo.script.is_update_claim:
            return self._add_claim_or_update(height, txo, tx_hash, tx_num, nout, spent_claims)
        elif txo.script.is_support_claim or txo.script.is_support_claim_data:
            return self._add_support(txo, tx_num, nout)
        return []

    def _spend_support_txo(self, txin):
        txin_num = self.db.transaction_num_mapping[txin.prev_hash]
        if (txin_num, txin.prev_idx) in self.pending_support_txos:
            spent_support, support_amount = self.pending_support_txos.pop((txin_num, txin.prev_idx))
            self.pending_supports[spent_support].remove((txin_num, txin.prev_idx))
            supported_name = self._get_pending_claim_name(spent_support)
            print(f"\tspent support for lbry://{supported_name}#{spent_support.hex()}")
            self.pending_removed_support[supported_name][spent_support].append((txin_num, txin.prev_idx))
            return StagedClaimtrieSupport(
                spent_support, txin_num, txin.prev_idx, support_amount
            ).get_spend_support_txo_ops()
        spent_support, support_amount = self.db.get_supported_claim_from_txo(txin_num, txin.prev_idx)
        if spent_support:
            supported_name = self._get_pending_claim_name(spent_support)
            self.pending_removed_support[supported_name][spent_support].append((txin_num, txin.prev_idx))
            activation = self.db.get_activation(txin_num, txin.prev_idx, is_support=True)
            self.removed_active_support[spent_support].append(support_amount)
            print(f"\tspent support for lbry://{supported_name}#{spent_support.hex()} activation:{activation} {support_amount}")
            return StagedClaimtrieSupport(
                spent_support, txin_num, txin.prev_idx, support_amount
            ).get_spend_support_txo_ops() + \
                StagedActivation(
                    ACTIVATED_SUPPORT_TXO_TYPE, spent_support, txin_num, txin.prev_idx, activation, supported_name,
                    support_amount
                ).get_remove_activate_ops()
        return []

    def _spend_claim_txo(self, txin: TxInput, spent_claims: Dict[bytes, Tuple[int, int, str]]):
        txin_num = self.db.transaction_num_mapping[txin.prev_hash]
        if (txin_num, txin.prev_idx) in self.pending_claims:
            spent = self.pending_claims[(txin_num, txin.prev_idx)]
        else:
            spent_claim_hash_and_name = self.db.get_claim_from_txo(
                txin_num, txin.prev_idx
            )
            if not spent_claim_hash_and_name:  # txo is not a claim
                return []
            claim_hash = spent_claim_hash_and_name.claim_hash
            signing_hash = self.db.get_channel_for_claim(claim_hash)
            k, v = self.db.get_claim_txo(claim_hash)
            spent = StagedClaimtrieItem(
                v.name, claim_hash, v.amount,
                self.coin.get_expiration_height(bisect_right(self.db.tx_counts, txin_num)),
                txin_num, txin.prev_idx, v.root_tx_num, v.root_position, signing_hash
            )
        spent_claims[spent.claim_hash] = (spent.tx_num, spent.position, spent.name)
        print(f"\tspend lbry://{spent.name}#{spent.claim_hash.hex()}")
        return spent.get_spend_claim_txo_ops()

    def _spend_claim_or_support_txo(self, txin, spent_claims):
        spend_claim_ops = self._spend_claim_txo(txin, spent_claims)
        if spend_claim_ops:
            return spend_claim_ops
        return self._spend_support_txo(txin)

    def _abandon_claim(self, claim_hash, tx_num, nout, name) -> List['RevertableOp']:
        if (tx_num, nout) in self.pending_claims:
            pending = self.pending_claims.pop((tx_num, nout))
            self.staged_pending_abandoned[pending.claim_hash] = pending
            claim_root_tx_num, claim_root_idx = pending.root_claim_tx_num, pending.root_claim_tx_position
            prev_amount, prev_signing_hash = pending.amount, pending.signing_hash
            expiration = self.coin.get_expiration_height(self.height)
        else:
            k, v = self.db.get_claim_txo(
                claim_hash
            )
            claim_root_tx_num, claim_root_idx, prev_amount = v.root_tx_num,  v.root_position, v.amount
            prev_signing_hash = self.db.get_channel_for_claim(claim_hash)
            expiration = self.coin.get_expiration_height(bisect_right(self.db.tx_counts, tx_num))
        self.staged_pending_abandoned[claim_hash] = staged = StagedClaimtrieItem(
            name, claim_hash, prev_amount, expiration, tx_num, nout, claim_root_tx_num,
            claim_root_idx, prev_signing_hash
        )

        self.pending_supports[claim_hash].clear()
        self.pending_supports.pop(claim_hash)

        return staged.get_abandon_ops(self.db.db)

    def _abandon(self, spent_claims) -> List['RevertableOp']:
        # Handle abandoned claims
        ops = []

        for abandoned_claim_hash, (tx_num, nout, name) in spent_claims.items():
            print(f"\tabandon lbry://{name}#{abandoned_claim_hash.hex()} {tx_num} {nout}")
            ops.extend(self._abandon_claim(abandoned_claim_hash, tx_num, nout, name))
        return ops

    def _expire_claims(self, height: int):
        expired = self.db.get_expired_by_height(height)
        spent_claims = {}
        ops = []
        for expired_claim_hash, (tx_num, position, name, txi) in expired.items():
            if (tx_num, position) not in self.pending_claims:
                ops.extend(self._spend_claim_txo(txi, spent_claims))
        if expired:
            # do this to follow the same content claim removing pathway as if a claim (possible channel) was abandoned
            ops.extend(self._abandon(spent_claims))
        return ops

    def _get_pending_claim_amount(self, name: str, claim_hash: bytes, height=None) -> int:
        if (name, claim_hash) in self.staged_activated_claim:
            return self.staged_activated_claim[(name, claim_hash)]
        if (name, claim_hash) in self.possible_future_activated_claim:
            return self.possible_future_activated_claim[(name, claim_hash)]
        return self.db._get_active_amount(claim_hash, ACTIVATED_CLAIM_TXO_TYPE, height or (self.height + 1))

    def _get_pending_claim_name(self, claim_hash: bytes) -> Optional[str]:
        assert claim_hash is not None
        if claim_hash in self.pending_claims:
            return self.pending_claims[claim_hash].name
        claim_info = self.db.get_claim_txo(claim_hash)
        if claim_info:
            return claim_info[1].name

    def _get_pending_supported_amount(self, claim_hash: bytes, height: Optional[int] = None) -> int:
        amount = self.db._get_active_amount(claim_hash, ACTIVATED_SUPPORT_TXO_TYPE, height or (self.height + 1)) or 0
        if claim_hash in self.staged_activated_support:
            amount += sum(self.staged_activated_support[claim_hash])
        if claim_hash in self.possible_future_activated_support:
            amount += sum(self.possible_future_activated_support[claim_hash])
        if claim_hash in self.removed_active_support:
            return amount - sum(self.removed_active_support[claim_hash])
        return amount

    def _get_pending_effective_amount(self, name: str, claim_hash: bytes, height: Optional[int] = None) -> int:
        claim_amount = self._get_pending_claim_amount(name, claim_hash, height=height)
        support_amount = self._get_pending_supported_amount(claim_hash, height=height)
        return claim_amount + support_amount

    def _get_takeover_ops(self, height: int) -> List['RevertableOp']:

        # cache for controlling claims as of the previous block
        controlling_claims = {}

        def get_controlling(_name):
            if _name not in controlling_claims:
                _controlling = self.db.get_controlling_claim(_name)
                controlling_claims[_name] = _controlling
            else:
                _controlling = controlling_claims[_name]
            return _controlling

        ops = []
        names_with_abandoned_controlling_claims: List[str] = []

        # get the claims and supports previously scheduled to be activated at this block
        activated_at_height = self.db.get_activated_at_height(height)
        activate_in_future = defaultdict(lambda: defaultdict(list))
        future_activations = defaultdict(dict)

        def get_delayed_activate_ops(name: str, claim_hash: bytes, is_new_claim: bool, tx_num: int, nout: int,
                                     amount: int, is_support: bool) -> List['RevertableOp']:
            controlling = get_controlling(name)
            nothing_is_controlling = not controlling
            staged_is_controlling = False if not controlling else claim_hash == controlling.claim_hash
            controlling_is_abandoned = False if not controlling else \
                controlling.claim_hash in names_with_abandoned_controlling_claims

            if nothing_is_controlling or staged_is_controlling or controlling_is_abandoned:
                delay = 0
            elif is_new_claim:
                delay = self.coin.get_delay_for_name(height - controlling.height)
            else:
                controlling_effective_amount = self._get_pending_effective_amount(name, controlling.claim_hash)
                staged_effective_amount = self._get_pending_effective_amount(name, claim_hash)
                staged_update_could_cause_takeover = staged_effective_amount > controlling_effective_amount
                delay = 0 if not staged_update_could_cause_takeover else self.coin.get_delay_for_name(
                    height - controlling.height
                )
            if delay == 0:  # if delay was 0 it needs to be considered for takeovers
                activated_at_height[PendingActivationValue(claim_hash, name)].append(
                    PendingActivationKey(
                        height, ACTIVATED_SUPPORT_TXO_TYPE if is_support else ACTIVATED_CLAIM_TXO_TYPE, tx_num, nout
                    )
                )
            else:  # if the delay was higher if still needs to be considered if something else triggers a takeover
                activate_in_future[name][claim_hash].append((
                    PendingActivationKey(
                        height + delay, ACTIVATED_SUPPORT_TXO_TYPE if is_support else ACTIVATED_CLAIM_TXO_TYPE,
                        tx_num, nout
                    ), amount
                ))
                if is_support:
                    self.possible_future_support_txos[claim_hash].append((tx_num, nout))
            return StagedActivation(
                ACTIVATED_SUPPORT_TXO_TYPE if is_support else ACTIVATED_CLAIM_TXO_TYPE, claim_hash, tx_num, nout,
                height + delay, name, amount
            ).get_activate_ops()

        # determine names needing takeover/deletion due to controlling claims being abandoned
        # and add ops to deactivate abandoned claims
        for claim_hash, staged in self.staged_pending_abandoned.items():
            controlling = get_controlling(staged.name)
            if controlling and controlling.claim_hash == claim_hash:
                names_with_abandoned_controlling_claims.append(staged.name)
                print(f"\t{staged.name} needs takeover")
            activation = self.db.get_activation(staged.tx_num, staged.position)
            if activation > 0:  #  db returns -1 for non-existent txos
                # removed queued future activation from the db
                ops.extend(
                    StagedActivation(
                        ACTIVATED_CLAIM_TXO_TYPE, staged.claim_hash, staged.tx_num, staged.position,
                        activation, staged.name, staged.amount
                    ).get_remove_activate_ops()
                )
            else:
                # it hadn't yet been activated
                pass

        # get the removed activated supports for controlling claims to determine if takeovers are possible
        abandoned_support_check_need_takeover = defaultdict(list)
        for claim_hash, amounts in self.removed_active_support.items():
            name = self._get_pending_claim_name(claim_hash)
            controlling = get_controlling(name)
            if controlling and controlling.claim_hash == claim_hash and \
                    name not in names_with_abandoned_controlling_claims:
                abandoned_support_check_need_takeover[(name, claim_hash)].extend(amounts)

        # prepare to activate or delay activation of the pending claims being added this block
        for (tx_num, nout), staged in self.pending_claims.items():
            ops.extend(get_delayed_activate_ops(
                staged.name, staged.claim_hash, not staged.is_update, tx_num, nout, staged.amount, is_support=False
            ))

        # and the supports
        for (tx_num, nout), (claim_hash, amount) in self.pending_support_txos.items():
            if claim_hash in self.staged_pending_abandoned:
                continue
            elif claim_hash in self.pending_claim_txos:
                name = self.pending_claims[self.pending_claim_txos[claim_hash]].name
                staged_is_new_claim = not self.pending_claims[self.pending_claim_txos[claim_hash]].is_update
            else:
                k, v = self.db.get_claim_txo(claim_hash)
                name = v.name
                staged_is_new_claim = (v.root_tx_num, v.root_position) == (k.tx_num, k.position)
            ops.extend(get_delayed_activate_ops(
                name, claim_hash, staged_is_new_claim, tx_num, nout, amount, is_support=True
            ))

        # add the activation/delayed-activation ops
        for activated, activated_txos in activated_at_height.items():
            controlling = get_controlling(activated.name)

            if activated.claim_hash in self.staged_pending_abandoned:
                continue
            reactivate = False
            if not controlling or controlling.claim_hash == activated.claim_hash:
                # there is no delay for claims to a name without a controlling value or to the controlling value
                reactivate = True
            for activated_txo in activated_txos:
                if activated_txo.is_support and (activated_txo.tx_num, activated_txo.position) in \
                        self.pending_removed_support[activated.name][activated.claim_hash]:
                    print("\tskip activate support for pending abandoned claim")
                    continue
                if activated_txo.is_claim:
                    txo_type = ACTIVATED_CLAIM_TXO_TYPE
                    txo_tup = (activated_txo.tx_num, activated_txo.position)
                    if txo_tup in self.pending_claims:
                        amount = self.pending_claims[txo_tup].amount
                    else:
                        amount = self.db.get_claim_txo_amount(
                            activated.claim_hash, activated_txo.tx_num, activated_txo.position
                        )
                    self.staged_activated_claim[(activated.name, activated.claim_hash)] = amount
                else:
                    txo_type = ACTIVATED_SUPPORT_TXO_TYPE
                    txo_tup = (activated_txo.tx_num, activated_txo.position)
                    if txo_tup in self.pending_support_txos:
                        amount = self.pending_support_txos[txo_tup][1]
                    else:
                        amount = self.db.get_support_txo_amount(
                            activated.claim_hash, activated_txo.tx_num, activated_txo.position
                        )
                    self.staged_activated_support[activated.claim_hash].append(amount)
                self.pending_activated[activated.name][activated.claim_hash].append((activated_txo, amount))
                print(f"\tactivate {'support' if txo_type == ACTIVATED_SUPPORT_TXO_TYPE else 'claim'} "
                      f"lbry://{activated.name}#{activated.claim_hash.hex()} @ {activated_txo.height}")
                if reactivate:
                    ops.extend(
                        StagedActivation(
                            txo_type, activated.claim_hash, activated_txo.tx_num, activated_txo.position,
                            activated_txo.height, activated.name, amount
                        ).get_activate_ops()
                    )

        # go through claims where the controlling claim or supports to the controlling claim have been abandoned
        # check if takeovers are needed or if the name node is now empty
        need_reactivate_if_takes_over = {}
        for need_takeover in names_with_abandoned_controlling_claims:
            existing = self.db.get_claim_txos_for_name(need_takeover)
            has_candidate = False
            # add existing claims to the queue for the takeover
            # track that we need to reactivate these if one of them becomes controlling
            for candidate_claim_hash, (tx_num, nout) in existing.items():
                if candidate_claim_hash in self.staged_pending_abandoned:
                    continue
                has_candidate = True
                existing_activation = self.db.get_activation(tx_num, nout)
                activate_key = PendingActivationKey(
                    existing_activation, ACTIVATED_CLAIM_TXO_TYPE, tx_num, nout
                )
                self.pending_activated[need_takeover][candidate_claim_hash].append((
                    activate_key, self.db.get_claim_txo_amount(candidate_claim_hash, tx_num, nout)
                ))
                need_reactivate_if_takes_over[(need_takeover, candidate_claim_hash)] = activate_key
                print(f"\tcandidate to takeover abandoned controlling claim for lbry://{need_takeover} - "
                      f"{activate_key.tx_num}:{activate_key.position} {activate_key.is_claim}")
            if not has_candidate:
                # remove name takeover entry, the name is now unclaimed
                controlling = get_controlling(need_takeover)
                ops.extend(get_remove_name_ops(need_takeover, controlling.claim_hash, controlling.height))

        # scan for possible takeovers out of the accumulated activations, of these make sure there
        # aren't any future activations for the taken over names with yet higher amounts, if there are
        # these need to get activated now and take over instead. for example:
        # claim A is winning for 0.1 for long enough for a > 1 takeover delay
        # claim B is made for 0.2
        # a block later, claim C is made for 0.3, it will schedule to activate 1 (or rarely 2) block(s) after B
        # upon the delayed activation of B, we need to detect to activate C and make it take over early instead
        for activated, activated_txos in self.db.get_future_activated(height).items():
            # uses the pending effective amount for the future activation height, not the current height
            future_amount = self._get_pending_claim_amount(
                activated.name, activated.claim_hash, activated_txos[-1].height + 1
            )
            v = future_amount, activated, activated_txos[-1]
            future_activations[activated.name][activated.claim_hash] = v

        for name, future_activated in activate_in_future.items():
            for claim_hash, activated in future_activated.items():
                for txo in activated:
                    v = txo[1], PendingActivationValue(claim_hash, name), txo[0]
                    future_activations[name][claim_hash] = v
                    if v[2].is_claim:
                        self.possible_future_activated_claim[(name, claim_hash)] = v[0]
                    else:
                        self.possible_future_activated_support[claim_hash].append(v[0])

        # process takeovers
        checked_names = set()
        for name, activated in self.pending_activated.items():
            checked_names.add(name)
            controlling = controlling_claims[name]
            amounts = {
                claim_hash: self._get_pending_effective_amount(name, claim_hash)
                for claim_hash in activated.keys() if claim_hash not in self.staged_pending_abandoned
            }
            # if there is a controlling claim include it in the amounts to ensure it remains the max
            if controlling and controlling.claim_hash not in self.staged_pending_abandoned:
                amounts[controlling.claim_hash] = self._get_pending_effective_amount(name, controlling.claim_hash)
            winning_claim_hash = max(amounts, key=lambda x: amounts[x])
            if not controlling or (winning_claim_hash != controlling.claim_hash and
                                   name in names_with_abandoned_controlling_claims) or \
                    ((winning_claim_hash != controlling.claim_hash) and (amounts[winning_claim_hash] > amounts[controlling.claim_hash])):
                amounts_with_future_activations = {claim_hash: amount for claim_hash, amount in amounts.items()}
                amounts_with_future_activations.update(
                    {
                        claim_hash: self._get_pending_effective_amount(
                            name, claim_hash, self.height + 1 + self.coin.maxTakeoverDelay
                        ) for claim_hash in future_activations[name]
                    }
                )
                winning_including_future_activations = max(
                    amounts_with_future_activations, key=lambda x: amounts_with_future_activations[x]
                )
                if winning_claim_hash != winning_including_future_activations:
                    print(f"\ttakeover of {name} by {winning_claim_hash.hex()} triggered early activation and "
                          f"takeover by {winning_including_future_activations.hex()} at {height}")
                    # handle a pending activated claim jumping the takeover delay when another name takes over
                    if winning_including_future_activations not in self.pending_claim_txos:
                        claim = self.db.get_claim_txo(winning_including_future_activations)
                        tx_num = claim[0].tx_num
                        position = claim[0].position
                        amount = claim[1].amount
                        activation = self.db.get_activation(tx_num, position)

                    else:
                        tx_num, position = self.pending_claim_txos[winning_including_future_activations]
                        amount = None
                        activation = None
                        for (k, tx_amount) in activate_in_future[name][winning_including_future_activations]:
                            if (k.tx_num, k.position) == (tx_num, position):
                                amount = tx_amount
                                activation = k.height
                                break
                        assert None not in (amount, activation)
                    # update the claim that's activating early
                    ops.extend(
                        StagedActivation(
                            ACTIVATED_CLAIM_TXO_TYPE, winning_including_future_activations, tx_num,
                            position, activation, name, amount
                        ).get_remove_activate_ops()
                    )
                    ops.extend(
                        StagedActivation(
                            ACTIVATED_CLAIM_TXO_TYPE, winning_including_future_activations, tx_num,
                            position, height, name, amount
                        ).get_activate_ops()
                    )
                    for (k, amount) in activate_in_future[name][winning_including_future_activations]:
                        txo = (k.tx_num, k.position)
                        if txo in self.possible_future_support_txos[winning_including_future_activations]:
                            t = ACTIVATED_SUPPORT_TXO_TYPE
                            ops.extend(
                                StagedActivation(
                                    t, winning_including_future_activations, k.tx_num,
                                    k.position, k.height, name, amount
                                ).get_remove_activate_ops()
                            )
                            ops.extend(
                                StagedActivation(
                                    t, winning_including_future_activations, k.tx_num,
                                    k.position, height, name, amount
                                ).get_activate_ops()
                            )
                    ops.extend(get_takeover_name_ops(name, winning_including_future_activations, height, controlling))
                elif not controlling or (winning_claim_hash != controlling.claim_hash and
                                       name in names_with_abandoned_controlling_claims) or \
                        ((winning_claim_hash != controlling.claim_hash) and (amounts[winning_claim_hash] > amounts[controlling.claim_hash])):
                    print(f"\ttakeover {name} by {winning_claim_hash.hex()} at {height}")
                    if (name, winning_claim_hash) in need_reactivate_if_takes_over:
                        previous_pending_activate = need_reactivate_if_takes_over[(name, winning_claim_hash)]
                        amount = self.db.get_claim_txo_amount(
                            winning_claim_hash, previous_pending_activate.tx_num, previous_pending_activate.position
                        )
                        if winning_claim_hash in self.pending_claim_txos:
                            tx_num, position = self.pending_claim_txos[winning_claim_hash]
                            amount = self.pending_claims[(tx_num, position)].amount
                        else:
                            tx_num, position = previous_pending_activate.tx_num, previous_pending_activate.position
                        if previous_pending_activate.height > height:
                            # the claim had a pending activation in the future, move it to now
                            ops.extend(
                                StagedActivation(
                                    ACTIVATED_CLAIM_TXO_TYPE, winning_claim_hash, tx_num,
                                    position, previous_pending_activate.height, name, amount
                                ).get_remove_activate_ops()
                            )
                            ops.extend(
                                StagedActivation(
                                    ACTIVATED_CLAIM_TXO_TYPE, winning_claim_hash, tx_num,
                                    position, height, name, amount
                                ).get_activate_ops()
                            )
                    ops.extend(get_takeover_name_ops(name, winning_claim_hash, height, controlling))
                elif winning_claim_hash == controlling.claim_hash:
                    print("\tstill winning")
                    pass
                else:
                    print("\tno takeover")
                    pass

        # handle remaining takeovers from abandoned supports
        for (name, claim_hash), amounts in abandoned_support_check_need_takeover.items():
            if name in checked_names:
                continue
            checked_names.add(name)
            controlling = get_controlling(name)
            amounts = {
                claim_hash: self._get_pending_effective_amount(name, claim_hash)
                for claim_hash in self.db.get_claims_for_name(name) if claim_hash not in self.staged_pending_abandoned
            }
            if controlling and controlling.claim_hash not in self.staged_pending_abandoned:
                amounts[controlling.claim_hash] = self._get_pending_effective_amount(name, controlling.claim_hash)
            winning = max(amounts, key=lambda x: amounts[x])
            if (controlling and winning != controlling.claim_hash) or (not controlling and winning):
                print(f"\ttakeover from abandoned support {controlling.claim_hash.hex()} -> {winning.hex()}")
                ops.extend(get_takeover_name_ops(name, winning, height, controlling))
        return ops

    def advance_block(self, block):
        height = self.height + 1
        print("advance ", height)
        txs: List[Tuple[Tx, bytes]] = block.transactions
        block_hash = self.coin.header_hash(block.header)

        self.block_hashes.append(block_hash)
        self.block_txs.append((b''.join(tx_hash for tx, tx_hash in txs), [tx.raw for tx, _ in txs]))

        first_tx_num = self.tx_count
        undo_info = []
        hashXs_by_tx = []
        tx_count = self.tx_count

        # Use local vars for speed in the loops
        put_utxo = self.utxo_cache.__setitem__
        claimtrie_stash = []
        claimtrie_stash_extend = claimtrie_stash.extend
        spend_utxo = self.spend_utxo
        undo_info_append = undo_info.append
        update_touched = self.touched.update
        append_hashX_by_tx = hashXs_by_tx.append
        hashX_from_script = self.coin.hashX_from_script

        for tx, tx_hash in txs:
            spent_claims = {}

            hashXs = []  # hashXs touched by spent inputs/rx outputs
            append_hashX = hashXs.append
            tx_numb = pack('<I', tx_count)

            # Spend the inputs
            for txin in tx.inputs:
                if txin.is_generation():
                    continue
                # spend utxo for address histories
                cache_value = spend_utxo(txin.prev_hash, txin.prev_idx)
                undo_info_append(cache_value)
                append_hashX(cache_value[:-12])

                spend_claim_or_support_ops = self._spend_claim_or_support_txo(txin, spent_claims)
                if spend_claim_or_support_ops:
                    claimtrie_stash_extend(spend_claim_or_support_ops)

            # Add the new UTXOs
            for nout, txout in enumerate(tx.outputs):
                # Get the hashX.  Ignore unspendable outputs
                hashX = hashX_from_script(txout.pk_script)
                if hashX:
                    append_hashX(hashX)
                    put_utxo(tx_hash + pack('<H', nout), hashX + tx_numb + pack('<Q', txout.value))

                # add claim/support txo
                script = OutputScript(txout.pk_script)
                script.parse()

                claim_or_support_ops = self._add_claim_or_support(
                    height, tx_hash, tx_count, nout, Output(txout.value, script), spent_claims
                )
                if claim_or_support_ops:
                    claimtrie_stash_extend(claim_or_support_ops)

            # Handle abandoned claims
            abandon_ops = self._abandon(spent_claims)
            if abandon_ops:
                claimtrie_stash_extend(abandon_ops)

            append_hashX_by_tx(hashXs)
            update_touched(hashXs)
            self.db.total_transactions.append(tx_hash)
            self.db.transaction_num_mapping[tx_hash] = tx_count
            tx_count += 1

        # handle expired claims
        expired_ops = self._expire_claims(height)
        if expired_ops:
            print(f"************\nexpire claims at block {height}\n************")
            claimtrie_stash_extend(expired_ops)

        # activate claims and process takeovers
        takeover_ops = self._get_takeover_ops(height)
        if takeover_ops:
            claimtrie_stash_extend(takeover_ops)

        # self.db.add_unflushed(hashXs_by_tx, self.tx_count)
        _unflushed = self.db.hist_unflushed
        _count = 0
        for _tx_num, _hashXs in enumerate(hashXs_by_tx, start=first_tx_num):
            for _hashX in set(_hashXs):
                _unflushed[_hashX].append(_tx_num)
            _count += len(_hashXs)
        self.db.hist_unflushed_count += _count
        self.tx_count = tx_count
        self.db.tx_counts.append(self.tx_count)

        undo_claims = b''.join(op.invert().pack() for op in claimtrie_stash)
        self.claimtrie_stash.extend(claimtrie_stash)
        # print("%i undo bytes for %i (%i claimtrie stash ops)" % (len(undo_claims), height, len(claimtrie_stash)))

        if height >= self.daemon.cached_height() - self.env.reorg_limit:
            self.undo_infos.append((undo_info, height))
            self.undo_claims.append((undo_claims, height))
            self.db.write_raw_block(block.raw, height)

        self.height = height
        self.headers.append(block.header)
        self.tip = self.coin.header_hash(block.header)

        self.db.flush_dbs(self.flush_data())

        # self.effective_amount_changes.clear()

        self.pending_claims.clear()
        self.pending_claim_txos.clear()
        self.pending_supports.clear()
        self.pending_support_txos.clear()
        self.pending_removed_support.clear()
        self.staged_pending_abandoned.clear()
        self.removed_active_support.clear()
        self.staged_activated_support.clear()
        self.staged_activated_claim.clear()
        self.pending_activated.clear()
        self.possible_future_activated_claim.clear()
        self.possible_future_activated_support.clear()
        self.possible_future_support_txos.clear()

        for cache in self.search_cache.values():
            cache.clear()
        self.history_cache.clear()
        self.notifications.notified_mempool_txs.clear()

    def backup_blocks(self, raw_blocks):
        """Backup the raw blocks and flush.

        The blocks should be in order of decreasing height, starting at.
        self.height.  A flush is performed once the blocks are backed up.
        """
        self.db.assert_flushed(self.flush_data())
        assert self.height >= len(raw_blocks)

        coin = self.coin
        for raw_block in raw_blocks:
            self.logger.info("backup block %i", self.height)
            # Check and update self.tip
            block = coin.block(raw_block, self.height)
            header_hash = coin.header_hash(block.header)
            if header_hash != self.tip:
                raise ChainError('backup block {} not tip {} at height {:,d}'
                                 .format(hash_to_hex_str(header_hash),
                                         hash_to_hex_str(self.tip),
                                         self.height))
            self.tip = coin.header_prevhash(block.header)
            self.backup_txs(block.transactions)
            self.height -= 1
            self.db.tx_counts.pop()

            # self.touched can include other addresses which is
            # harmless, but remove None.
            self.touched.discard(None)

            self.db.flush_backup(self.flush_data(), self.touched)
            self.logger.info(f'backed up to height {self.height:,d}')

    def backup_txs(self, txs):
        # Prevout values, in order down the block (coinbase first if present)
        # undo_info is in reverse block order
        undo_info, undo_claims = self.db.read_undo_info(self.height)
        if undo_info is None:
            raise ChainError(f'no undo information found for height {self.height:,d}')
        n = len(undo_info)

        # Use local vars for speed in the loops
        s_pack = pack
        undo_entry_len = 12 + HASHX_LEN

        for tx, tx_hash in reversed(txs):
            for idx, txout in enumerate(tx.outputs):
                # Spend the TX outputs.  Be careful with unspendable
                # outputs - we didn't save those in the first place.
                hashX = self.coin.hashX_from_script(txout.pk_script)
                if hashX:
                    cache_value = self.spend_utxo(tx_hash, idx)
                    self.touched.add(cache_value[:-12])

            # Restore the inputs
            for txin in reversed(tx.inputs):
                if txin.is_generation():
                    continue
                n -= undo_entry_len
                undo_item = undo_info[n:n + undo_entry_len]
                self.utxo_cache[txin.prev_hash + s_pack('<H', txin.prev_idx)] = undo_item
                self.touched.add(undo_item[:-12])

            self.db.transaction_num_mapping.pop(self.db.total_transactions.pop())

        assert n == 0
        self.tx_count -= len(txs)
        self.undo_claims.append((undo_claims, self.height))

    """An in-memory UTXO cache, representing all changes to UTXO state
    since the last DB flush.

    We want to store millions of these in memory for optimal
    performance during initial sync, because then it is possible to
    spend UTXOs without ever going to the database (other than as an
    entry in the address history, and there is only one such entry per
    TX not per UTXO).  So store them in a Python dictionary with
    binary keys and values.

      Key:    TX_HASH + TX_IDX           (32 + 2 = 34 bytes)
      Value:  HASHX + TX_NUM + VALUE     (11 + 4 + 8 = 23 bytes)

    That's 57 bytes of raw data in-memory.  Python dictionary overhead
    means each entry actually uses about 205 bytes of memory.  So
    almost 5 million UTXOs can fit in 1GB of RAM.  There are
    approximately 42 million UTXOs on bitcoin mainnet at height
    433,000.

    Semantics:

      add:   Add it to the cache dictionary.

      spend: Remove it if in the cache dictionary.  Otherwise it's
             been flushed to the DB.  Each UTXO is responsible for two
             entries in the DB.  Mark them for deletion in the next
             cache flush.

    The UTXO database format has to be able to do two things efficiently:

      1.  Given an address be able to list its UTXOs and their values
          so its balance can be efficiently computed.

      2.  When processing transactions, for each prevout spent - a (tx_hash,
          idx) pair - we have to be able to remove it from the DB.  To send
          notifications to clients we also need to know any address it paid
          to.

    To this end we maintain two "tables", one for each point above:

      1.  Key: b'u' + address_hashX + tx_idx + tx_num
          Value: the UTXO value as a 64-bit unsigned integer

      2.  Key: b'h' + compressed_tx_hash + tx_idx + tx_num
          Value: hashX

    The compressed tx hash is just the first few bytes of the hash of
    the tx in which the UTXO was created.  As this is not unique there
    will be potential collisions so tx_num is also in the key.  When
    looking up a UTXO the prefix space of the compressed hash needs to
    be searched and resolved if necessary with the tx_num.  The
    collision rate is low (<0.1%).
    """

    def spend_utxo(self, tx_hash, tx_idx):
        """Spend a UTXO and return the 33-byte value.

        If the UTXO is not in the cache it must be on disk.  We store
        all UTXOs so not finding one indicates a logic error or DB
        corruption.
        """

        # Fast track is it being in the cache
        idx_packed = pack('<H', tx_idx)
        cache_value = self.utxo_cache.pop(tx_hash + idx_packed, None)
        if cache_value:
            return cache_value

        # Spend it from the DB.
        # Key: b'h' + compressed_tx_hash + tx_idx + tx_num
        # Value: hashX
        prefix = DB_PREFIXES.HASHX_UTXO_PREFIX.value + tx_hash[:4] + idx_packed
        candidates = {db_key: hashX for db_key, hashX in self.db.db.iterator(prefix=prefix)}

        for hdb_key, hashX in candidates.items():
            tx_num_packed = hdb_key[-4:]
            if len(candidates) > 1:
                tx_num, = unpack('<I', tx_num_packed)
                try:
                    hash, height = self.db.fs_tx_hash(tx_num)
                except IndexError:
                    self.logger.error("data integrity error for hashx history: %s missing tx #%s (%s:%s)",
                                      hashX.hex(), tx_num, hash_to_hex_str(tx_hash), tx_idx)
                    continue
                if hash != tx_hash:
                    assert hash is not None  # Should always be found
                    continue

            # Key: b'u' + address_hashX + tx_idx + tx_num
            # Value: the UTXO value as a 64-bit unsigned integer
            udb_key = DB_PREFIXES.UTXO_PREFIX.value + hashX + hdb_key[-6:]
            utxo_value_packed = self.db.db.get(udb_key)
            if utxo_value_packed is None:
                self.logger.warning(
                    "%s:%s is not found in UTXO db for %s", hash_to_hex_str(tx_hash), tx_idx, hash_to_hex_str(hashX)
                )
                raise ChainError(f"{hash_to_hex_str(tx_hash)}:{tx_idx} is not found in UTXO db for {hash_to_hex_str(hashX)}")
            # Remove both entries for this UTXO
            self.db_deletes.append(hdb_key)
            self.db_deletes.append(udb_key)

            return hashX + tx_num_packed + utxo_value_packed

        self.logger.error('UTXO {hash_to_hex_str(tx_hash)} / {tx_idx} not found in "h" table')
        raise ChainError('UTXO {} / {:,d} not found in "h" table'
                         .format(hash_to_hex_str(tx_hash), tx_idx))

    async def _process_prefetched_blocks(self):
        """Loop forever processing blocks as they arrive."""
        while True:
            if self.height == self.daemon.cached_height():
                if not self._caught_up_event.is_set():
                    await self._first_caught_up()
                    self._caught_up_event.set()
            await self.blocks_event.wait()
            self.blocks_event.clear()
            if self.reorg_count:  # this could only happen by calling the reorg rpc
                await self.reorg_chain(self.reorg_count)
                self.reorg_count = 0
            else:
                blocks = self.prefetcher.get_prefetched_blocks()
                try:
                    await self.check_and_advance_blocks(blocks)
                except Exception:
                    self.logger.exception("error while processing txs")
                    raise

    async def _first_caught_up(self):
        self.logger.info(f'caught up to height {self.height}')
        # Flush everything but with first_sync->False state.
        first_sync = self.db.first_sync
        self.db.first_sync = False
        await self.flush(True)
        if first_sync:
            self.logger.info(f'{lbry.__version__} synced to '
                             f'height {self.height:,d}')
        # Reopen for serving
        await self.db.open_for_serving()

    async def _first_open_dbs(self):
        await self.db.open_for_sync()
        self.height = self.db.db_height
        self.tip = self.db.db_tip
        self.tx_count = self.db.db_tx_count

    # --- External API

    async def fetch_and_process_blocks(self, caught_up_event):
        """Fetch, process and index blocks from the daemon.

        Sets caught_up_event when first caught up.  Flushes to disk
        and shuts down cleanly if cancelled.

        This is mainly because if, during initial sync ElectrumX is
        asked to shut down when a large number of blocks have been
        processed but not written to disk, it should write those to
        disk before exiting, as otherwise a significant amount of work
        could be lost.
        """

        self._caught_up_event = caught_up_event
        try:
            await self._first_open_dbs()
            self.status_server.set_height(self.db.fs_height, self.db.db_tip)
            await asyncio.wait([
                self.prefetcher.main_loop(self.height),
                self._process_prefetched_blocks()
            ])
        except asyncio.CancelledError:
            raise
        except:
            self.logger.exception("Block processing failed!")
            raise
        finally:
            self.status_server.stop()
            # Shut down block processing
            self.logger.info('flushing to DB for a clean shutdown...')
            await self.flush(True)
            self.db.close()
            self.executor.shutdown(wait=True)

    def force_chain_reorg(self, count):
        """Force a reorg of the given number of blocks.

        Returns True if a reorg is queued, false if not caught up.
        """
        if self._caught_up_event.is_set():
            self.reorg_count = count
            self.blocks_event.set()
            return True
        return False


class Timer:
    def __init__(self, name):
        self.name = name
        self.total = 0
        self.count = 0
        self.sub_timers = {}
        self._last_start = None

    def add_timer(self, name):
        if name not in self.sub_timers:
            self.sub_timers[name] = Timer(name)
        return self.sub_timers[name]

    def run(self, func, *args, forward_timer=False, timer_name=None, **kwargs):
        t = self.add_timer(timer_name or func.__name__)
        t.start()
        try:
            if forward_timer:
                return func(*args, **kwargs, timer=t)
            else:
                return func(*args, **kwargs)
        finally:
            t.stop()

    def start(self):
        self._last_start = time.time()
        return self

    def stop(self):
        self.total += (time.time() - self._last_start)
        self.count += 1
        self._last_start = None
        return self

    def show(self, depth=0, height=None):
        if depth == 0:
            print('='*100)
            if height is not None:
                print(f'STATISTICS AT HEIGHT {height}')
                print('='*100)
        else:
            print(
                f"{'  '*depth} {self.total/60:4.2f}mins {self.name}"
                # f"{self.total/self.count:.5f}sec/call, "
            )
        for sub_timer in self.sub_timers.values():
            sub_timer.show(depth+1)
        if depth == 0:
            print('='*100)
