import os
import time
import signal
import json
import typing
from collections import defaultdict
import asyncio
import logging
from elasticsearch import AsyncElasticsearch, NotFoundError
from elasticsearch.helpers import async_streaming_bulk
from prometheus_client import Gauge, Histogram

from lbry.schema.result import Censor
from lbry.wallet.server.db.elasticsearch.search import IndexVersionMismatch
from lbry.wallet.server.db.elasticsearch.constants import ALL_FIELDS, INDEX_DEFAULT_SETTINGS
from lbry.wallet.server.db.elasticsearch.common import expand_query
from lbry.wallet.server.db.elasticsearch.notifier import ElasticNotifierProtocol
from lbry.wallet.server.db.elasticsearch.fast_ar_trending import FAST_AR_TRENDING_SCRIPT
from lbry.wallet.server.chain_reader import BlockchainReader, HISTOGRAM_BUCKETS
from lbry.wallet.server.db.revertable import RevertableOp
from lbry.wallet.server.db.common import TrendingNotification
from lbry.wallet.server.db import DB_PREFIXES


log = logging.getLogger()


class ElasticWriter(BlockchainReader):
    VERSION = 1
    prometheus_namespace = ""
    block_count_metric = Gauge(
        "block_count", "Number of processed blocks", namespace="elastic_sync"
    )
    block_update_time_metric = Histogram(
        "block_time", "Block update times", namespace="elastic_sync", buckets=HISTOGRAM_BUCKETS
    )
    reorg_count_metric = Gauge(
        "reorg_count", "Number of reorgs", namespace="elastic_sync"
    )

    def __init__(self, env):
        super().__init__(env, 'lbry-elastic-writer', thread_workers=1, thread_prefix='lbry-elastic-writer')
        # self._refresh_interval = 0.1
        self._task = None
        self.index = self.env.es_index_prefix + 'claims'
        self._elastic_host = env.elastic_host
        self._elastic_port = env.elastic_port
        self.sync_timeout = 1800
        self.sync_client = None
        self._es_info_path = os.path.join(env.db_dir, 'es_info')
        self._last_wrote_height = 0
        self._last_wrote_block_hash = None

        self._touched_claims = set()
        self._deleted_claims = set()

        self._removed_during_undo = set()

        self._trending = defaultdict(list)
        self._advanced = True
        self.synchronized = asyncio.Event()
        self._listeners: typing.List[ElasticNotifierProtocol] = []

    async def run_es_notifier(self, synchronized: asyncio.Event):
        server = await asyncio.get_event_loop().create_server(
            lambda: ElasticNotifierProtocol(self._listeners), '127.0.0.1', self.env.elastic_notifier_port
        )
        self.log.info("ES notifier server listening on TCP localhost:%i", self.env.elastic_notifier_port)
        synchronized.set()
        async with server:
            await server.serve_forever()

    def notify_es_notification_listeners(self, height: int, block_hash: bytes):
        for p in self._listeners:
            p.send_height(height, block_hash)
            self.log.info("notify listener %i", height)

    def _read_es_height(self):
        info = {}
        if os.path.exists(self._es_info_path):
            with open(self._es_info_path, 'r') as f:
                info.update(json.loads(f.read()))
        self._last_wrote_height = int(info.get('height', 0))
        self._last_wrote_block_hash = info.get('block_hash', None)

    async def read_es_height(self):
        await asyncio.get_event_loop().run_in_executor(self._executor, self._read_es_height)

    def write_es_height(self, height: int, block_hash: str):
        with open(self._es_info_path, 'w') as f:
            f.write(json.dumps({'height': height, 'block_hash': block_hash}, indent=2))
        self._last_wrote_height = height
        self._last_wrote_block_hash = block_hash

    async def get_index_version(self) -> int:
        try:
            template = await self.sync_client.indices.get_template(self.index)
            return template[self.index]['version']
        except NotFoundError:
            return 0

    async def set_index_version(self, version):
        await self.sync_client.indices.put_template(
            self.index, body={'version': version, 'index_patterns': ['ignored']}, ignore=400
        )

    async def start_index(self) -> bool:
        if self.sync_client:
            return False
        hosts = [{'host': self._elastic_host, 'port': self._elastic_port}]
        self.sync_client = AsyncElasticsearch(hosts, timeout=self.sync_timeout)
        while True:
            try:
                await self.sync_client.cluster.health(wait_for_status='yellow')
                self.log.info("ES is ready to connect to")
                break
            except ConnectionError:
                self.log.warning("Failed to connect to Elasticsearch. Waiting for it!")
                await asyncio.sleep(1)

        index_version = await self.get_index_version()

        res = await self.sync_client.indices.create(self.index, INDEX_DEFAULT_SETTINGS, ignore=400)
        acked = res.get('acknowledged', False)

        if acked:
            await self.set_index_version(self.VERSION)
            return True
        elif index_version != self.VERSION:
            self.log.error("es search index has an incompatible version: %s vs %s", index_version, self.VERSION)
            raise IndexVersionMismatch(index_version, self.VERSION)
        else:
            await self.sync_client.indices.refresh(self.index)
            return False

    async def stop_index(self):
        if self.sync_client:
            await self.sync_client.close()
        self.sync_client = None

    async def delete_index(self):
        if self.sync_client:
            return await self.sync_client.indices.delete(self.index, ignore_unavailable=True)

    def update_filter_query(self, censor_type, blockdict, channels=False):
        blockdict = {blocked.hex(): blocker.hex() for blocked, blocker in blockdict.items()}
        if channels:
            update = expand_query(channel_id__in=list(blockdict.keys()), censor_type=f"<{censor_type}")
        else:
            update = expand_query(claim_id__in=list(blockdict.keys()), censor_type=f"<{censor_type}")
        key = 'channel_id' if channels else 'claim_id'
        update['script'] = {
            "source": f"ctx._source.censor_type={censor_type}; "
                      f"ctx._source.censoring_channel_id=params[ctx._source.{key}];",
            "lang": "painless",
            "params": blockdict
        }
        return update

    async def apply_filters(self, blocked_streams, blocked_channels, filtered_streams, filtered_channels):
        if filtered_streams:
            await self.sync_client.update_by_query(
                self.index, body=self.update_filter_query(Censor.SEARCH, filtered_streams), slices=4)
            await self.sync_client.indices.refresh(self.index)
        if filtered_channels:
            await self.sync_client.update_by_query(
                self.index, body=self.update_filter_query(Censor.SEARCH, filtered_channels), slices=4)
            await self.sync_client.indices.refresh(self.index)
            await self.sync_client.update_by_query(
                self.index, body=self.update_filter_query(Censor.SEARCH, filtered_channels, True), slices=4)
            await self.sync_client.indices.refresh(self.index)
        if blocked_streams:
            await self.sync_client.update_by_query(
                self.index, body=self.update_filter_query(Censor.RESOLVE, blocked_streams), slices=4)
            await self.sync_client.indices.refresh(self.index)
        if blocked_channels:
            await self.sync_client.update_by_query(
                self.index, body=self.update_filter_query(Censor.RESOLVE, blocked_channels), slices=4)
            await self.sync_client.indices.refresh(self.index)
            await self.sync_client.update_by_query(
                self.index, body=self.update_filter_query(Censor.RESOLVE, blocked_channels, True), slices=4)
            await self.sync_client.indices.refresh(self.index)

    @staticmethod
    def _upsert_claim_query(index, claim):
        return {
            'doc': {key: value for key, value in claim.items() if key in ALL_FIELDS},
            '_id': claim['claim_id'],
            '_index': index,
            '_op_type': 'update',
            'doc_as_upsert': True
        }

    @staticmethod
    def _delete_claim_query(index, claim_hash: bytes):
        return {
            '_index': index,
            '_op_type': 'delete',
            '_id': claim_hash.hex()
        }

    @staticmethod
    def _update_trending_query(index, claim_hash, notifications):
        return {
            '_id': claim_hash.hex(),
            '_index': index,
            '_op_type': 'update',
            'script': {
                'lang': 'painless',
                'source': FAST_AR_TRENDING_SCRIPT,
                'params': {'src': {
                    'changes': [
                        {
                            'height': notification.height,
                            'prev_amount': notification.prev_amount / 1E8,
                            'new_amount': notification.new_amount / 1E8,
                        } for notification in notifications
                    ]
                }}
            },
        }

    async def _claim_producer(self):
        for deleted in self._deleted_claims:
            yield self._delete_claim_query(self.index, deleted)
        for touched in self._touched_claims:
            claim = self.db.claim_producer(touched)
            if claim:
                yield self._upsert_claim_query(self.index, claim)
        for claim_hash, notifications in self._trending.items():
            yield self._update_trending_query(self.index, claim_hash, notifications)

    def advance(self, height: int):
        super().advance(height)

        touched_or_deleted = self.db.prefix_db.touched_or_deleted.get(height)
        for k, v in self.db.prefix_db.trending_notification.iterate((height,)):
            self._trending[k.claim_hash].append(TrendingNotification(k.height, v.previous_amount, v.new_amount))
        if touched_or_deleted:
            readded_after_reorg = self._removed_during_undo.intersection(touched_or_deleted.touched_claims)
            self._deleted_claims.difference_update(readded_after_reorg)
            self._touched_claims.update(touched_or_deleted.touched_claims)
            self._deleted_claims.update(touched_or_deleted.deleted_claims)
            self._touched_claims.difference_update(self._deleted_claims)
            for to_del in touched_or_deleted.deleted_claims:
                if to_del in self._trending:
                    self._trending.pop(to_del)
        self._advanced = True

    def unwind(self):
        self.db.tx_counts.pop()
        reverted_block_hash = self.db.coin.header_hash(self.db.headers.pop())
        packed = self.db.prefix_db.undo.get(len(self.db.tx_counts), reverted_block_hash)
        touched_or_deleted = None
        claims_to_delete = []
        # find and apply the touched_or_deleted items in the undos for the reverted blocks
        assert packed, f'missing undo information for block {len(self.db.tx_counts)}'
        while packed:
            op, packed = RevertableOp.unpack(packed)
            if op.is_delete and op.key.startswith(DB_PREFIXES.touched_or_deleted.value):
                assert touched_or_deleted is None, 'only should have one match'
                touched_or_deleted = self.db.prefix_db.touched_or_deleted.unpack_value(op.value)
            elif op.is_delete and op.key.startswith(DB_PREFIXES.claim_to_txo.value):
                v = self.db.prefix_db.claim_to_txo.unpack_value(op.value)
                if v.root_tx_num == v.tx_num and v.root_tx_num > self.db.tx_counts[-1]:
                    claims_to_delete.append(self.db.prefix_db.claim_to_txo.unpack_key(op.key).claim_hash)
        if touched_or_deleted:
            self._touched_claims.update(set(touched_or_deleted.deleted_claims).union(
                touched_or_deleted.touched_claims.difference(set(claims_to_delete))))
            self._deleted_claims.update(claims_to_delete)
            self._removed_during_undo.update(claims_to_delete)
        self._advanced = True
        self.log.warning("delete %i claim and upsert %i from reorg", len(self._deleted_claims), len(self._touched_claims))

    async def poll_for_changes(self):
        await super().poll_for_changes()
        cnt = 0
        success = 0
        if self._advanced:
            if self._touched_claims or self._deleted_claims or self._trending:
                async for ok, item in async_streaming_bulk(
                        self.sync_client, self._claim_producer(),
                        raise_on_error=False):
                    cnt += 1
                    if not ok:
                        self.log.warning("indexing failed for an item: %s", item)
                    else:
                        success += 1
                await self.sync_client.indices.refresh(self.index)
                await self.db.reload_blocking_filtering_streams()
                await self.apply_filters(
                    self.db.blocked_streams, self.db.blocked_channels, self.db.filtered_streams,
                    self.db.filtered_channels
                )
            self.write_es_height(self.db.db_height, self.db.db_tip[::-1].hex())
            self.log.info("Indexing block %i done. %i/%i successful", self._last_wrote_height, success, cnt)
            self._touched_claims.clear()
            self._deleted_claims.clear()
            self._removed_during_undo.clear()
            self._trending.clear()
            self._advanced = False
            self.synchronized.set()
            self.notify_es_notification_listeners(self._last_wrote_height, self.db.db_tip)

    @property
    def last_synced_height(self) -> int:
        return self._last_wrote_height

    async def start(self, reindex=False):
        await super().start()

        def _start_cancellable(run, *args):
            _flag = asyncio.Event()
            self.cancellable_tasks.append(asyncio.ensure_future(run(*args, _flag)))
            return _flag.wait()

        self.db.open_db()
        await self.db.initialize_caches()
        await self.read_es_height()
        await self.start_index()
        self.last_state = self.db.read_db_state()

        await _start_cancellable(self.run_es_notifier)

        if reindex or self._last_wrote_height == 0 and self.db.db_height > 0:
            if self._last_wrote_height == 0:
                self.log.info("running initial ES indexing of rocksdb at block height %i", self.db.db_height)
            else:
                self.log.info("reindex (last wrote: %i, db height: %i)", self._last_wrote_height, self.db.db_height)
            await self.reindex()
        await _start_cancellable(self.refresh_blocks_forever)

    async def stop(self, delete_index=False):
        async with self._lock:
            while self.cancellable_tasks:
                t = self.cancellable_tasks.pop()
                if not t.done():
                    t.cancel()
        if delete_index:
            await self.delete_index()
        await self.stop_index()
        self._executor.shutdown(wait=True)
        self._executor = None
        self.shutdown_event.set()

    def run(self, reindex=False):
        loop = asyncio.get_event_loop()
        loop.set_default_executor(self._executor)

        def __exit():
            raise SystemExit()
        try:
            loop.add_signal_handler(signal.SIGINT, __exit)
            loop.add_signal_handler(signal.SIGTERM, __exit)
            loop.run_until_complete(self.start(reindex=reindex))
            loop.run_until_complete(self.shutdown_event.wait())
        except (SystemExit, KeyboardInterrupt):
            pass
        finally:
            loop.run_until_complete(self.stop())

    async def reindex(self):
        async with self._lock:
            self.log.info("reindexing %i claims (estimate)", self.db.prefix_db.claim_to_txo.estimate_num_keys())
            await self.delete_index()
            res = await self.sync_client.indices.create(self.index, INDEX_DEFAULT_SETTINGS, ignore=400)
            acked = res.get('acknowledged', False)
            if acked:
                await self.set_index_version(self.VERSION)
            await self.sync_client.indices.refresh(self.index)
            self.write_es_height(0, self.env.coin.GENESIS_HASH)
            await self._sync_all_claims()
            await self.sync_client.indices.refresh(self.index)
            self.write_es_height(self.db.db_height, self.db.db_tip[::-1].hex())
            self.notify_es_notification_listeners(self.db.db_height, self.db.db_tip)
            self.log.info("finished reindexing")

    async def _sync_all_claims(self, batch_size=100000):
        def load_historic_trending():
            notifications = self._trending
            for k, v in self.db.prefix_db.trending_notification.iterate():
                notifications[k.claim_hash].append(TrendingNotification(k.height, v.previous_amount, v.new_amount))

        async def all_claims_producer():
            async for claim in self.db.all_claims_producer(batch_size=batch_size):
                yield self._upsert_claim_query(self.index, claim)
                claim_hash = bytes.fromhex(claim['claim_id'])
                if claim_hash in self._trending:
                    yield self._update_trending_query(self.index, claim_hash, self._trending.pop(claim_hash))
            self._trending.clear()

        self.log.info("loading about %i historic trending updates", self.db.prefix_db.trending_notification.estimate_num_keys())
        await asyncio.get_event_loop().run_in_executor(self._executor, load_historic_trending)
        self.log.info("loaded historic trending updates for %i claims", len(self._trending))

        cnt = 0
        success = 0
        producer = all_claims_producer()

        finished = False
        try:
            async for ok, item in async_streaming_bulk(self.sync_client, producer, raise_on_error=False):
                cnt += 1
                if not ok:
                    self.log.warning("indexing failed for an item: %s", item)
                else:
                    success += 1
                if cnt % batch_size == 0:
                    self.log.info(f"indexed {success} claims")
            finished = True
            await self.sync_client.indices.refresh(self.index)
            self.log.info("indexed %i/%i claims", success, cnt)
        finally:
            if not finished:
                await producer.aclose()
            self.shutdown_event.set()
