import time
import asyncio
import typing
import struct
from bisect import bisect_right
from struct import pack, unpack
from concurrent.futures.thread import ThreadPoolExecutor
from typing import Optional, List, Tuple, Set, DefaultDict, Dict
from prometheus_client import Gauge, Histogram
from collections import defaultdict
import array
import lbry
from lbry.schema.claim import Claim
from lbry.schema.mime_types import guess_stream_type
from lbry.wallet.ledger import Ledger, TestNetLedger, RegTestLedger
from lbry.wallet.constants import TXO_TYPES
from lbry.wallet.server.db.common import STREAM_TYPES, CLAIM_TYPES

from lbry.wallet.transaction import OutputScript, Output, Transaction
from lbry.wallet.server.tx import Tx, TxOutput, TxInput
from lbry.wallet.server.daemon import DaemonError
from lbry.wallet.server.hash import hash_to_hex_str, HASHX_LEN
from lbry.wallet.server.util import chunks, class_logger
from lbry.crypto.hash import hash160
from lbry.wallet.server.leveldb import FlushData
from lbry.wallet.server.mempool import MemPool
from lbry.wallet.server.db import DB_PREFIXES
from lbry.wallet.server.db.claimtrie import StagedClaimtrieItem, StagedClaimtrieSupport
from lbry.wallet.server.db.claimtrie import get_takeover_name_ops, StagedActivation, get_add_effective_amount_ops
from lbry.wallet.server.db.claimtrie import get_remove_name_ops, get_remove_effective_amount_ops
from lbry.wallet.server.db.prefixes import ACTIVATED_SUPPORT_TXO_TYPE, ACTIVATED_CLAIM_TXO_TYPE
from lbry.wallet.server.db.prefixes import PendingActivationKey, PendingActivationValue, Prefixes, ClaimToTXOValue
from lbry.wallet.server.udp import StatusServer
from lbry.wallet.server.db.revertable import RevertableOp, RevertablePut, RevertableDelete, RevertableOpStack
if typing.TYPE_CHECKING:
    from lbry.wallet.server.leveldb import LevelDB


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

    def __init__(self, env, db: 'LevelDB', daemon, shutdown_event: asyncio.Event):
        self.state_lock = asyncio.Lock()
        self.env = env
        self.db = db
        self.daemon = daemon
        self.mempool = MemPool(env.coin, daemon, db, self.state_lock)
        self.shutdown_event = shutdown_event
        self.coin = env.coin
        if env.coin.NET == 'mainnet':
            self.ledger = Ledger
        elif env.coin.NET == 'testnet':
            self.ledger = TestNetLedger
        else:
            self.ledger = RegTestLedger

        self._caught_up_event: Optional[asyncio.Event] = None
        self.height = 0
        self.tip = bytes.fromhex(self.coin.GENESIS_HASH)[::-1]
        self.tx_count = 0

        self.blocks_event = asyncio.Event()
        self.prefetcher = Prefetcher(daemon, env.coin, self.blocks_event)
        self.logger = class_logger(__name__, self.__class__.__name__)
        self.executor = ThreadPoolExecutor(1)

        # Meta
        self.touched_hashXs: Set[bytes] = set()

        # UTXO cache
        self.utxo_cache: Dict[Tuple[bytes, int], Tuple[bytes, int]] = {}

        # Claimtrie cache
        self.db_op_stack: Optional[RevertableOpStack] = None

        # self.search_cache = {}
        self.history_cache = {}
        self.status_server = StatusServer()

        #################################
        # attributes used for calculating stake activations and takeovers per block
        #################################

        # txo to pending claim
        self.txo_to_claim: Dict[Tuple[int, int], StagedClaimtrieItem] = {}
        # claim hash to pending claim txo
        self.claim_hash_to_txo: Dict[bytes, Tuple[int, int]] = {}
        # claim hash to lists of pending support txos
        self.support_txos_by_claim: DefaultDict[bytes, List[Tuple[int, int]]] = defaultdict(list)
        # support txo: (supported claim hash, support amount)
        self.support_txo_to_claim: Dict[Tuple[int, int], Tuple[bytes, int]] = {}
        # removed supports {name: {claim_hash: [(tx_num, nout), ...]}}
        self.removed_support_txos_by_name_by_claim: DefaultDict[str, DefaultDict[bytes, List[Tuple[int, int]]]] = \
            defaultdict(lambda: defaultdict(list))
        self.abandoned_claims: Dict[bytes, StagedClaimtrieItem] = {}
        # removed activated support amounts by claim hash
        self.removed_active_support_amount_by_claim: DefaultDict[bytes, List[int]] = defaultdict(list)
        # pending activated support amounts by claim hash
        self.activated_support_amount_by_claim: DefaultDict[bytes, List[int]] = defaultdict(list)
        # pending activated name and claim hash to claim/update txo amount
        self.activated_claim_amount_by_name_and_hash: Dict[Tuple[str, bytes], int] = {}
        # pending claim and support activations per claim hash per name,
        # used to process takeovers due to added activations
        activation_by_claim_by_name_type = DefaultDict[str, DefaultDict[bytes, List[Tuple[PendingActivationKey, int]]]]
        self.activation_by_claim_by_name: activation_by_claim_by_name_type = defaultdict(lambda: defaultdict(list))
        # these are used for detecting early takeovers by not yet activated claims/supports
        self.possible_future_support_amounts_by_claim_hash: DefaultDict[bytes, List[int]] = defaultdict(list)
        self.possible_future_claim_amount_by_name_and_hash: Dict[Tuple[str, bytes], int] = {}
        self.possible_future_support_txos_by_claim_hash: DefaultDict[bytes, List[Tuple[int, int]]] = defaultdict(list)

        self.removed_claims_to_send_es = set()  # cumulative changes across blocks to send ES
        self.touched_claims_to_send_es = set()

        self.removed_claim_hashes: Set[bytes] = set()  # per block changes
        self.touched_claim_hashes: Set[bytes] = set()

        self.signatures_changed = set()

        self.pending_reposted = set()
        self.pending_channel_counts = defaultdict(lambda: 0)

        self.pending_channels = {}
        self.amount_cache = {}
        self.expired_claim_hashes: Set[bytes] = set()

        self.doesnt_have_valid_signature: Set[bytes] = set()
        self.claim_channels: Dict[bytes, bytes] = {}
        self.hashXs_by_tx: DefaultDict[bytes, List[int]] = defaultdict(list)

    def claim_producer(self):
        if self.db.db_height <= 1:
            return

        for claim_hash in self.removed_claims_to_send_es:
            yield 'delete', claim_hash.hex()
        for claim in self.db.claims_producer(self.touched_claims_to_send_es):
            yield 'update', claim

    async def run_in_thread_with_lock(self, func, *args):
        # Run in a thread to prevent blocking.  Shielded so that
        # cancellations from shutdown don't lose work - when the task
        # completes the data will be flushed and then we shut down.
        # Take the state lock to be certain in-memory state is
        # consistent and not being updated elsewhere.
        async def run_in_thread_locked():
            async with self.state_lock:
                return await asyncio.get_event_loop().run_in_executor(None, func, *args)
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
            total_start = time.perf_counter()
            try:
                for block in blocks:
                    start = time.perf_counter()
                    await self.advance_block(block)
                    await self.flush()
                    self.logger.info("advanced to %i in %0.3fs", self.height, time.perf_counter() - start)
                    # TODO: we shouldnt wait on the search index updating before advancing to the next block
                if not self.db.first_sync:
                    await self.db.search_index.claim_consumer(self.claim_producer())
                self.db.search_index.clear_caches()
                self.touched_claims_to_send_es.clear()
                self.removed_claims_to_send_es.clear()
                # print("******************\n")
            except:
                self.logger.exception("advance blocks failed")
                raise
            processed_time = time.perf_counter() - total_start
            self.block_count_metric.set(self.height)
            self.block_update_time_metric.observe(processed_time)
            self.status_server.set_height(self.db.fs_height, self.db.db_tip)
            if not self.db.first_sync:
                s = '' if len(blocks) == 1 else 's'
                self.logger.info('processed {:,d} block{} in {:.1f}s'.format(len(blocks), s, processed_time))
            if self._caught_up_event.is_set():
                await self.mempool.on_block(self.touched_hashXs, self.height)
            self.touched_hashXs.clear()
        elif hprevs[0] != chain[0]:
            min_start_height = max(self.height - self.coin.REORG_LIMIT, 0)
            count = 1
            block_hashes_from_lbrycrd = await self.daemon.block_hex_hashes(
                min_start_height, self.coin.REORG_LIMIT
            )
            for height, block_hash in zip(
                    reversed(range(min_start_height, min_start_height + self.coin.REORG_LIMIT)),
                    reversed(block_hashes_from_lbrycrd)):
                if self.db.get_block_hash(height)[::-1].hex() == block_hash:
                    break
                count += 1
            self.logger.warning(f"blockchain reorg detected at {self.height}, unwinding last {count} blocks")
            try:
                assert count > 0, count
                for _ in range(count):
                    await self.backup_block()
                    await self.flush()
                    self.logger.info(f'backed up to height {self.height:,d}')

                await self.db._read_claim_txos()

                for touched in self.touched_claims_to_send_es:
                    if not self.db.get_claim_txo(touched):
                        self.removed_claims_to_send_es.add(touched)
                self.touched_claims_to_send_es.difference_update(self.removed_claims_to_send_es)
                await self.db.search_index.claim_consumer(self.claim_producer())
                self.db.search_index.clear_caches()
                self.touched_claims_to_send_es.clear()
                self.removed_claims_to_send_es.clear()
                await self.prefetcher.reset_height(self.height)
                self.reorg_count_metric.inc()
            except:
                self.logger.exception("reorg blocks failed")
                raise
            finally:
                self.logger.info("backed up to block %i", self.height)
        else:
            # It is probably possible but extremely rare that what
            # bitcoind returns doesn't form a chain because it
            # reorg-ed the chain as it was processing the batched
            # block hash requests.  Should this happen it's simplest
            # just to reset the prefetcher and try again.
            self.logger.warning('daemon blocks do not form a chain; '
                                'resetting the prefetcher')
            await self.prefetcher.reset_height(self.height)

    # - Flushing
    def flush_data(self):
        """The data for a flush.  The lock must be taken."""
        assert self.state_lock.locked()
        return FlushData(self.height, self.tx_count, self.db_op_stack, self.tip)

    async def flush(self):
        def flush():
            self.db.flush_dbs(self.flush_data())
            self.clear_after_advance_or_reorg()
        await self.run_in_thread_with_lock(flush)

    async def write_state(self):
        def flush():
            with self.db.db.write_batch() as batch:
                self.db.write_db_state(batch)

        await self.run_in_thread_with_lock(flush)

    def _add_claim_or_update(self, height: int, txo: 'Output', tx_hash: bytes, tx_num: int, nout: int,
                             spent_claims: typing.Dict[bytes, typing.Tuple[int, int, str]]):
        try:
            claim_name = txo.normalized_name
        except UnicodeDecodeError:
            claim_name = ''.join(chr(c) for c in txo.script.values['claim_name'])
        if txo.script.is_claim_name:
            claim_hash = hash160(tx_hash + pack('>I', nout))[::-1]
            # print(f"\tnew {claim_hash.hex()} ({tx_num} {txo.amount})")
        else:
            claim_hash = txo.claim_hash[::-1]
            # print(f"\tupdate {claim_hash.hex()} ({tx_num} {txo.amount})")

        signing_channel_hash = None
        channel_signature_is_valid = False
        try:
            signable = txo.signable
            is_repost = txo.claim.is_repost
            is_channel = txo.claim.is_channel
            if txo.claim.is_signed:
                signing_channel_hash = txo.signable.signing_channel_hash[::-1]
        except:  # google.protobuf.message.DecodeError: Could not parse JSON.
            signable = None
            is_repost = False
            is_channel = False

        reposted_claim_hash = None

        if is_repost:
            reposted_claim_hash = txo.claim.repost.reference.claim_hash[::-1]
            self.pending_reposted.add(reposted_claim_hash)

        if is_channel:
            self.pending_channels[claim_hash] = txo.claim.channel.public_key_bytes

        self.doesnt_have_valid_signature.add(claim_hash)
        raw_channel_tx = None
        if signable and signable.signing_channel_hash:
            signing_channel = self.db.get_claim_txo(signing_channel_hash)

            if signing_channel:
                raw_channel_tx = self.db.db.get(
                    DB_PREFIXES.tx.value + self.db.total_transactions[signing_channel.tx_num]
                )
            channel_pub_key_bytes = None
            try:
                if not signing_channel:
                    if txo.signable.signing_channel_hash[::-1] in self.pending_channels:
                        channel_pub_key_bytes = self.pending_channels[signing_channel_hash]
                elif raw_channel_tx:
                    chan_output = self.coin.transaction(raw_channel_tx).outputs[signing_channel.position]
                    chan_script = OutputScript(chan_output.pk_script)
                    chan_script.parse()
                    channel_meta = Claim.from_bytes(chan_script.values['claim'])

                    channel_pub_key_bytes = channel_meta.channel.public_key_bytes
                if channel_pub_key_bytes:
                    channel_signature_is_valid = Output.is_signature_valid(
                        txo.get_encoded_signature(), txo.get_signature_digest(self.ledger), channel_pub_key_bytes
                    )
                    if channel_signature_is_valid:
                        self.pending_channel_counts[signing_channel_hash] += 1
                        self.doesnt_have_valid_signature.remove(claim_hash)
                        self.claim_channels[claim_hash] = signing_channel_hash
            except:
                self.logger.exception(f"error validating channel signature for %s:%i", tx_hash[::-1].hex(), nout)

        if txo.script.is_claim_name:  # it's a root claim
            root_tx_num, root_idx = tx_num, nout
        else:  # it's a claim update
            if claim_hash not in spent_claims:
                # print(f"\tthis is a wonky tx, contains unlinked claim update {claim_hash.hex()}")
                return
            (prev_tx_num, prev_idx, _) = spent_claims.pop(claim_hash)
            # print(f"\tupdate {claim_hash.hex()} {tx_hash[::-1].hex()} {txo.amount}")
            if (prev_tx_num, prev_idx) in self.txo_to_claim:
                previous_claim = self.txo_to_claim.pop((prev_tx_num, prev_idx))
                root_tx_num, root_idx = previous_claim.root_tx_num, previous_claim.root_position
            else:
                previous_claim = self._make_pending_claim_txo(claim_hash)
                root_tx_num, root_idx = previous_claim.root_tx_num, previous_claim.root_position
                activation = self.db.get_activation(prev_tx_num, prev_idx)
                self.db_op_stack.extend_ops(
                    StagedActivation(
                        ACTIVATED_CLAIM_TXO_TYPE, claim_hash, prev_tx_num, prev_idx, activation, claim_name,
                        previous_claim.amount
                    ).get_remove_activate_ops()
                )

        self.db.claim_to_txo[claim_hash] = ClaimToTXOValue(
            tx_num, nout, root_tx_num, root_idx, txo.amount, channel_signature_is_valid, claim_name
        )
        self.db.txo_to_claim[(tx_num, nout)] = claim_hash

        pending = StagedClaimtrieItem(
            claim_name, claim_hash, txo.amount, self.coin.get_expiration_height(height), tx_num, nout, root_tx_num,
            root_idx, channel_signature_is_valid, signing_channel_hash, reposted_claim_hash
        )
        self.txo_to_claim[(tx_num, nout)] = pending
        self.claim_hash_to_txo[claim_hash] = (tx_num, nout)
        self.db_op_stack.extend_ops(pending.get_add_claim_utxo_ops())

    def _add_support(self, txo: 'Output', tx_num: int, nout: int):
        supported_claim_hash = txo.claim_hash[::-1]
        self.support_txos_by_claim[supported_claim_hash].append((tx_num, nout))
        self.support_txo_to_claim[(tx_num, nout)] = supported_claim_hash, txo.amount
        # print(f"\tsupport claim {supported_claim_hash.hex()} +{txo.amount}")
        self.db_op_stack.extend_ops(StagedClaimtrieSupport(
            supported_claim_hash, tx_num, nout, txo.amount
        ).get_add_support_utxo_ops())

    def _add_claim_or_support(self, height: int, tx_hash: bytes, tx_num: int, nout: int, txo: 'Output',
                              spent_claims: typing.Dict[bytes, Tuple[int, int, str]]):
        if txo.script.is_claim_name or txo.script.is_update_claim:
            self._add_claim_or_update(height, txo, tx_hash, tx_num, nout, spent_claims)
        elif txo.script.is_support_claim or txo.script.is_support_claim_data:
            self._add_support(txo, tx_num, nout)

    def _spend_support_txo(self, txin):
        txin_num = self.db.transaction_num_mapping[txin.prev_hash]
        if (txin_num, txin.prev_idx) in self.support_txo_to_claim:
            spent_support, support_amount = self.support_txo_to_claim.pop((txin_num, txin.prev_idx))
            self.support_txos_by_claim[spent_support].remove((txin_num, txin.prev_idx))
            supported_name = self._get_pending_claim_name(spent_support)
            # print(f"\tspent support for {spent_support.hex()}")
            self.removed_support_txos_by_name_by_claim[supported_name][spent_support].append((txin_num, txin.prev_idx))
            self.db_op_stack.extend_ops(StagedClaimtrieSupport(
                spent_support, txin_num, txin.prev_idx, support_amount
            ).get_spend_support_txo_ops())
        spent_support, support_amount = self.db.get_supported_claim_from_txo(txin_num, txin.prev_idx)
        if spent_support:
            supported_name = self._get_pending_claim_name(spent_support)
            if supported_name is not None:
                self.removed_support_txos_by_name_by_claim[supported_name][spent_support].append((txin_num, txin.prev_idx))
            activation = self.db.get_activation(txin_num, txin.prev_idx, is_support=True)
            if 0 < activation < self.height + 1:
                self.removed_active_support_amount_by_claim[spent_support].append(support_amount)
            # print(f"\tspent support for {spent_support.hex()} activation:{activation} {support_amount}")
            self.db_op_stack.extend_ops(StagedClaimtrieSupport(
                spent_support, txin_num, txin.prev_idx, support_amount
            ).get_spend_support_txo_ops())
            if supported_name is not None and activation > 0:
                self.db_op_stack.extend_ops(StagedActivation(
                    ACTIVATED_SUPPORT_TXO_TYPE, spent_support, txin_num, txin.prev_idx, activation, supported_name,
                    support_amount
                ).get_remove_activate_ops())

    def _spend_claim_txo(self, txin: TxInput, spent_claims: Dict[bytes, Tuple[int, int, str]]) -> bool:
        txin_num = self.db.transaction_num_mapping[txin.prev_hash]
        if (txin_num, txin.prev_idx) in self.txo_to_claim:
            spent = self.txo_to_claim[(txin_num, txin.prev_idx)]
        else:
            if (txin_num, txin.prev_idx) not in self.db.txo_to_claim:  # txo is not a claim
                return False
            spent_claim_hash_and_name = self.db.get_claim_from_txo(
                txin_num, txin.prev_idx
            )
            assert spent_claim_hash_and_name is not None
            spent = self._make_pending_claim_txo(spent_claim_hash_and_name.claim_hash)
        self.db.claim_to_txo.pop(self.db.txo_to_claim.pop((txin_num, txin.prev_idx)))
        if spent.reposted_claim_hash:
            self.pending_reposted.add(spent.reposted_claim_hash)
        if spent.signing_hash and spent.channel_signature_is_valid:
            self.pending_channel_counts[spent.signing_hash] -= 1
        spent_claims[spent.claim_hash] = (spent.tx_num, spent.position, spent.name)
        # print(f"\tspend lbry://{spent.name}#{spent.claim_hash.hex()}")
        self.db_op_stack.extend_ops(spent.get_spend_claim_txo_ops())
        return True

    def _spend_claim_or_support_txo(self, txin, spent_claims):
        if not self._spend_claim_txo(txin, spent_claims):
            self._spend_support_txo(txin)

    def _abandon_claim(self, claim_hash, tx_num, nout, name):
        if (tx_num, nout) in self.txo_to_claim:
            pending = self.txo_to_claim.pop((tx_num, nout))
            self.abandoned_claims[pending.claim_hash] = pending
            claim_root_tx_num, claim_root_idx = pending.root_tx_num, pending.root_position
            prev_amount, prev_signing_hash = pending.amount, pending.signing_hash
            reposted_claim_hash = pending.reposted_claim_hash
            expiration = self.coin.get_expiration_height(self.height)
            signature_is_valid = pending.channel_signature_is_valid
        else:
            v = self.db.get_claim_txo(
                claim_hash
            )
            claim_root_tx_num, claim_root_idx, prev_amount = v.root_tx_num,  v.root_position, v.amount
            signature_is_valid = v.channel_signature_is_valid
            prev_signing_hash = self.db.get_channel_for_claim(claim_hash, tx_num, nout)
            reposted_claim_hash = self.db.get_repost(claim_hash)
            expiration = self.coin.get_expiration_height(bisect_right(self.db.tx_counts, tx_num))
        self.abandoned_claims[claim_hash] = staged = StagedClaimtrieItem(
            name, claim_hash, prev_amount, expiration, tx_num, nout, claim_root_tx_num,
            claim_root_idx, signature_is_valid, prev_signing_hash, reposted_claim_hash
        )
        if prev_signing_hash and prev_signing_hash in self.pending_channel_counts:
            self.pending_channel_counts.pop(prev_signing_hash)

        for support_txo_to_clear in self.support_txos_by_claim[claim_hash]:
            self.support_txo_to_claim.pop(support_txo_to_clear)
        self.support_txos_by_claim[claim_hash].clear()
        self.support_txos_by_claim.pop(claim_hash)

        if name.startswith('@'):  # abandon a channel, invalidate signatures
            self._invalidate_channel_signatures(claim_hash)

    def _invalidate_channel_signatures(self, claim_hash: bytes):
        for k, signed_claim_hash in self.db.db.iterator(
                prefix=Prefixes.channel_to_claim.pack_partial_key(claim_hash)):
            if signed_claim_hash in self.abandoned_claims or signed_claim_hash in self.expired_claim_hashes:
                continue
            # there is no longer a signing channel for this claim as of this block
            if signed_claim_hash in self.doesnt_have_valid_signature:
                continue
            # the signing channel changed in this block
            if signed_claim_hash in self.claim_channels and signed_claim_hash != self.claim_channels[signed_claim_hash]:
                continue

            # if the claim with an invalidated signature is in this block, update the StagedClaimtrieItem
            # so that if we later try to spend it in this block we won't try to delete the channel info twice
            if signed_claim_hash in self.claim_hash_to_txo:
                signed_claim_txo = self.claim_hash_to_txo[signed_claim_hash]
                claim = self.txo_to_claim[signed_claim_txo]
                if claim.signing_hash != claim_hash:  # claim was already invalidated this block
                    continue
                self.txo_to_claim[signed_claim_txo] = claim.invalidate_signature()
            else:
                claim = self._make_pending_claim_txo(signed_claim_hash)
            self.signatures_changed.add(signed_claim_hash)
            self.pending_channel_counts[claim_hash] -= 1
            self.db_op_stack.extend_ops(claim.get_invalidate_signature_ops())

        for staged in list(self.txo_to_claim.values()):
            needs_invalidate = staged.claim_hash not in self.doesnt_have_valid_signature
            if staged.signing_hash == claim_hash and needs_invalidate:
                self.db_op_stack.extend_ops(staged.get_invalidate_signature_ops())
                self.txo_to_claim[self.claim_hash_to_txo[staged.claim_hash]] = staged.invalidate_signature()
                self.signatures_changed.add(staged.claim_hash)
                self.pending_channel_counts[claim_hash] -= 1

    def _make_pending_claim_txo(self, claim_hash: bytes):
        claim = self.db.get_claim_txo(claim_hash)
        if claim_hash in self.doesnt_have_valid_signature:
            signing_hash = None
        else:
            signing_hash = self.db.get_channel_for_claim(claim_hash, claim.tx_num, claim.position)
        reposted_claim_hash = self.db.get_repost(claim_hash)
        return StagedClaimtrieItem(
            claim.name, claim_hash, claim.amount,
            self.coin.get_expiration_height(bisect_right(self.db.tx_counts, claim.tx_num)),
            claim.tx_num, claim.position, claim.root_tx_num, claim.root_position,
            claim.channel_signature_is_valid, signing_hash, reposted_claim_hash
        )

    def _expire_claims(self, height: int):
        expired = self.db.get_expired_by_height(height)
        self.expired_claim_hashes.update(set(expired.keys()))
        spent_claims = {}
        for expired_claim_hash, (tx_num, position, name, txi) in expired.items():
            if (tx_num, position) not in self.txo_to_claim:
                self._spend_claim_txo(txi, spent_claims)
        if expired:
            # abandon the channels last to handle abandoned signed claims in the same tx,
            # see test_abandon_channel_and_claims_in_same_tx
            expired_channels = {}
            for abandoned_claim_hash, (tx_num, nout, name) in spent_claims.items():
                self._abandon_claim(abandoned_claim_hash, tx_num, nout, name)

                if name.startswith('@'):
                    expired_channels[abandoned_claim_hash] = (tx_num, nout, name)
                else:
                    # print(f"\texpire {abandoned_claim_hash.hex()} {tx_num} {nout}")
                    self._abandon_claim(abandoned_claim_hash, tx_num, nout, name)

            # do this to follow the same content claim removing pathway as if a claim (possible channel) was abandoned
            for abandoned_claim_hash, (tx_num, nout, name) in expired_channels.items():
                # print(f"\texpire {abandoned_claim_hash.hex()} {tx_num} {nout}")
                self._abandon_claim(abandoned_claim_hash, tx_num, nout, name)

    def _cached_get_active_amount(self, claim_hash: bytes, txo_type: int, height: int) -> int:
        if (claim_hash, txo_type, height) in self.amount_cache:
            return self.amount_cache[(claim_hash, txo_type, height)]
        self.amount_cache[(claim_hash, txo_type, height)] = amount = self.db._get_active_amount(
            claim_hash, txo_type, height
        )
        return amount

    def _cached_get_effective_amount(self, claim_hash: bytes, support_only=False) -> int:
        support_amount = self._cached_get_active_amount(claim_hash, ACTIVATED_SUPPORT_TXO_TYPE, self.db.db_height + 1)
        if support_only:
            return support_only
        return support_amount + self._cached_get_active_amount(
            claim_hash, ACTIVATED_CLAIM_TXO_TYPE, self.db.db_height + 1
        )

    def _get_pending_claim_amount(self, name: str, claim_hash: bytes, height=None) -> int:
        if (name, claim_hash) in self.activated_claim_amount_by_name_and_hash:
            return self.activated_claim_amount_by_name_and_hash[(name, claim_hash)]
        if (name, claim_hash) in self.possible_future_claim_amount_by_name_and_hash:
            return self.possible_future_claim_amount_by_name_and_hash[(name, claim_hash)]
        return self._cached_get_active_amount(claim_hash, ACTIVATED_CLAIM_TXO_TYPE, height or (self.height + 1))

    def _get_pending_claim_name(self, claim_hash: bytes) -> Optional[str]:
        assert claim_hash is not None
        if claim_hash in self.txo_to_claim:
            return self.txo_to_claim[claim_hash].name
        claim_info = self.db.get_claim_txo(claim_hash)
        if claim_info:
            return claim_info.name

    def _get_pending_supported_amount(self, claim_hash: bytes, height: Optional[int] = None) -> int:
        amount = self._cached_get_active_amount(claim_hash, ACTIVATED_SUPPORT_TXO_TYPE, height or (self.height + 1))
        if claim_hash in self.activated_support_amount_by_claim:
            amount += sum(self.activated_support_amount_by_claim[claim_hash])
        if claim_hash in self.possible_future_support_amounts_by_claim_hash:
            amount += sum(self.possible_future_support_amounts_by_claim_hash[claim_hash])
        if claim_hash in self.removed_active_support_amount_by_claim:
            return amount - sum(self.removed_active_support_amount_by_claim[claim_hash])
        return amount

    def _get_pending_effective_amount(self, name: str, claim_hash: bytes, height: Optional[int] = None) -> int:
        claim_amount = self._get_pending_claim_amount(name, claim_hash, height=height)
        support_amount = self._get_pending_supported_amount(claim_hash, height=height)
        return claim_amount + support_amount

    def _get_takeover_ops(self, height: int):

        # cache for controlling claims as of the previous block
        controlling_claims = {}

        def get_controlling(_name):
            if _name not in controlling_claims:
                _controlling = self.db.get_controlling_claim(_name)
                controlling_claims[_name] = _controlling
            else:
                _controlling = controlling_claims[_name]
            return _controlling

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
                    self.possible_future_support_txos_by_claim_hash[claim_hash].append((tx_num, nout))
            return StagedActivation(
                ACTIVATED_SUPPORT_TXO_TYPE if is_support else ACTIVATED_CLAIM_TXO_TYPE, claim_hash, tx_num, nout,
                height + delay, name, amount
            ).get_activate_ops()

        # determine names needing takeover/deletion due to controlling claims being abandoned
        # and add ops to deactivate abandoned claims
        for claim_hash, staged in self.abandoned_claims.items():
            controlling = get_controlling(staged.name)
            if controlling and controlling.claim_hash == claim_hash:
                names_with_abandoned_controlling_claims.append(staged.name)
                # print(f"\t{staged.name} needs takeover")
            activation = self.db.get_activation(staged.tx_num, staged.position)
            if activation > 0:  #  db returns -1 for non-existent txos
                # removed queued future activation from the db
                self.db_op_stack.extend_ops(
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
        for claim_hash, amounts in self.removed_active_support_amount_by_claim.items():
            name = self._get_pending_claim_name(claim_hash)
            if name is None:
                continue
            controlling = get_controlling(name)
            if controlling and controlling.claim_hash == claim_hash and \
                    name not in names_with_abandoned_controlling_claims:
                abandoned_support_check_need_takeover[(name, claim_hash)].extend(amounts)

        # prepare to activate or delay activation of the pending claims being added this block
        for (tx_num, nout), staged in self.txo_to_claim.items():
            self.db_op_stack.extend_ops(get_delayed_activate_ops(
                staged.name, staged.claim_hash, not staged.is_update, tx_num, nout, staged.amount, is_support=False
            ))

        # and the supports
        for (tx_num, nout), (claim_hash, amount) in self.support_txo_to_claim.items():
            if claim_hash in self.abandoned_claims:
                continue
            elif claim_hash in self.claim_hash_to_txo:
                name = self.txo_to_claim[self.claim_hash_to_txo[claim_hash]].name
                staged_is_new_claim = not self.txo_to_claim[self.claim_hash_to_txo[claim_hash]].is_update
            else:
                supported_claim_info = self.db.get_claim_txo(claim_hash)
                if not supported_claim_info:
                    # the supported claim doesn't exist
                    continue
                else:
                    v = supported_claim_info
                name = v.name
                staged_is_new_claim = (v.root_tx_num, v.root_position) == (v.tx_num, v.position)
            self.db_op_stack.extend_ops(get_delayed_activate_ops(
                name, claim_hash, staged_is_new_claim, tx_num, nout, amount, is_support=True
            ))

        # add the activation/delayed-activation ops
        for activated, activated_txos in activated_at_height.items():
            controlling = get_controlling(activated.name)
            if activated.claim_hash in self.abandoned_claims:
                continue
            reactivate = False
            if not controlling or controlling.claim_hash == activated.claim_hash:
                # there is no delay for claims to a name without a controlling value or to the controlling value
                reactivate = True
            for activated_txo in activated_txos:
                if activated_txo.is_support and (activated_txo.tx_num, activated_txo.position) in \
                        self.removed_support_txos_by_name_by_claim[activated.name][activated.claim_hash]:
                    # print("\tskip activate support for pending abandoned claim")
                    continue
                if activated_txo.is_claim:
                    txo_type = ACTIVATED_CLAIM_TXO_TYPE
                    txo_tup = (activated_txo.tx_num, activated_txo.position)
                    if txo_tup in self.txo_to_claim:
                        amount = self.txo_to_claim[txo_tup].amount
                    else:
                        amount = self.db.get_claim_txo_amount(
                            activated.claim_hash
                        )
                    self.activated_claim_amount_by_name_and_hash[(activated.name, activated.claim_hash)] = amount
                else:
                    txo_type = ACTIVATED_SUPPORT_TXO_TYPE
                    txo_tup = (activated_txo.tx_num, activated_txo.position)
                    if txo_tup in self.support_txo_to_claim:
                        amount = self.support_txo_to_claim[txo_tup][1]
                    else:
                        amount = self.db.get_support_txo_amount(
                            activated.claim_hash, activated_txo.tx_num, activated_txo.position
                        )
                    if amount is None:
                        # print("\tskip activate support for non existent claim")
                        continue
                    self.activated_support_amount_by_claim[activated.claim_hash].append(amount)
                self.activation_by_claim_by_name[activated.name][activated.claim_hash].append((activated_txo, amount))
                # print(f"\tactivate {'support' if txo_type == ACTIVATED_SUPPORT_TXO_TYPE else 'claim'} "
                #       f"{activated.claim_hash.hex()} @ {activated_txo.height}")

        # go through claims where the controlling claim or supports to the controlling claim have been abandoned
        # check if takeovers are needed or if the name node is now empty
        need_reactivate_if_takes_over = {}
        for need_takeover in names_with_abandoned_controlling_claims:
            existing = self.db.get_claim_txos_for_name(need_takeover)
            has_candidate = False
            # add existing claims to the queue for the takeover
            # track that we need to reactivate these if one of them becomes controlling
            for candidate_claim_hash, (tx_num, nout) in existing.items():
                if candidate_claim_hash in self.abandoned_claims:
                    continue
                has_candidate = True
                existing_activation = self.db.get_activation(tx_num, nout)
                activate_key = PendingActivationKey(
                    existing_activation, ACTIVATED_CLAIM_TXO_TYPE, tx_num, nout
                )
                self.activation_by_claim_by_name[need_takeover][candidate_claim_hash].append((
                    activate_key, self.db.get_claim_txo_amount(candidate_claim_hash)
                ))
                need_reactivate_if_takes_over[(need_takeover, candidate_claim_hash)] = activate_key
                # print(f"\tcandidate to takeover abandoned controlling claim for "
                #       f"{activate_key.tx_num}:{activate_key.position} {activate_key.is_claim}")
            if not has_candidate:
                # remove name takeover entry, the name is now unclaimed
                controlling = get_controlling(need_takeover)
                self.db_op_stack.extend_ops(get_remove_name_ops(need_takeover, controlling.claim_hash, controlling.height))

        # scan for possible takeovers out of the accumulated activations, of these make sure there
        # aren't any future activations for the taken over names with yet higher amounts, if there are
        # these need to get activated now and take over instead. for example:
        # claim A is winning for 0.1 for long enough for a > 1 takeover delay
        # claim B is made for 0.2
        # a block later, claim C is made for 0.3, it will schedule to activate 1 (or rarely 2) block(s) after B
        # upon the delayed activation of B, we need to detect to activate C and make it take over early instead

        claim_exists = {}
        for activated, activated_claim_txo in self.db.get_future_activated(height):
            # uses the pending effective amount for the future activation height, not the current height
            future_amount = self._get_pending_claim_amount(
                activated.name, activated.claim_hash, activated_claim_txo.height + 1
            )
            if activated.claim_hash not in claim_exists:
                claim_exists[activated.claim_hash] = activated.claim_hash in self.claim_hash_to_txo or (
                        self.db.get_claim_txo(activated.claim_hash) is not None)
            if claim_exists[activated.claim_hash] and activated.claim_hash not in self.abandoned_claims:
                v = future_amount, activated, activated_claim_txo
                future_activations[activated.name][activated.claim_hash] = v

        for name, future_activated in activate_in_future.items():
            for claim_hash, activated in future_activated.items():
                if claim_hash not in claim_exists:
                    claim_exists[claim_hash] = claim_hash in self.claim_hash_to_txo or (
                            self.db.get_claim_txo(claim_hash) is not None)
                if not claim_exists[claim_hash]:
                    continue
                if claim_hash in self.abandoned_claims:
                    continue
                for txo in activated:
                    v = txo[1], PendingActivationValue(claim_hash, name), txo[0]
                    future_activations[name][claim_hash] = v
                    if txo[0].is_claim:
                        self.possible_future_claim_amount_by_name_and_hash[(name, claim_hash)] = txo[1]
                    else:
                        self.possible_future_support_amounts_by_claim_hash[claim_hash].append(txo[1])

        # process takeovers
        checked_names = set()
        for name, activated in self.activation_by_claim_by_name.items():
            checked_names.add(name)
            controlling = controlling_claims[name]
            amounts = {
                claim_hash: self._get_pending_effective_amount(name, claim_hash)
                for claim_hash in activated.keys() if claim_hash not in self.abandoned_claims
            }
            # if there is a controlling claim include it in the amounts to ensure it remains the max
            if controlling and controlling.claim_hash not in self.abandoned_claims:
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
                future_winning_amount = amounts_with_future_activations[winning_including_future_activations]

                if winning_claim_hash != winning_including_future_activations and \
                        future_winning_amount > amounts[winning_claim_hash]:
                    # print(f"\ttakeover by {winning_claim_hash.hex()} triggered early activation and "
                    #       f"takeover by {winning_including_future_activations.hex()} at {height}")
                    # handle a pending activated claim jumping the takeover delay when another name takes over
                    if winning_including_future_activations not in self.claim_hash_to_txo:
                        claim = self.db.get_claim_txo(winning_including_future_activations)
                        tx_num = claim.tx_num
                        position = claim.position
                        amount = claim.amount
                        activation = self.db.get_activation(tx_num, position)
                    else:
                        tx_num, position = self.claim_hash_to_txo[winning_including_future_activations]
                        amount = None
                        activation = None
                        for (k, tx_amount) in activate_in_future[name][winning_including_future_activations]:
                            if (k.tx_num, k.position) == (tx_num, position):
                                amount = tx_amount
                                activation = k.height
                                break
                        assert None not in (amount, activation)
                    # update the claim that's activating early
                    self.db_op_stack.extend_ops(
                        StagedActivation(
                            ACTIVATED_CLAIM_TXO_TYPE, winning_including_future_activations, tx_num,
                            position, activation, name, amount
                        ).get_remove_activate_ops() + \
                        StagedActivation(
                            ACTIVATED_CLAIM_TXO_TYPE, winning_including_future_activations, tx_num,
                            position, height, name, amount
                        ).get_activate_ops()
                    )

                    for (k, amount) in activate_in_future[name][winning_including_future_activations]:
                        txo = (k.tx_num, k.position)
                        if txo in self.possible_future_support_txos_by_claim_hash[winning_including_future_activations]:
                            self.db_op_stack.extend_ops(
                                StagedActivation(
                                    ACTIVATED_SUPPORT_TXO_TYPE, winning_including_future_activations, k.tx_num,
                                    k.position, k.height, name, amount
                                ).get_remove_activate_ops() + \
                                StagedActivation(
                                    ACTIVATED_SUPPORT_TXO_TYPE, winning_including_future_activations, k.tx_num,
                                    k.position, height, name, amount
                                ).get_activate_ops()
                            )

                    self.db_op_stack.extend_ops(get_takeover_name_ops(name, winning_including_future_activations, height, controlling))
                    self.touched_claim_hashes.add(winning_including_future_activations)
                    if controlling and controlling.claim_hash not in self.abandoned_claims:
                        self.touched_claim_hashes.add(controlling.claim_hash)
                elif not controlling or (winning_claim_hash != controlling.claim_hash and
                                       name in names_with_abandoned_controlling_claims) or \
                        ((winning_claim_hash != controlling.claim_hash) and (amounts[winning_claim_hash] > amounts[controlling.claim_hash])):
                    # print(f"\ttakeover by {winning_claim_hash.hex()} at {height}")
                    if (name, winning_claim_hash) in need_reactivate_if_takes_over:
                        previous_pending_activate = need_reactivate_if_takes_over[(name, winning_claim_hash)]
                        amount = self.db.get_claim_txo_amount(
                            winning_claim_hash
                        )
                        if winning_claim_hash in self.claim_hash_to_txo:
                            tx_num, position = self.claim_hash_to_txo[winning_claim_hash]
                            amount = self.txo_to_claim[(tx_num, position)].amount
                        else:
                            tx_num, position = previous_pending_activate.tx_num, previous_pending_activate.position
                        if previous_pending_activate.height > height:
                            # the claim had a pending activation in the future, move it to now
                            if tx_num < self.tx_count:
                                self.db_op_stack.extend_ops(
                                    StagedActivation(
                                        ACTIVATED_CLAIM_TXO_TYPE, winning_claim_hash, tx_num,
                                        position, previous_pending_activate.height, name, amount
                                    ).get_remove_activate_ops()
                                )
                            self.db_op_stack.extend_ops(
                                StagedActivation(
                                    ACTIVATED_CLAIM_TXO_TYPE, winning_claim_hash, tx_num,
                                    position, height, name, amount
                                ).get_activate_ops()
                            )
                    self.db_op_stack.extend_ops(get_takeover_name_ops(name, winning_claim_hash, height, controlling))
                    if controlling and controlling.claim_hash not in self.abandoned_claims:
                        self.touched_claim_hashes.add(controlling.claim_hash)
                    self.touched_claim_hashes.add(winning_claim_hash)
                elif winning_claim_hash == controlling.claim_hash:
                    # print("\tstill winning")
                    pass
                else:
                    # print("\tno takeover")
                    pass

        # handle remaining takeovers from abandoned supports
        for (name, claim_hash), amounts in abandoned_support_check_need_takeover.items():
            if name in checked_names:
                continue
            checked_names.add(name)
            controlling = get_controlling(name)
            amounts = {
                claim_hash: self._get_pending_effective_amount(name, claim_hash)
                for claim_hash in self.db.get_claims_for_name(name) if claim_hash not in self.abandoned_claims
            }
            if controlling and controlling.claim_hash not in self.abandoned_claims:
                amounts[controlling.claim_hash] = self._get_pending_effective_amount(name, controlling.claim_hash)
            winning = max(amounts, key=lambda x: amounts[x])
            if (controlling and winning != controlling.claim_hash) or (not controlling and winning):
                # print(f"\ttakeover from abandoned support {controlling.claim_hash.hex()} -> {winning.hex()}")
                self.db_op_stack.extend_ops(get_takeover_name_ops(name, winning, height, controlling))
                if controlling:
                    self.touched_claim_hashes.add(controlling.claim_hash)
                self.touched_claim_hashes.add(winning)

    def _get_cumulative_update_ops(self):
        # gather cumulative removed/touched sets to update the search index
        self.removed_claim_hashes.update(set(self.abandoned_claims.keys()))
        self.touched_claim_hashes.update(
            set(self.activated_support_amount_by_claim.keys()).union(
                set(claim_hash for (_, claim_hash) in self.activated_claim_amount_by_name_and_hash.keys())
            ).union(self.signatures_changed).union(
                set(self.removed_active_support_amount_by_claim.keys())
            ).difference(self.removed_claim_hashes)
        )

        # use the cumulative changes to update bid ordered resolve
        for removed in self.removed_claim_hashes:
            removed_claim = self.db.get_claim_txo(removed)
            if removed_claim:
                amt = self.db.get_url_effective_amount(
                    removed_claim.name, removed
                )
                if amt:
                    self.db_op_stack.extend_ops(get_remove_effective_amount_ops(
                        removed_claim.name, amt.effective_amount, amt.tx_num,
                        amt.position, removed
                    ))
        for touched in self.touched_claim_hashes:
            if touched in self.claim_hash_to_txo:
                pending = self.txo_to_claim[self.claim_hash_to_txo[touched]]
                name, tx_num, position = pending.name, pending.tx_num, pending.position
                claim_from_db = self.db.get_claim_txo(touched)
                if claim_from_db:
                    claim_amount_info = self.db.get_url_effective_amount(name, touched)
                    if claim_amount_info:
                        self.db_op_stack.extend_ops(get_remove_effective_amount_ops(
                            name, claim_amount_info.effective_amount, claim_amount_info.tx_num,
                            claim_amount_info.position, touched
                        ))
            else:
                v = self.db.get_claim_txo(touched)
                if not v:
                    continue
                name, tx_num, position = v.name, v.tx_num, v.position
                amt = self.db.get_url_effective_amount(name, touched)
                if amt:
                    self.db_op_stack.extend_ops(get_remove_effective_amount_ops(
                        name, amt.effective_amount, amt.tx_num, amt.position, touched
                    ))
            self.db_op_stack.extend_ops(
                get_add_effective_amount_ops(name, self._get_pending_effective_amount(name, touched),
                                             tx_num, position, touched)
            )

        self.touched_claim_hashes.update(
            {k for k in self.pending_reposted if k not in self.removed_claim_hashes}
        )
        self.touched_claim_hashes.update(
            {k for k, v in self.pending_channel_counts.items() if v != 0 and k not in self.removed_claim_hashes}
        )
        self.touched_claims_to_send_es.difference_update(self.removed_claim_hashes)
        self.touched_claims_to_send_es.update(self.touched_claim_hashes)
        self.removed_claims_to_send_es.update(self.removed_claim_hashes)

    async def advance_block(self, block):
        height = self.height + 1
        # print("advance ", height)
        # Use local vars for speed in the loops
        tx_count = self.tx_count
        spend_utxo = self.spend_utxo
        add_utxo = self.add_utxo
        spend_claim_or_support_txo = self._spend_claim_or_support_txo
        add_claim_or_support = self._add_claim_or_support
        txs: List[Tuple[Tx, bytes]] = block.transactions

        self.db_op_stack.extend_ops([
            RevertablePut(*Prefixes.block_hash.pack_item(height, self.coin.header_hash(block.header))),
            RevertablePut(*Prefixes.header.pack_item(height, block.header))
        ])

        for tx, tx_hash in txs:
            spent_claims = {}
            txos = Transaction(tx.raw).outputs

            self.db_op_stack.extend_ops([
                RevertablePut(*Prefixes.tx.pack_item(tx_hash, tx.raw)),
                RevertablePut(*Prefixes.tx_num.pack_item(tx_hash, tx_count)),
                RevertablePut(*Prefixes.tx_hash.pack_item(tx_count, tx_hash))
            ])

            # Spend the inputs
            for txin in tx.inputs:
                if txin.is_generation():
                    continue
                # spend utxo for address histories
                hashX = spend_utxo(txin.prev_hash, txin.prev_idx)
                if hashX:
                    # self._set_hashX_cache(hashX)
                    if tx_count not in self.hashXs_by_tx[hashX]:
                        self.hashXs_by_tx[hashX].append(tx_count)
                # spend claim/support txo
                spend_claim_or_support_txo(txin, spent_claims)

            # Add the new UTXOs
            for nout, txout in enumerate(tx.outputs):
                # Get the hashX.  Ignore unspendable outputs
                hashX = add_utxo(tx_hash, tx_count, nout, txout)
                if hashX:
                    # self._set_hashX_cache(hashX)
                    if tx_count not in self.hashXs_by_tx[hashX]:
                        self.hashXs_by_tx[hashX].append(tx_count)
                # add claim/support txo
                add_claim_or_support(
                    height, tx_hash, tx_count, nout, txos[nout], spent_claims
                )

            # Handle abandoned claims
            abandoned_channels = {}
            # abandon the channels last to handle abandoned signed claims in the same tx,
            # see test_abandon_channel_and_claims_in_same_tx
            for abandoned_claim_hash, (tx_num, nout, name) in spent_claims.items():
                if name.startswith('@'):
                    abandoned_channels[abandoned_claim_hash] = (tx_num, nout, name)
                else:
                    # print(f"\tabandon {name} {abandoned_claim_hash.hex()} {tx_num} {nout}")
                    self._abandon_claim(abandoned_claim_hash, tx_num, nout, name)

            for abandoned_claim_hash, (tx_num, nout, name) in abandoned_channels.items():
                # print(f"\tabandon {name} {abandoned_claim_hash.hex()} {tx_num} {nout}")
                self._abandon_claim(abandoned_claim_hash, tx_num, nout, name)

            self.db.total_transactions.append(tx_hash)
            self.db.transaction_num_mapping[tx_hash] = tx_count
            tx_count += 1

        # handle expired claims
        self._expire_claims(height)

        # activate claims and process takeovers
        self._get_takeover_ops(height)

        # update effective amount and update sets of touched and deleted claims
        self._get_cumulative_update_ops()

        self.db_op_stack.append_op(RevertablePut(*Prefixes.tx_count.pack_item(height, tx_count)))

        for hashX, new_history in self.hashXs_by_tx.items():
            if not new_history:
                continue
            self.db_op_stack.append_op(
                RevertablePut(
                    *Prefixes.hashX_history.pack_item(
                        hashX, height, new_history
                    )
                )
            )

        self.tx_count = tx_count
        self.db.tx_counts.append(self.tx_count)

        cached_max_reorg_depth = self.daemon.cached_height() - self.env.reorg_limit
        if height >= cached_max_reorg_depth:
            self.db_op_stack.append_op(
                RevertablePut(
                    *Prefixes.touched_or_deleted.pack_item(
                        height, self.touched_claim_hashes, self.removed_claim_hashes
                    )
                )
            )
            self.db_op_stack.append_op(
                RevertablePut(
                    *Prefixes.undo.pack_item(height, self.db_op_stack.get_undo_ops())
                )
            )

        self.height = height
        self.db.headers.append(block.header)
        self.tip = self.coin.header_hash(block.header)

    def clear_after_advance_or_reorg(self):
        self.db_op_stack.clear()
        self.txo_to_claim.clear()
        self.claim_hash_to_txo.clear()
        self.support_txos_by_claim.clear()
        self.support_txo_to_claim.clear()
        self.removed_support_txos_by_name_by_claim.clear()
        self.abandoned_claims.clear()
        self.removed_active_support_amount_by_claim.clear()
        self.activated_support_amount_by_claim.clear()
        self.activated_claim_amount_by_name_and_hash.clear()
        self.activation_by_claim_by_name.clear()
        self.possible_future_claim_amount_by_name_and_hash.clear()
        self.possible_future_support_amounts_by_claim_hash.clear()
        self.possible_future_support_txos_by_claim_hash.clear()
        self.pending_channels.clear()
        self.amount_cache.clear()
        self.signatures_changed.clear()
        self.expired_claim_hashes.clear()
        self.doesnt_have_valid_signature.clear()
        self.claim_channels.clear()
        self.utxo_cache.clear()
        self.hashXs_by_tx.clear()
        self.history_cache.clear()
        self.mempool.notified_mempool_txs.clear()
        self.removed_claim_hashes.clear()
        self.touched_claim_hashes.clear()
        self.pending_reposted.clear()
        self.pending_channel_counts.clear()

    async def backup_block(self):
        # self.db.assert_flushed(self.flush_data())
        self.logger.info("backup block %i", self.height)
        # Check and update self.tip
        undo_ops, touched_and_deleted_bytes = self.db.read_undo_info(self.height)
        if undo_ops is None:
            raise ChainError(f'no undo information found for height {self.height:,d}')
        self.db_op_stack.append_op(RevertableDelete(Prefixes.undo.pack_key(self.height), undo_ops))
        self.db_op_stack.apply_packed_undo_ops(undo_ops)

        touched_and_deleted = Prefixes.touched_or_deleted.unpack_value(touched_and_deleted_bytes)
        self.touched_claims_to_send_es.update(touched_and_deleted.touched_claims)
        self.removed_claims_to_send_es.difference_update(touched_and_deleted.touched_claims)
        self.removed_claims_to_send_es.update(touched_and_deleted.deleted_claims)

        self.db.headers.pop()
        self.db.tx_counts.pop()
        self.tip = self.coin.header_hash(self.db.headers[-1])
        while len(self.db.total_transactions) > self.db.tx_counts[-1]:
            self.db.transaction_num_mapping.pop(self.db.total_transactions.pop())
            self.tx_count -= 1
        self.height -= 1
        # self.touched can include other addresses which is
        # harmless, but remove None.
        self.touched_hashXs.discard(None)

    def add_utxo(self, tx_hash: bytes, tx_num: int, nout: int, txout: 'TxOutput') -> Optional[bytes]:
        hashX = self.coin.hashX_from_script(txout.pk_script)
        if hashX:
            self.touched_hashXs.add(hashX)
            self.utxo_cache[(tx_hash, nout)] = (hashX, txout.value)
            self.db_op_stack.extend_ops([
                RevertablePut(
                    *Prefixes.utxo.pack_item(hashX, tx_num, nout, txout.value)
                ),
                RevertablePut(
                    *Prefixes.hashX_utxo.pack_item(tx_hash[:4], tx_num, nout, hashX)
                )
            ])
            return hashX

    def spend_utxo(self, tx_hash: bytes, nout: int):
        hashX, amount = self.utxo_cache.pop((tx_hash, nout), (None, None))
        txin_num = self.db.transaction_num_mapping[tx_hash]
        hdb_key = Prefixes.hashX_utxo.pack_key(tx_hash[:4], txin_num, nout)
        if not hashX:
            hashX = self.db.db.get(hdb_key)
            if not hashX:
                return
            udb_key = Prefixes.utxo.pack_key(hashX, txin_num, nout)
            utxo_value_packed = self.db.db.get(udb_key)
            if utxo_value_packed is None:
                self.logger.warning(
                    "%s:%s is not found in UTXO db for %s", hash_to_hex_str(tx_hash), nout, hash_to_hex_str(hashX)
                )
                raise ChainError(
                    f"{hash_to_hex_str(tx_hash)}:{nout} is not found in UTXO db for {hash_to_hex_str(hashX)}"
                )
            self.touched_hashXs.add(hashX)
            self.db_op_stack.extend_ops([
                RevertableDelete(hdb_key, hashX),
                RevertableDelete(udb_key, utxo_value_packed)
            ])
            return hashX
        elif amount is not None:
            udb_key = Prefixes.utxo.pack_key(hashX, txin_num, nout)
            self.touched_hashXs.add(hashX)
            self.db_op_stack.extend_ops([
                RevertableDelete(hdb_key, hashX),
                RevertableDelete(udb_key, Prefixes.utxo.pack_value(amount))
            ])
            return hashX

    async def _process_prefetched_blocks(self):
        """Loop forever processing blocks as they arrive."""
        while True:
            if self.height == self.daemon.cached_height():
                if not self._caught_up_event.is_set():
                    await self._first_caught_up()
                    self._caught_up_event.set()
            await self.blocks_event.wait()
            self.blocks_event.clear()
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
        await self.write_state()
        if first_sync:
            self.logger.info(f'{lbry.__version__} synced to '
                             f'height {self.height:,d}, halting here.')
            self.shutdown_event.set()

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
            await self.db.open_dbs()
            self.db_op_stack = RevertableOpStack(self.db.db.get)
            self.height = self.db.db_height
            self.tip = self.db.db_tip
            self.tx_count = self.db.db_tx_count

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
            self.logger.info('closing the DB for a clean shutdown...')
            self.db.close()
            # self.executor.shutdown(wait=True)
