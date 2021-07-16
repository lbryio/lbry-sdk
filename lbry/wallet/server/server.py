import signal
import logging
import asyncio
from concurrent.futures.thread import ThreadPoolExecutor
import typing

import lbry
from lbry.wallet.server.mempool import MemPool
from lbry.wallet.server.block_processor import BlockProcessor
from lbry.wallet.server.leveldb import LevelDB
from lbry.wallet.server.session import LBRYSessionManager
from lbry.prometheus import PrometheusServer


class Server:

    def __init__(self, env):
        self.env = env
        self.log = logging.getLogger(__name__).getChild(self.__class__.__name__)
        self.shutdown_event = asyncio.Event()
        self.cancellable_tasks = []

        self.daemon = daemon = env.coin.DAEMON(env.coin, env.daemon_url)
        self.db = db = LevelDB(env)
        self.mempool = mempool = MemPool(env.coin, daemon, db)
        self.bp = bp = BlockProcessor(env, db, daemon, mempool, self.shutdown_event)
        self.prometheus_server: typing.Optional[PrometheusServer] = None

        self.session_mgr = LBRYSessionManager(
            env, db, bp, daemon, mempool, self.shutdown_event
        )
        self._indexer_task = None

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

        await self.start_prometheus()
        if self.env.udp_port:
            await self.bp.status_server.start(
                0, bytes.fromhex(self.bp.coin.GENESIS_HASH)[::-1], self.env.country,
                self.env.host, self.env.udp_port, self.env.allow_lan_udp
            )
        await _start_cancellable(self.bp.fetch_and_process_blocks)

        await self.db.populate_header_merkle_cache()
        await _start_cancellable(self.mempool.keep_synchronized)
        await _start_cancellable(self.session_mgr.serve, self.mempool)

    async def stop(self):
        for task in reversed(self.cancellable_tasks):
            task.cancel()
        await asyncio.wait(self.cancellable_tasks)
        if self.prometheus_server:
            await self.prometheus_server.stop()
            self.prometheus_server = None
        self.shutdown_event.set()
        await self.daemon.close()

    def run(self):
        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(1)
        loop.set_default_executor(executor)

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
            executor.shutdown(True)

    async def start_prometheus(self):
        if not self.prometheus_server and self.env.prometheus_port:
            self.prometheus_server = PrometheusServer()
            await self.prometheus_server.start("0.0.0.0", self.env.prometheus_port)
