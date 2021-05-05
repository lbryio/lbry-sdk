import time
import asyncio
import typing
from bisect import bisect_right
from struct import pack, unpack
from concurrent.futures.thread import ThreadPoolExecutor
from typing import Optional, List, Tuple
from prometheus_client import Gauge, Histogram
from collections import defaultdict
import lbry
from lbry.schema.claim import Claim
from lbry.wallet.transaction import OutputScript, Output
from lbry.wallet.server.tx import Tx
from lbry.wallet.server.daemon import DaemonError
from lbry.wallet.server.hash import hash_to_hex_str, HASHX_LEN
from lbry.wallet.server.util import chunks, class_logger
from lbry.crypto.hash import hash160
from lbry.wallet.server.leveldb import FlushData
from lbry.wallet.server.db import DB_PREFIXES
from lbry.wallet.server.db.claimtrie import StagedClaimtrieItem, StagedClaimtrieSupport, get_expiration_height
from lbry.wallet.server.db.claimtrie import get_takeover_name_ops, get_force_activate_ops, get_delay_for_name
from lbry.wallet.server.db.prefixes import PendingClaimActivationPrefixRow, Prefixes
from lbry.wallet.server.db.revertable import RevertablePut
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
        self.effective_amount_changes = defaultdict(list)
        self.pending_claims: typing.Dict[Tuple[int, int], StagedClaimtrieItem] = {}
        self.pending_claim_txos: typing.Dict[bytes, Tuple[int, int]] = {}
        self.pending_supports = defaultdict(set)
        self.pending_support_txos = {}
        self.pending_abandon = set()
        self.staged_pending_abandoned = {}

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

    def check_cache_size(self):
        """Flush a cache if it gets too big."""
        # Good average estimates based on traversal of subobjects and
        # requesting size from Python (see deep_getsizeof).
        one_MB = 1000*1000
        utxo_cache_size = len(self.utxo_cache) * 205
        db_deletes_size = len(self.db_deletes) * 57
        hist_cache_size = len(self.db.hist_unflushed) * 180 + self.db.hist_unflushed_count * 4
        # Roughly ntxs * 32 + nblocks * 42
        tx_hash_size = ((self.tx_count - self.db.fs_tx_count) * 32
                        + (self.height - self.db.fs_height) * 42)
        utxo_MB = (db_deletes_size + utxo_cache_size) // one_MB
        hist_MB = (hist_cache_size + tx_hash_size) // one_MB

        self.logger.info('our height: {:,d} daemon: {:,d} '
                         'UTXOs {:,d}MB hist {:,d}MB'
                         .format(self.height, self.daemon.cached_height(),
                                 utxo_MB, hist_MB))

        # Flush history if it takes up over 20% of cache memory.
        # Flush UTXOs once they take up 80% of cache memory.
        cache_MB = self.env.cache_MB
        if utxo_MB + hist_MB >= cache_MB or hist_MB >= cache_MB // 5:
            return utxo_MB >= cache_MB * 4 // 5
        return None

    def _add_claim_or_update(self, height: int, txo, script, tx_hash: bytes, idx: int, tx_count: int, txout,
                             spent_claims: typing.Dict[bytes, typing.Tuple[int, int, str]],
                             zero_delay_claims: typing.Dict[Tuple[str, bytes], Tuple[int, int]]) -> List['RevertableOp']:
        try:
            claim_name = txo.normalized_name
        except UnicodeDecodeError:
            claim_name = ''.join(chr(c) for c in txo.script.values['claim_name'])
        if script.is_claim_name:
            claim_hash = hash160(tx_hash + pack('>I', idx))[::-1]
            # print(f"\tnew lbry://{claim_name}#{claim_hash.hex()} ({tx_count} {txout.value})")
        else:
            claim_hash = txo.claim_hash[::-1]

        signing_channel_hash = None
        channel_claims_count = 0
        activation_delay = self.db.get_activation_delay(claim_hash, claim_name)
        if activation_delay == 0:
            zero_delay_claims[(claim_name, claim_hash)] = tx_count, idx
        # else:
        #     print("delay activation ", claim_name, activation_delay, height)

        activation_height = activation_delay + height
        try:
            signable = txo.signable
        except:  # google.protobuf.message.DecodeError: Could not parse JSON.
            signable = None

        if signable and signable.signing_channel_hash:
            signing_channel_hash = txo.signable.signing_channel_hash[::-1]
            # if signing_channel_hash in self.pending_claim_txos:
            #     pending_channel = self.pending_claims[self.pending_claim_txos[signing_channel_hash]]
            #     channel_claims_count = pending_channel.

            channel_claims_count = self.db.get_claims_in_channel_count(signing_channel_hash) + 1
        if script.is_claim_name:
            support_amount = 0
            root_tx_num, root_idx = tx_count, idx
        else:
            if claim_hash not in spent_claims:
                print(f"\tthis is a wonky tx, contains unlinked claim update {claim_hash.hex()}")
                return []
            support_amount = self.db.get_support_amount(claim_hash)
            (prev_tx_num, prev_idx, _) = spent_claims.pop(claim_hash)
            # print(f"\tupdate lbry://{claim_name}#{claim_hash.hex()} {tx_hash[::-1].hex()} {txout.value}")

            if (prev_tx_num, prev_idx) in self.pending_claims:
                previous_claim = self.pending_claims.pop((prev_tx_num, prev_idx))
                root_tx_num = previous_claim.root_claim_tx_num
                root_idx = previous_claim.root_claim_tx_position
                # prev_amount = previous_claim.amount
            else:
                k, v = self.db.get_root_claim_txo_and_current_amount(
                    claim_hash
                )
                root_tx_num = v.root_tx_num
                root_idx = v.root_position
                prev_amount = v.amount

        pending = StagedClaimtrieItem(
            claim_name, claim_hash, txout.value, support_amount + txout.value,
            activation_height, get_expiration_height(height), tx_count, idx, root_tx_num, root_idx,
            signing_channel_hash, channel_claims_count
        )

        self.pending_claims[(tx_count, idx)] = pending
        self.pending_claim_txos[claim_hash] = (tx_count, idx)
        self.effective_amount_changes[claim_hash].append(txout.value)
        return pending.get_add_claim_utxo_ops()

    def _add_support(self, height, txo, txout, idx, tx_count,
                     zero_delay_claims: typing.Dict[Tuple[str, bytes], Tuple[int, int]]) -> List['RevertableOp']:
        supported_claim_hash = txo.claim_hash[::-1]

        claim_info = self.db.get_root_claim_txo_and_current_amount(
            supported_claim_hash
        )
        controlling_claim = None
        supported_tx_num = supported_position = supported_activation_height = supported_name = None
        if claim_info:
            k, v = claim_info
            supported_name = v.name
            supported_tx_num = k.tx_num
            supported_position = k.position
            supported_activation_height = v.activation
            controlling_claim = self.db.get_controlling_claim(v.name)

        if supported_claim_hash in self.effective_amount_changes:
            # print(f"\tsupport claim {supported_claim_hash.hex()} {txout.value}")
            self.effective_amount_changes[supported_claim_hash].append(txout.value)
            self.pending_supports[supported_claim_hash].add((tx_count, idx))
            self.pending_support_txos[(tx_count, idx)] = supported_claim_hash, txout.value
            return StagedClaimtrieSupport(
                supported_claim_hash, tx_count, idx, txout.value
            ).get_add_support_utxo_ops()
        elif supported_claim_hash not in self.pending_claims and supported_claim_hash not in self.pending_abandon:
            # print(f"\tsupport claim {supported_claim_hash.hex()} {txout.value}")
            ops = []
            if claim_info:
                starting_amount = self.db.get_effective_amount(supported_claim_hash)

                if supported_claim_hash not in self.effective_amount_changes:
                    self.effective_amount_changes[supported_claim_hash].append(starting_amount)
                self.effective_amount_changes[supported_claim_hash].append(txout.value)
                supported_amount = self._get_pending_effective_amount(supported_claim_hash)

                if controlling_claim and supported_claim_hash != controlling_claim.claim_hash:
                    if supported_amount + txo.amount > self._get_pending_effective_amount(controlling_claim.claim_hash):
                        # takeover could happen
                        if (supported_name, supported_claim_hash) not in zero_delay_claims:
                            takeover_delay = get_delay_for_name(height - supported_activation_height)
                            if takeover_delay == 0:
                                zero_delay_claims[(supported_name, supported_claim_hash)] = (
                                    supported_tx_num, supported_position
                                )
                            else:
                                ops.append(
                                    RevertablePut(
                                        *Prefixes.pending_activation.pack_item(
                                            height + takeover_delay, supported_tx_num, supported_position,
                                            supported_claim_hash, supported_name
                                        )
                                    )
                                )

                self.pending_supports[supported_claim_hash].add((tx_count, idx))
                self.pending_support_txos[(tx_count, idx)] = supported_claim_hash, txout.value
                # print(f"\tsupport claim {supported_claim_hash.hex()} {starting_amount}+{txout.value}={starting_amount + txout.value}")
                ops.extend(StagedClaimtrieSupport(
                    supported_claim_hash, tx_count, idx, txout.value
                ).get_add_support_utxo_ops())
                return ops
            else:
                print(f"\tthis is a wonky tx, contains unlinked support for non existent {supported_claim_hash.hex()}")
        return []

    def _add_claim_or_support(self, height: int, tx_hash: bytes, tx_count: int, idx: int, txo, txout, script,
                              spent_claims: typing.Dict[bytes, Tuple[int, int, str]],
                              zero_delay_claims: typing.Dict[Tuple[str, bytes], Tuple[int, int]]) -> List['RevertableOp']:
        if script.is_claim_name or script.is_update_claim:
            return self._add_claim_or_update(height, txo, script, tx_hash, idx, tx_count, txout, spent_claims,
                                             zero_delay_claims)
        elif script.is_support_claim or script.is_support_claim_data:
            return self._add_support(height, txo, txout, idx, tx_count, zero_delay_claims)
        return []

    def _remove_support(self, txin, zero_delay_claims):
        txin_num = self.db.transaction_num_mapping[txin.prev_hash]
        supported_name = None
        if (txin_num, txin.prev_idx) in self.pending_support_txos:
            spent_support, support_amount = self.pending_support_txos.pop((txin_num, txin.prev_idx))
            supported_name = self._get_pending_claim_name(spent_support)
            self.pending_supports[spent_support].remove((txin_num, txin.prev_idx))
        else:
            spent_support, support_amount = self.db.get_supported_claim_from_txo(txin_num, txin.prev_idx)
            if spent_support:
                supported_name = self._get_pending_claim_name(spent_support)

        if spent_support and support_amount is not None and spent_support not in self.pending_abandon:
            controlling = self.db.get_controlling_claim(supported_name)
            if controlling:
                bid_queue = {
                    claim_hash: self._get_pending_effective_amount(claim_hash)
                    for claim_hash in self.db.get_claims_for_name(supported_name)
                    if claim_hash not in self.pending_abandon
                }
                bid_queue[spent_support] -= support_amount
                sorted_claims = sorted(
                    list(bid_queue.keys()), key=lambda claim_hash: bid_queue[claim_hash], reverse=True
                )
                if controlling.claim_hash == spent_support and sorted_claims.index(controlling.claim_hash) > 0:
                    print("takeover due to abandoned support")

            # print(f"\tspent support for {spent_support.hex()} -{support_amount} ({txin_num}, {txin.prev_idx}) {supported_name}")
            if spent_support not in self.effective_amount_changes:
                assert spent_support not in self.pending_claims
                prev_effective_amount = self.db.get_effective_amount(spent_support)
                self.effective_amount_changes[spent_support].append(prev_effective_amount)
            self.effective_amount_changes[spent_support].append(-support_amount)
            return StagedClaimtrieSupport(
                spent_support, txin_num, txin.prev_idx, support_amount
            ).get_spend_support_txo_ops()
        return []

    def _remove_claim(self, txin, spent_claims, zero_delay_claims):
        txin_num = self.db.transaction_num_mapping[txin.prev_hash]
        if (txin_num, txin.prev_idx) in self.pending_claims:
            spent = self.pending_claims[(txin_num, txin.prev_idx)]
            name = spent.name
            spent_claims[spent.claim_hash] = (txin_num, txin.prev_idx, name)
            # print(f"spend lbry://{name}#{spent.claim_hash.hex()}")
        else:
            spent_claim_hash_and_name = self.db.claim_hash_and_name_from_txo(
                txin_num, txin.prev_idx
            )
            if not spent_claim_hash_and_name:  # txo is not a claim
                return []
            prev_claim_hash = spent_claim_hash_and_name.claim_hash

            prev_signing_hash = self.db.get_channel_for_claim(prev_claim_hash)
            prev_claims_in_channel_count = None
            if prev_signing_hash:
                prev_claims_in_channel_count = self.db.get_claims_in_channel_count(
                    prev_signing_hash
                )
            prev_effective_amount = self.db.get_effective_amount(
                prev_claim_hash
            )
            k, v = self.db.get_root_claim_txo_and_current_amount(prev_claim_hash)
            claim_root_tx_num = v.root_tx_num
            claim_root_idx = v.root_position
            prev_amount = v.amount
            name = v.name
            tx_num = k.tx_num
            position = k.position
            activation_height = v.activation
            height = bisect_right(self.db.tx_counts, tx_num)
            spent = StagedClaimtrieItem(
                name, prev_claim_hash, prev_amount, prev_effective_amount,
                activation_height, get_expiration_height(height), txin_num, txin.prev_idx, claim_root_tx_num,
                claim_root_idx, prev_signing_hash, prev_claims_in_channel_count
            )
            spent_claims[prev_claim_hash] = (txin_num, txin.prev_idx, name)
            # print(f"spend lbry://{spent_claims[prev_claim_hash][2]}#{prev_claim_hash.hex()}")
        if spent.claim_hash not in self.effective_amount_changes:
            self.effective_amount_changes[spent.claim_hash].append(spent.effective_amount)
        self.effective_amount_changes[spent.claim_hash].append(-spent.amount)
        if (name, spent.claim_hash) in zero_delay_claims:
            zero_delay_claims.pop((name, spent.claim_hash))
        return spent.get_spend_claim_txo_ops()

    def _remove_claim_or_support(self, txin, spent_claims, zero_delay_claims):
        spend_claim_ops = self._remove_claim(txin, spent_claims, zero_delay_claims)
        if spend_claim_ops:
            return spend_claim_ops
        return self._remove_support(txin, zero_delay_claims)

    def _abandon(self, spent_claims) -> typing.Tuple[List['RevertableOp'], typing.Set[str]]:
        # Handle abandoned claims
        ops = []

        controlling_claims = {}
        need_takeover = set()

        for abandoned_claim_hash, (prev_tx_num, prev_idx, name) in spent_claims.items():
            # print(f"\tabandon lbry://{name}#{abandoned_claim_hash.hex()} {prev_tx_num} {prev_idx}")

            if (prev_tx_num, prev_idx) in self.pending_claims:
                pending = self.pending_claims.pop((prev_tx_num, prev_idx))
                self.staged_pending_abandoned[pending.claim_hash] = pending
                claim_root_tx_num = pending.root_claim_tx_num
                claim_root_idx = pending.root_claim_tx_position
                prev_amount = pending.amount
                prev_signing_hash = pending.signing_hash
                prev_effective_amount = pending.effective_amount
                prev_claims_in_channel_count = pending.claims_in_channel_count
            else:
                k, v = self.db.get_root_claim_txo_and_current_amount(
                    abandoned_claim_hash
                )
                claim_root_tx_num = v.root_tx_num
                claim_root_idx = v.root_position
                prev_amount = v.amount
                prev_signing_hash = self.db.get_channel_for_claim(abandoned_claim_hash)
                prev_claims_in_channel_count = None
                if prev_signing_hash:
                    prev_claims_in_channel_count = self.db.get_claims_in_channel_count(
                        prev_signing_hash
                    )
                prev_effective_amount = self.db.get_effective_amount(
                    abandoned_claim_hash
                )

            if name not in controlling_claims:
                controlling_claims[name] = self.db.get_controlling_claim(name)
            controlling = controlling_claims[name]
            if controlling and controlling.claim_hash == abandoned_claim_hash:
                need_takeover.add(name)
                # print("needs takeover")

            for (support_tx_num, support_tx_idx) in self.pending_supports[abandoned_claim_hash]:
                _, support_amount = self.pending_support_txos.pop((support_tx_num, support_tx_idx))
                ops.extend(
                    StagedClaimtrieSupport(
                        abandoned_claim_hash, support_tx_num, support_tx_idx, support_amount
                    ).get_spend_support_txo_ops()
                )
                # print(f"\tremove pending support for abandoned lbry://{name}#{abandoned_claim_hash.hex()} {support_tx_num} {support_tx_idx}")
            self.pending_supports[abandoned_claim_hash].clear()
            self.pending_supports.pop(abandoned_claim_hash)

            for (support_tx_num, support_tx_idx, support_amount) in self.db.get_supports(abandoned_claim_hash):
                ops.extend(
                    StagedClaimtrieSupport(
                        abandoned_claim_hash, support_tx_num, support_tx_idx, support_amount
                    ).get_spend_support_txo_ops()
                )
                # print(f"\tremove support for abandoned lbry://{name}#{abandoned_claim_hash.hex()} {support_tx_num} {support_tx_idx}")

            height = bisect_right(self.db.tx_counts, prev_tx_num)
            activation_height = 0

            if abandoned_claim_hash in self.effective_amount_changes:
                # print("pop")
                self.effective_amount_changes.pop(abandoned_claim_hash)
            self.pending_abandon.add(abandoned_claim_hash)

            # print(f"\tabandoned lbry://{name}#{abandoned_claim_hash.hex()}, {len(need_takeover)} names need takeovers")
            ops.extend(
                StagedClaimtrieItem(
                    name, abandoned_claim_hash, prev_amount, prev_effective_amount,
                    activation_height, get_expiration_height(height), prev_tx_num, prev_idx, claim_root_tx_num,
                    claim_root_idx, prev_signing_hash, prev_claims_in_channel_count
                ).get_abandon_ops(self.db.db)
            )
        return ops, need_takeover

    def _expire_claims(self, height: int, zero_delay_claims):
        expired = self.db.get_expired_by_height(height)
        spent_claims = {}
        ops = []
        names_needing_takeover = set()
        for expired_claim_hash, (tx_num, position, name, txi) in expired.items():
            if (tx_num, position) not in self.pending_claims:
                ops.extend(self._remove_claim(txi, spent_claims, zero_delay_claims))
        if expired:
            # do this to follow the same content claim removing pathway as if a claim (possible channel) was abandoned
            abandon_ops, _names_needing_takeover = self._abandon(spent_claims)
            if abandon_ops:
                ops.extend(abandon_ops)
                names_needing_takeover.update(_names_needing_takeover)
            ops.extend(self._abandon(spent_claims))
        return ops, names_needing_takeover

    def _get_pending_claim_amount(self, claim_hash: bytes) -> int:
        if claim_hash in self.pending_claim_txos:
            return self.pending_claims[self.pending_claim_txos[claim_hash]].amount
        return self.db.get_claim_amount(claim_hash)

    def _get_pending_claim_name(self, claim_hash: bytes) -> str:
        assert claim_hash is not None
        if claim_hash in self.pending_claims:
            return self.pending_claims[claim_hash].name
        claim = self.db.get_claim_from_txo(claim_hash)
        return claim.name

    def _get_pending_effective_amount(self, claim_hash: bytes) -> int:
        claim_amount = self._get_pending_claim_amount(claim_hash) or 0
        support_amount = self.db.get_support_amount(claim_hash) or 0
        return claim_amount + support_amount + sum(
            self.pending_support_txos[support_txnum, support_n][1]
            for (support_txnum, support_n) in self.pending_supports.get(claim_hash, [])
        )  # TODO: subtract pending spend supports

    def _get_name_takeover_ops(self, height: int, name: str,
                               activated_claims: typing.Set[bytes]) -> List['RevertableOp']:
        controlling = self.db.get_controlling_claim(name)
        if not controlling or controlling.claim_hash in self.pending_abandon:
            # print("no controlling claim for ", name)
            bid_queue = {
                claim_hash: self._get_pending_effective_amount(claim_hash) for claim_hash in activated_claims
            }
            winning_claim = max(bid_queue, key=lambda k: bid_queue[k])
            if winning_claim in self.pending_claim_txos:
                s = self.pending_claims[self.pending_claim_txos[winning_claim]]
            else:
                s = self.db.make_staged_claim_item(winning_claim)
            ops = []
            if s.activation_height > height:
                ops.extend(get_force_activate_ops(
                    name, s.tx_num, s.position, s.claim_hash, s.root_claim_tx_num, s.root_claim_tx_position,
                    s.amount, s.effective_amount, s.activation_height, height
                ))
            ops.extend(get_takeover_name_ops(name, winning_claim, height))
            return ops
        else:
            # print(f"current controlling claim for {name}#{controlling.claim_hash.hex()}")
            controlling_effective_amount = self._get_pending_effective_amount(controlling.claim_hash)
            bid_queue = {
                claim_hash: self._get_pending_effective_amount(claim_hash) for claim_hash in activated_claims
            }
            highest_newly_activated = max(bid_queue, key=lambda k: bid_queue[k])
            if bid_queue[highest_newly_activated] > controlling_effective_amount:
                # print(f"takeover controlling claim for {name}#{controlling.claim_hash.hex()}")
                return get_takeover_name_ops(name, highest_newly_activated, height, controlling)
            print(bid_queue[highest_newly_activated], controlling_effective_amount)
            # print("no takeover")
            return []

    def _get_takeover_ops(self, height: int, zero_delay_claims) -> List['RevertableOp']:
        ops = []
        pending = defaultdict(set)

        # get non delayed takeovers for new names
        for (name, claim_hash) in zero_delay_claims:
            if claim_hash not in self.pending_abandon:
                pending[name].add(claim_hash)
                # print("zero delay activate", name, claim_hash.hex())

        # get takeovers from claims activated at this block
        for activated in self.db.get_activated_claims_at_height(height):
            if activated.claim_hash not in self.pending_abandon:
                pending[activated.name].add(activated.claim_hash)
                # print("delayed activate")

        # get takeovers from supports for controlling claims being abandoned
        for abandoned_claim_hash in self.pending_abandon:
            if abandoned_claim_hash in self.staged_pending_abandoned:
                abandoned = self.staged_pending_abandoned[abandoned_claim_hash]
                controlling = self.db.get_controlling_claim(abandoned.name)
                if controlling and controlling.claim_hash == abandoned_claim_hash and abandoned.name not in pending:
                    pending[abandoned.name].update(self.db.get_claims_for_name(abandoned.name))
            else:
                k, v = self.db.get_root_claim_txo_and_current_amount(abandoned_claim_hash)
                controlling_claim = self.db.get_controlling_claim(v.name)
                if controlling_claim and abandoned_claim_hash == controlling_claim.claim_hash and v.name not in pending:
                    pending[v.name].update(self.db.get_claims_for_name(v.name))
                    # print("check abandoned winning")



        # get takeovers from controlling claims being abandoned

        for name, activated_claims in pending.items():
            ops.extend(self._get_name_takeover_ops(height, name, activated_claims))
        return ops

    def advance_block(self, block):
        # print("advance ", height)
        height = self.height + 1
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

        zero_delay_claims: typing.Dict[Tuple[str, bytes], Tuple[int, int]] = {}
        abandoned_or_expired_controlling = set()

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

                spend_claim_or_support_ops = self._remove_claim_or_support(txin, spent_claims, zero_delay_claims)
                if spend_claim_or_support_ops:
                    claimtrie_stash_extend(spend_claim_or_support_ops)

            # Add the new UTXOs
            for idx, txout in enumerate(tx.outputs):
                # Get the hashX.  Ignore unspendable outputs
                hashX = hashX_from_script(txout.pk_script)
                if hashX:
                    append_hashX(hashX)
                    put_utxo(tx_hash + pack('<H', idx), hashX + tx_numb + pack('<Q', txout.value))

                # add claim/support txo
                script = OutputScript(txout.pk_script)
                script.parse()
                txo = Output(txout.value, script)

                claim_or_support_ops = self._add_claim_or_support(
                    height, tx_hash, tx_count, idx, txo, txout, script, spent_claims, zero_delay_claims
                )
                if claim_or_support_ops:
                    claimtrie_stash_extend(claim_or_support_ops)

            # Handle abandoned claims
            abandon_ops, abandoned_controlling_need_takeover = self._abandon(spent_claims)
            if abandon_ops:
                claimtrie_stash_extend(abandon_ops)
                abandoned_or_expired_controlling.update(abandoned_controlling_need_takeover)

            append_hashX_by_tx(hashXs)
            update_touched(hashXs)
            self.db.total_transactions.append(tx_hash)
            self.db.transaction_num_mapping[tx_hash] = tx_count
            tx_count += 1

        # handle expired claims
        expired_ops, expired_need_takeover = self._expire_claims(height, zero_delay_claims)
        if expired_ops:
            # print(f"************\nexpire claims at block {height}\n************")
            abandoned_or_expired_controlling.update(expired_need_takeover)
            claimtrie_stash_extend(expired_ops)

        # activate claims and process takeovers
        takeover_ops = self._get_takeover_ops(height, zero_delay_claims)
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

        for touched_claim_hash, amount_changes in self.effective_amount_changes.items():
            new_effective_amount = sum(amount_changes)
            assert new_effective_amount >= 0, f'{new_effective_amount}, {touched_claim_hash.hex()}'
            claimtrie_stash.extend(
                self.db.get_update_effective_amount_ops(touched_claim_hash, new_effective_amount)
            )

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

        self.effective_amount_changes.clear()

        self.pending_claims.clear()
        self.pending_claim_txos.clear()
        self.pending_supports.clear()
        self.pending_support_txos.clear()
        self.pending_abandon.clear()
        self.staged_pending_abandoned.clear()

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
