import os
import asyncio
import logging
import tqdm
from threading import Thread
from multiprocessing import Queue, Event
from concurrent import futures
from typing import Dict, Tuple

from lbry.wallet.stream import StreamController

from .lbrycrd import Lbrycrd
from .db import AsyncBlockchainDB
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
        block_bar = tqdm.tqdm(
            desc='total parsing', total=sum(s['total_blocks'] for s in self.state.values()),
            unit='blocks', bar_format=self.FORMAT
        )
        tx_bar = tqdm.tqdm(
            desc='total loading', total=sum(s['total_txs'] for s in self.state.values()),
            unit='txs', bar_format=self.FORMAT
        )
        bars: Dict[int, tqdm.tqdm] = {}
        while True:
            msg = self.queue.get()
            if msg == self.STOP:
                return
            file_num, msg_type, done = msg
            bar, state = bars.get(file_num, None), self.state[file_num]
            if msg_type == 1:
                if bar is None:
                    bar = bars[file_num] = tqdm.tqdm(
                        desc=f'├─ blk{file_num:05}.dat parsing', total=state['total_blocks'],
                        unit='blocks', bar_format=self.FORMAT
                    )
                change = done - state['done_blocks']
                state['done_blocks'] = done
                bar.update(change)
                block_bar.update(change)
                if state['total_blocks'] == done:
                    bar.set_description('✔  '+bar.desc[3:])
                    bar.close()
                    bars.pop(file_num)
            elif msg_type == 2:
                if bar is None:
                    bar = bars[file_num] = tqdm.tqdm(
                        desc=f'├─ blk{file_num:05}.dat loading', total=state['total_txs'],
                        unit='txs', bar_format=self.FORMAT
                    )
                change = done - state['done_txs']
                state['done_txs'] = done
                bar.update(change)
                tx_bar.update(change)
                if state['total_txs'] == done:
                    bar.set_description('✔  '+bar.desc[3:])
                    bar.close()
                    bars.pop(file_num)
            self.stream_controller.add(msg)

    def shutdown(self):
        self.queue.put(self.STOP)
        self.join()

    def __enter__(self):
        self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()


class BlockSync:

    def __init__(self, chain: Lbrycrd, use_process_pool=False):
        self.chain = chain
        self.use_process_pool = use_process_pool
        self.db = AsyncBlockchainDB.from_path(self.chain.actual_data_dir)
        self._on_progress_controller = StreamController()
        self.on_progress = self._on_progress_controller.stream

    async def start(self):
        await self.db.open()

    async def stop(self):
        await self.db.close()

    def get_worker_pool(self, queue, full_stop) -> futures.Executor:
        args = dict(
            initializer=worker.initializer,
            initargs=(self.chain.actual_data_dir, queue, full_stop)
        )
        if not self.use_process_pool:
            return futures.ThreadPoolExecutor(max_workers=1, **args)
        return futures.ProcessPoolExecutor(max_workers=max(os.cpu_count()-1, 4), **args)

    def get_progress_monitor(self, state, queue) -> ProgressMonitorThread:
        return ProgressMonitorThread(state, queue, self._on_progress_controller)

    async def load_blocks(self):
        jobs = []
        queue, full_stop = Queue(), Event()
        executor = self.get_worker_pool(queue, full_stop)
        files = list(await self.db.get_block_files_not_synced())
        state = {
            file.file_number: {
                'status': worker.PENDING,
                'done_txs': 0,
                'total_txs': file.txs,
                'done_blocks': 0,
                'total_blocks': file.blocks,
            } for file in files
        }
        progress = self.get_progress_monitor(state, queue)
        progress.start()

        def cancel_all_the_things():
            for job in jobs:
                job.cancel()
            full_stop.set()
            for job in jobs:
                exception = job.exception()
                if exception is not None:
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
            progress.shutdown()
            executor.shutdown()
