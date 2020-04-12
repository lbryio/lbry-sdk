import os
import asyncio
import logging
from threading import Thread
from multiprocessing import Queue, Event
from concurrent import futures

from lbry.wallet.stream import StreamController, EventQueuePublisher
from lbry.db import Database

from .lbrycrd import Lbrycrd
from . import worker


log = logging.getLogger(__name__)


class ProgressMonitorThread(Thread):

    STOP = 'stop'
    FORMAT = '{l_bar}{bar}| {n_fmt:>6}/{total_fmt:>7} [{elapsed}<{remaining:>5}, {rate_fmt:>15}]'

    def __init__(self, state: dict, queue: Queue, stream_controller: StreamController):
        super().__init__()
        self.state = state
        self.queue = queue
        self.stream_controller = stream_controller
        self.loop = asyncio.get_event_loop()

    def run(self):
        asyncio.set_event_loop(self.loop)
        while True:
            msg = self.queue.get()
            if msg == self.STOP:
                return
            self.stream_controller.add(msg)

    def shutdown(self):
        self.queue.put(self.STOP)
        self.join()

    def __enter__(self):
        self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()


class BlockchainSync:

    def __init__(self, chain: Lbrycrd, db: Database, use_process_pool=False):
        self.chain = chain
        self.db = db
        self.use_process_pool = use_process_pool
        self._on_progress_controller = StreamController()
        self.on_progress = self._on_progress_controller.stream

    def get_worker_pool(self, queue, full_stop) -> futures.Executor:
        args = dict(
            initializer=worker.initializer,
            initargs=(self.chain.data_dir, self.chain.regtest, self.db.db_path, queue, full_stop)
        )
        if not self.use_process_pool:
            return futures.ThreadPoolExecutor(max_workers=1, **args)
        return futures.ProcessPoolExecutor(max_workers=max(os.cpu_count()-1, 4), **args)

    async def load_blocks(self):
        jobs = []
        queue, full_stop = Queue(), Event()
        executor = self.get_worker_pool(queue, full_stop)
        files = list(await self.chain.get_block_files_not_synced())
        state = {
            file.file_number: {
                'status': worker.PENDING,
                'done_txs': 0,
                'total_txs': file.txs,
                'done_blocks': 0,
                'total_blocks': file.blocks,
            } for file in files
        }
        progress = EventQueuePublisher(queue, self._on_progress_controller)
        progress.start()

        def cancel_all_the_things():
            for job in jobs:
                job.cancel()
            full_stop.set()
            for job in jobs:
                exception = job.exception()
                if exception is not None:
                    log.exception(exception)
                    raise exception

        try:

            for file in files:
                jobs.append(executor.submit(worker.process_block_file, file.file_number))

            done, not_done = await asyncio.get_event_loop().run_in_executor(
                None, futures.wait, jobs, None, futures.FIRST_EXCEPTION
            )
            if not_done:
                cancel_all_the_things()

        except asyncio.CancelledError:
            cancel_all_the_things()
            raise

        finally:
            progress.stop()
            executor.shutdown()
