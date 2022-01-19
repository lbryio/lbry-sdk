import signal
import logging
import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
import typing

import lbry
from lbry.wallet.server.mempool import MemPool
from lbry.wallet.server.db.prefixes import DBState
from lbry.wallet.server.udp import StatusServer
from lbry.wallet.server.db.db import HubDB
from lbry.wallet.server.db.elasticsearch.notifier import ElasticNotifierClientProtocol
from lbry.wallet.server.session import LBRYSessionManager
from lbry.prometheus import PrometheusServer


class BlockchainReader:
    def __init__(self, env, secondary_name: str, thread_workers: int = 1, thread_prefix: str = 'blockchain-reader'):
        self.env = env
        self.log = logging.getLogger(__name__).getChild(self.__class__.__name__)
        self.shutdown_event = asyncio.Event()
        self.cancellable_tasks = []
        self._executor = ThreadPoolExecutor(thread_workers, thread_name_prefix=thread_prefix)

        self.db = HubDB(
            env.coin, env.db_dir, env.cache_MB, env.reorg_limit, env.cache_all_claim_txos, env.cache_all_tx_hashes,
            secondary_name=secondary_name, max_open_files=-1, executor=self._executor
        )
        self.last_state: typing.Optional[DBState] = None
        self._refresh_interval = 0.1
        self._lock = asyncio.Lock()

    def _detect_changes(self):
        try:
            self.db.prefix_db.try_catch_up_with_primary()
        except:
            self.log.exception('failed to update secondary db')
            raise
        state = self.db.prefix_db.db_state.get()
        if not state or state.height <= 0:
            return
        # if state and self.last_state and self.db.headers and self.last_state.tip == self.db.coin.header_hash(self.db.headers[-1]):
        #     return
        if self.last_state and self.last_state.height > state.height:
            self.log.warning("reorg detected, waiting until the writer has flushed the new blocks to advance")
            return
        last_height = 0 if not self.last_state else self.last_state.height
        if self.last_state:
            while True:
                if self.db.headers[-1] == self.db.prefix_db.header.get(last_height, deserialize_value=False):
                    self.log.info("connects to block %i", last_height)
                    break
                else:
                    self.log.warning("disconnect block %i", last_height)
                    self.unwind()
                    last_height -= 1
        self.db.read_db_state()
        if not self.last_state or last_height < state.height:
            for height in range(last_height + 1, state.height + 1):
                self.log.info("advancing to %i", height)
                self.advance(height)
            self.clear_caches()
            self.last_state = state

    async def poll_for_changes(self):
        await asyncio.get_event_loop().run_in_executor(self._executor, self._detect_changes)

    async def refresh_blocks_forever(self, synchronized: asyncio.Event):
        while True:
            try:
                async with self._lock:
                    await self.poll_for_changes()
            except asyncio.CancelledError:
                raise
            except:
                self.log.exception("blockchain reader main loop encountered an unexpected error")
                raise
            await asyncio.sleep(self._refresh_interval)
            synchronized.set()

    def clear_caches(self):
        pass

    def advance(self, height: int):
        tx_count = self.db.prefix_db.tx_count.get(height).tx_count
        assert tx_count not in self.db.tx_counts, f'boom {tx_count} in {len(self.db.tx_counts)} tx counts'
        assert len(self.db.tx_counts) == height, f"{len(self.db.tx_counts)} != {height}"
        self.db.tx_counts.append(tx_count)
        self.db.headers.append(self.db.prefix_db.header.get(height, deserialize_value=False))

    def unwind(self):
        self.db.tx_counts.pop()
        self.db.headers.pop()


