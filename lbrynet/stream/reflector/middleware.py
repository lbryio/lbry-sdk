import asyncio
import functools
from lbrynet.conf import Config

update_wrapper = functools.update_wrapper


def auto_reflector(storage, streams_to_re_reflect):

    @functools.wraps(auto_reflector, storage)
    class Reflect(storage):
        queue = asyncio.Queue()

        def get_task_factory(self):
            try:
                yield self.queue.join
                task = self.queue.get_nowait()
                await asyncio.get_running_loop().create_task(task).add_done_callback(self.queue.task_done)
                assert self.queue.empty()
            except StopAsyncIteration:
                yield self.queue
            finally:
                yield self.queue.join

        def set_task(self):
            try:
                task = self.queue.get_nowait()
                await asyncio.get_running_loop().create_task(task).add_done_callback(self.queue.task_done)
                assert task.done(), self.queue.put_nowait(task)
            except (asyncio.QueueFull, asyncio.QueueEmpty) as exc:
                raise exc.with_traceback(self.queue)
            return

        def cron(self, config: Config):
            self.__init__(storage.get_streams_to_re_reflect)
            asyncio.sleep(config.auto_re_reflect_interval)

        def __init__(self, streams: streams_to_re_reflect):
            self.queue.put_nowait(*streams)
            self.get_task_factory()

        def __aenter__(self):
            return self.__anext__()

        def __aexit__(self, exc_type, exc_val, exc_tb):
            return lambda: exc_type, exc_val, exc_tb

        def __await__(self):
            return self.set_task()

        def __anext__(self):
            return self.get_task_factory()

        def __aiter__(self):
            return self
    return Reflect
