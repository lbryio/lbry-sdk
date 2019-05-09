import asyncio
import typing
import logging
import traceback
if typing.TYPE_CHECKING:
    from types import AsyncGeneratorType

log = logging.getLogger(__name__)


def cancel_task(task: typing.Optional[asyncio.Task]):
    if task and not (task.done() or task.cancelled()):
        task.cancel()


def drain_tasks(tasks: typing.List[typing.Optional[asyncio.Task]]):
    while tasks:
        cancel_task(tasks.pop())


class AsyncGeneratorJunction:
    """
    A helper to interleave the results from multiple async generators into one
    async generator.
    """

    def __init__(self, loop: asyncio.BaseEventLoop, queue: typing.Optional[asyncio.Queue] = None):
        self.loop = loop
        self.__iterator_queue = asyncio.Queue(loop=loop)
        self.result_queue = queue or asyncio.Queue(loop=loop)
        self.tasks: typing.List[asyncio.Task] = []
        self.running_iterators: typing.Dict[typing.AsyncGenerator, bool] = {}
        self.generator_queue: asyncio.Queue = asyncio.Queue(loop=self.loop)

    @property
    def running(self):
        return any(self.running_iterators.values())

    async def wait_for_generators(self):
        async def iterate(iterator: typing.AsyncGenerator):
            try:
                async for item in iterator:
                    self.result_queue.put_nowait(item)
                    self.__iterator_queue.put_nowait(item)
            finally:
                self.running_iterators[iterator] = False
                if not self.running:
                    self.__iterator_queue.put_nowait(StopAsyncIteration)

        while True:
            async_gen: typing.Union[typing.AsyncGenerator, 'AsyncGeneratorType'] = await self.generator_queue.get()
            self.running_iterators[async_gen] = True
            self.tasks.append(self.loop.create_task(iterate(async_gen)))

    def add_generator(self, async_gen: typing.Union[typing.AsyncGenerator, 'AsyncGeneratorType']):
        """
        Add an async generator. This can be called during an iteration of the generator junction.
        """
        self.generator_queue.put_nowait(async_gen)

    def __aiter__(self):
        return self

    async def __anext__(self):
        result = await self.__iterator_queue.get()
        if result is StopAsyncIteration:
            raise result
        return result

    def aclose(self):
        async def _aclose():
            for iterator in list(self.running_iterators.keys()):
                result = iterator.aclose()
                if asyncio.iscoroutine(result):
                    await result
                self.running_iterators[iterator] = False
            drain_tasks(self.tasks)
            raise StopAsyncIteration()
        return self.loop.create_task(_aclose())

    async def __aenter__(self):
        self.tasks.append(self.loop.create_task(self.wait_for_generators()))
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            await self.aclose()
        except StopAsyncIteration:
            pass
        finally:
            if exc_type:
                if exc_type not in (asyncio.CancelledError, asyncio.TimeoutError, StopAsyncIteration, GeneratorExit):
                    err = traceback.format_exception(exc_type, exc, tb)
                    log.error(err)
