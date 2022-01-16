# Copyright (c) 2016-2018, Neil Booth
#
# All rights reserved.
#
# See the file "LICENCE" for information about the copyright
# and warranty status of this software.

"""Mempool handling."""
import asyncio
import itertools
import time
import attr
import typing
from collections import defaultdict
from prometheus_client import Histogram
from lbry.wallet.server.util import class_logger

if typing.TYPE_CHECKING:
    from lbry.wallet.server.session import LBRYSessionManager
    from wallet.server.db.db import LevelDB


@attr.s(slots=True)
class MemPoolTx:
    prevouts = attr.ib()
    # A pair is a (hashX, value) tuple
    in_pairs = attr.ib()
    out_pairs = attr.ib()
    fee = attr.ib()
    size = attr.ib()
    raw_tx = attr.ib()


@attr.s(slots=True)
class MemPoolTxSummary:
    hash = attr.ib()
    fee = attr.ib()
    has_unconfirmed_inputs = attr.ib()


NAMESPACE = "wallet_server"
HISTOGRAM_BUCKETS = (
    .005, .01, .025, .05, .075, .1, .25, .5, .75, 1.0, 2.5, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0, 60.0, float('inf')
)
mempool_process_time_metric = Histogram(
    "processed_mempool", "Time to process mempool and notify touched addresses",
    namespace=NAMESPACE, buckets=HISTOGRAM_BUCKETS
)