class BlockchainReaderServer(BlockchainReader):
    def __init__(self, env):
        super().__init__(env, 'lbry-reader', thread_workers=1, thread_prefix='hub-worker')
        self.history_cache = {}
        self.resolve_outputs_cache = {}
        self.resolve_cache = {}
        self.notifications_to_send = []
        self.status_server = StatusServer()
        self.daemon = env.coin.DAEMON(env.coin, env.daemon_url)  # only needed for broadcasting txs
        self.prometheus_server: typing.Optional[PrometheusServer] = None
        self.mempool = MemPool(self.env.coin, self.db)
        self.session_manager = LBRYSessionManager(
            env, self.db, self.mempool, self.history_cache, self.resolve_cache,
            self.resolve_outputs_cache, self.daemon,
            self.shutdown_event,
            on_available_callback=self.status_server.set_available,
            on_unavailable_callback=self.status_server.set_unavailable
        )
        self.mempool.session_manager = self.session_manager
        self.es_notifications = asyncio.Queue()
        self.es_notification_client = ElasticNotifierClientProtocol(self.es_notifications)
        self.synchronized = asyncio.Event()
        self._es_height = None
        self._es_block_hash = None

    def clear_caches(self):
        self.history_cache.clear()
        self.resolve_outputs_cache.clear()
        self.resolve_cache.clear()
        # self.clear_search_cache()
        # self.mempool.notified_mempool_txs.clear()

    def clear_search_cache(self):
        self.session_manager.search_index.clear_caches()

    def advance(self, height: int):
        super().advance(height)
        touched_hashXs = self.db.prefix_db.touched_hashX.get(height).touched_hashXs
        self.notifications_to_send.append((set(touched_hashXs), height))

    def _detect_changes(self):
        super()._detect_changes()
        self.mempool.raw_mempool.clear()
        self.mempool.raw_mempool.update(
            {k.tx_hash: v.raw_tx for k, v in self.db.prefix_db.mempool_tx.iterate()}
        )

    async def poll_for_changes(self):
        await super().poll_for_changes()
        self.status_server.set_height(self.db.fs_height, self.db.db_tip)
        if self.notifications_to_send:
            for (touched, height) in self.notifications_to_send:
                await self.mempool.on_block(touched, height)
                self.log.info("reader advanced to %i", height)
                if self._es_height == self.db.db_height:
                    self.synchronized.set()
        await self.mempool.refresh_hashes(self.db.db_height)
        self.notifications_to_send.clear()

    async def receive_es_notifications(self, synchronized: asyncio.Event):
        await asyncio.get_event_loop().create_connection(
            lambda: self.es_notification_client, '127.0.0.1', self.env.elastic_notifier_port
        )
        synchronized.set()
        try:
            while True:
                self._es_height, self._es_block_hash = await self.es_notifications.get()
                self.clear_search_cache()
                if self.last_state and self._es_block_hash == self.last_state.tip:
                    self.synchronized.set()
                    self.log.info("es and reader are in sync")
                else:
                    self.log.info("es and reader are not yet in sync %s vs %s", self._es_height, self.db.db_height)
        finally:
            self.es_notification_client.close()

    async def start(self):
        env = self.env
        min_str, max_str = env.coin.SESSIONCLS.protocol_min_max_strings()
        self.log.info(f'software version: {lbry.__version__}')
        self.log.info(f'supported protocol versions: {min_str}-{max_str}')
        self.log.info(f'event loop policy: {env.loop_policy}')
        self.log.info(f'reorg limit is {env.reorg_limit:,d} blocks')
        await self.daemon.height()

        def _start_cancellable(run, *args):
            _flag = asyncio.Event()
            self.cancellable_tasks.append(asyncio.ensure_future(run(*args, _flag)))
            return _flag.wait()

        self.db.open_db()
        await self.db.initialize_caches()

        self.last_state = self.db.read_db_state()

        await self.start_prometheus()
        if self.env.udp_port:
            await self.status_server.start(
                0, bytes.fromhex(self.env.coin.GENESIS_HASH)[::-1], self.env.country,
                self.env.host, self.env.udp_port, self.env.allow_lan_udp
            )
        await _start_cancellable(self.receive_es_notifications)
        await _start_cancellable(self.refresh_blocks_forever)
        await self.session_manager.search_index.start()
        await _start_cancellable(self.session_manager.serve, self.mempool)

    async def stop(self):
        self.status_server.stop()
        async with self._lock:
            for task in reversed(self.cancellable_tasks):
                task.cancel()
            await asyncio.wait(self.cancellable_tasks)
        self.session_manager.search_index.stop()
        self.db.close()
        if self.prometheus_server:
            await self.prometheus_server.stop()
            self.prometheus_server = None
        await self.daemon.close()
        self._executor.shutdown(wait=True)
        self.shutdown_event.set()

    def run(self):
        loop = asyncio.get_event_loop()

        def __exit():
            raise SystemExit()
        try:
            loop.add_signal_handler(signal.SIGINT, __exit)
            loop.add_signal_handler(signal.SIGTERM, __exit)
            loop.run_until_complete(self.start())
            loop.run_until_complete(self.shutdown_event.wait())
        except (SystemExit, KeyboardInterrupt):
            pass
        finally:
            loop.run_until_complete(self.stop())

    async def start_prometheus(self):
        if not self.prometheus_server and self.env.prometheus_port:
            self.prometheus_server = PrometheusServer()
            await self.prometheus_server.start("0.0.0.0", self.env.prometheus_port)
