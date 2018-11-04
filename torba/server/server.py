import signal
import logging
import asyncio

import torba
from torba.server.mempool import MemPool, MemPoolAPI
from torba.server.session import SessionManager


class Notifications:
    # hashX notifications come from two sources: new blocks and
    # mempool refreshes.
    #
    # A user with a pending transaction is notified after the block it
    # gets in is processed.  Block processing can take an extended
    # time, and the prefetcher might poll the daemon after the mempool
    # code in any case.  In such cases the transaction will not be in
    # the mempool after the mempool refresh.  We want to avoid
    # notifying clients twice - for the mempool refresh and when the
    # block is done.  This object handles that logic by deferring
    # notifications appropriately.

    def __init__(self):
        self._touched_mp = {}
        self._touched_bp = {}
        self._highest_block = -1

    async def _maybe_notify(self):
        tmp, tbp = self._touched_mp, self._touched_bp
        common = set(tmp).intersection(tbp)
        if common:
            height = max(common)
        elif tmp and max(tmp) == self._highest_block:
            height = self._highest_block
        else:
            # Either we are processing a block and waiting for it to
            # come in, or we have not yet had a mempool update for the
            # new block height
            return
        touched = tmp.pop(height)
        for old in [h for h in tmp if h <= height]:
            del tmp[old]
        for old in [h for h in tbp if h <= height]:
            touched.update(tbp.pop(old))
        await self.notify(height, touched)

    async def notify(self, height, touched):
        pass

    async def start(self, height, notify_func):
        self._highest_block = height
        self.notify = notify_func
        await self.notify(height, set())

    async def on_mempool(self, touched, height):
        self._touched_mp[height] = touched
        await self._maybe_notify()

    async def on_block(self, touched, height):
        self._touched_bp[height] = touched
        self._highest_block = height
        await self._maybe_notify()


class Server:

    def __init__(self, env):
        self.env = env
        self.log = logging.getLogger(__name__).getChild(self.__class__.__name__)
        self.shutdown_event = asyncio.Event()
        self.cancellable_tasks = []

        self.notifications = notifications = Notifications()
        self.daemon = daemon = env.coin.DAEMON(env.coin, env.daemon_url)
        self.db = db = env.coin.DB(env)
        self.bp = bp = env.coin.BLOCK_PROCESSOR(env, db, daemon, notifications)

        # Set notifications up to implement the MemPoolAPI
        notifications.height = daemon.height
        notifications.cached_height = daemon.cached_height
        notifications.mempool_hashes = daemon.mempool_hashes
        notifications.raw_transactions = daemon.getrawtransactions
        notifications.lookup_utxos = db.lookup_utxos
        MemPoolAPI.register(Notifications)
        self.mempool = mempool = MemPool(env.coin, notifications)

        self.session_mgr = SessionManager(
            env, db, bp, daemon, mempool, self.shutdown_event
        )

    async def start(self):
        env = self.env
        min_str, max_str = env.coin.SESSIONCLS.protocol_min_max_strings()
        self.log.info(f'software version: {torba.__version__}')
        self.log.info(f'supported protocol versions: {min_str}-{max_str}')
        self.log.info(f'event loop policy: {env.loop_policy}')
        self.log.info(f'reorg limit is {env.reorg_limit:,d} blocks')

        await self.daemon.height()

        def _start_cancellable(run, *args):
            _flag = asyncio.Event()
            self.cancellable_tasks.append(asyncio.ensure_future(run(*args, _flag)))
            return _flag.wait()

        await _start_cancellable(self.bp.fetch_and_process_blocks)
        await self.db.populate_header_merkle_cache()
        await _start_cancellable(self.mempool.keep_synchronized)
        await _start_cancellable(self.session_mgr.serve, self.notifications)

    def stop(self):
        for task in reversed(self.cancellable_tasks):
            task.cancel()

    def run(self):
        loop = asyncio.get_event_loop()
        try:
            loop.add_signal_handler(signal.SIGINT, self.stop)
            loop.add_signal_handler(signal.SIGTERM, self.stop)
            loop.run_until_complete(self.start())
            loop.run_forever()
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