class MemPool:
    def __init__(self, coin, db: 'LevelDB', refresh_secs=1.0):
        self.coin = coin
        self._db = db
        self.logger = class_logger(__name__, self.__class__.__name__)
        self.txs = {}
        self.raw_mempool = {}
        self.touched_hashXs: typing.DefaultDict[bytes, typing.Set[bytes]] = defaultdict(set)  # None can be a key
        self.refresh_secs = refresh_secs
        self.mempool_process_time_metric = mempool_process_time_metric
        self.session_manager: typing.Optional['LBRYSessionManager'] = None

    async def refresh_hashes(self, height: int):
        start = time.perf_counter()
        new_touched = await self._process_mempool()
        await self.on_mempool(set(self.touched_hashXs), new_touched, height)
        duration = time.perf_counter() - start
        self.mempool_process_time_metric.observe(duration)

    async def _process_mempool(self) -> typing.Set[bytes]:  # returns list of new touched hashXs
        # Re-sync with the new set of hashes

        # hashXs = self.hashXs  # hashX: [tx_hash, ...]
        touched_hashXs = set()

        # Remove txs that aren't in mempool anymore
        for tx_hash in set(self.txs).difference(self.raw_mempool.keys()):
            tx = self.txs.pop(tx_hash)
            tx_hashXs = {hashX for hashX, value in tx.in_pairs}.union({hashX for hashX, value in tx.out_pairs})
            for hashX in tx_hashXs:
                if hashX in self.touched_hashXs and tx_hash in self.touched_hashXs[hashX]:
                    self.touched_hashXs[hashX].remove(tx_hash)
                    if not self.touched_hashXs[hashX]:
                        self.touched_hashXs.pop(hashX)
            touched_hashXs.update(tx_hashXs)

        tx_map = {}
        for tx_hash, raw_tx in self.raw_mempool.items():
            if tx_hash in self.txs:
                continue
            tx, tx_size = self.coin.DESERIALIZER(raw_tx).read_tx_and_vsize()
            # Convert the inputs and outputs into (hashX, value) pairs
            # Drop generation-like inputs from MemPoolTx.prevouts
            txin_pairs = tuple((txin.prev_hash, txin.prev_idx)
                               for txin in tx.inputs
                               if not txin.is_generation())
            txout_pairs = tuple((self.coin.hashX_from_script(txout.pk_script), txout.value)
                                for txout in tx.outputs)

            tx_map[tx_hash] = MemPoolTx(txin_pairs, None, txout_pairs, 0, tx_size, raw_tx)

        # Determine all prevouts not in the mempool, and fetch the
        # UTXO information from the database.  Failed prevout lookups
        # return None - concurrent database updates happen - which is
        # relied upon by _accept_transactions. Ignore prevouts that are
        # generation-like.
        # prevouts = tuple(prevout for tx in tx_map.values()
        #                  for prevout in tx.prevouts
        #                  if prevout[0] not in self.raw_mempool)
        # utxos = await self._db.lookup_utxos(prevouts)
        # utxo_map = dict(zip(prevouts, utxos))
        # unspent = set(utxo_map)

        for tx_hash, tx in tx_map.items():
            in_pairs = []
            for prevout in tx.prevouts:
                # utxo = utxo_map.get(prevout)
                # if not utxo:
                prev_hash, prev_index = prevout
                if prev_hash in self.txs:  # accepted mempool
                    utxo = self.txs[prev_hash].out_pairs[prev_index]
                elif prev_hash in tx_map:  # this set of changes
                    utxo = tx_map[prev_hash].out_pairs[prev_index]
                else:  # get it from the db
                    prev_tx_num = self._db.prefix_db.tx_num.get(prev_hash)
                    if not prev_tx_num:
                        continue
                    prev_tx_num = prev_tx_num.tx_num
                    hashX_val = self._db.prefix_db.hashX_utxo.get(tx_hash[:4], prev_tx_num, prev_index)
                    if not hashX_val:
                        continue
                    hashX = hashX_val.hashX
                    utxo_value = self._db.prefix_db.utxo.get(hashX, prev_tx_num, prev_index)
                    utxo = (hashX, utxo_value.amount)
                    # if not prev_raw:
                    #     print("derp", prev_hash[::-1].hex())
                    #     print(self._db.get_tx_num(prev_hash))
                    # prev_tx, prev_tx_size = self.coin.DESERIALIZER(prev_raw.raw_tx).read_tx_and_vsize()
                    # prev_txo = prev_tx.outputs[prev_index]
                    # utxo = (self.coin.hashX_from_script(prev_txo.pk_script), prev_txo.value)
                in_pairs.append(utxo)

            # # Spend the prevouts
            # unspent.difference_update(tx.prevouts)

            # Save the in_pairs, compute the fee and accept the TX
            tx.in_pairs = tuple(in_pairs)
            # Avoid negative fees if dealing with generation-like transactions
            # because some in_parts would be missing
            tx.fee = max(0, (sum(v for _, v in tx.in_pairs) -
                             sum(v for _, v in tx.out_pairs)))
            self.txs[tx_hash] = tx
            # print(f"added {tx_hash[::-1].hex()} reader to mempool")

            for hashX, value in itertools.chain(tx.in_pairs, tx.out_pairs):
                self.touched_hashXs[hashX].add(tx_hash)
                touched_hashXs.add(hashX)
        # utxo_map = {prevout: utxo_map[prevout] for prevout in unspent}

        return touched_hashXs

    def transaction_summaries(self, hashX):
        """Return a list of MemPoolTxSummary objects for the hashX."""
        result = []
        for tx_hash in self.touched_hashXs.get(hashX, ()):
            tx = self.txs[tx_hash]
            has_ui = any(hash in self.txs for hash, idx in tx.prevouts)
            result.append(MemPoolTxSummary(tx_hash, tx.fee, has_ui))
        return result

    def get_mempool_height(self, tx_hash: bytes) -> int:
        # Height Progression
        #   -2: not broadcast
        #   -1: in mempool but has unconfirmed inputs
        #    0: in mempool and all inputs confirmed
        # +num: confirmed in a specific block (height)
        if tx_hash not in self.txs:
            return -2
        tx = self.txs[tx_hash]
        unspent_inputs = any(hash in self.raw_mempool for hash, idx in tx.prevouts)
        if unspent_inputs:
            return -1
        return 0

    async def start(self, height, session_manager: 'LBRYSessionManager'):
        self.notify_sessions = session_manager._notify_sessions
        await self._notify_sessions(height, set(), set())

    async def on_mempool(self, touched, new_touched, height):
        await self._notify_sessions(height, touched, new_touched)

    async def on_block(self, touched, height):
        await self._notify_sessions(height, touched, set())

    async def _notify_sessions(self, height, touched, new_touched):
        """Notify sessions about height changes and touched addresses."""
        height_changed = height != self.session_manager.notified_height
        if height_changed:
            await self.session_manager._refresh_hsub_results(height)

        if not self.session_manager.sessions:
            return

        if height_changed:
            header_tasks = [
                session.send_notification('blockchain.headers.subscribe', (self.session_manager.hsub_results[session.subscribe_headers_raw], ))
                for session in self.session_manager.sessions.values() if session.subscribe_headers
            ]
            if header_tasks:
                self.logger.info(f'notify {len(header_tasks)} sessions of new header')
                asyncio.create_task(asyncio.wait(header_tasks))
            for hashX in touched.intersection(self.session_manager.mempool_statuses.keys()):
                self.session_manager.mempool_statuses.pop(hashX, None)
        # self.bp._chain_executor
        await asyncio.get_event_loop().run_in_executor(
            None, touched.intersection_update, self.session_manager.hashx_subscriptions_by_session.keys()
        )

        if touched or new_touched or (height_changed and self.session_manager.mempool_statuses):
            notified_hashxs = 0
            session_hashxes_to_notify = defaultdict(list)
            to_notify = touched if height_changed else new_touched

            for hashX in to_notify:
                if hashX not in self.session_manager.hashx_subscriptions_by_session:
                    continue
                for session_id in self.session_manager.hashx_subscriptions_by_session[hashX]:
                    session_hashxes_to_notify[session_id].append(hashX)
                    notified_hashxs += 1
            for session_id, hashXes in session_hashxes_to_notify.items():
                asyncio.create_task(self.session_manager.sessions[session_id].send_history_notifications(*hashXes))
            if session_hashxes_to_notify:
                self.logger.info(f'notified {len(session_hashxes_to_notify)} sessions/{notified_hashxs:,d} touched addresses')
