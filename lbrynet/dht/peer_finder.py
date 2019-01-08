import asyncio
import typing
import logging
import binascii
from types import AsyncGeneratorType
from lbrynet.stream.descriptor import StreamDescriptor

if typing.TYPE_CHECKING:
    from lbrynet.peer import Peer
    from lbrynet.blob.blob_manager import BlobFileManager
    from lbrynet.dht.node import Node

log = logging.getLogger(__name__)


def cancel_task(task: typing.Optional[asyncio.Task]):
    if task and not (task.done() or task.cancelled()):
        task.cancel()


def cancel_tasks(tasks: typing.List[typing.Optional[asyncio.Task]]):
    for task in tasks:
        cancel_task(task)


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
        self.queue = queue or asyncio.Queue(loop=loop)
        self.tasks: typing.List[asyncio.Task] = []
        self.running_iterators: typing.Dict[typing.AsyncGenerator, bool] = {}
        self.awaiting: asyncio.Future = None

    @property
    def running(self):
        return any(self.running_iterators.values())

    def add_generator(self, async_gen: typing.Union[typing.AsyncGenerator, AsyncGeneratorType]):
        """
        Add an async generator. This can be called during an iteration of the generator junction.
        """

        async def iterate(iterator: typing.AsyncGenerator):
            async for item in iterator:
                self.queue.put_nowait(item)

            self.running_iterators[iterator] = False

        self.running_iterators[async_gen] = True
        self.tasks.append(self.loop.create_task(iterate(async_gen)))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.running:
            await self.aclose()
            raise StopAsyncIteration()
        self.awaiting = asyncio.ensure_future(self.queue.get(), loop=self.loop)
        try:
            return await self.awaiting
        finally:
            self.awaiting = None

    def aclose(self):
        async def _aclose():
            for iterator in list(self.running_iterators.keys()):
                result = iterator.aclose()
                if asyncio.iscoroutine(result):
                    await result
                self.running_iterators[iterator] = False
            drain_tasks(self.tasks)
            if self.awaiting and not self.awaiting.done():
                self.awaiting.cancel()
            self.awaiting = None
        return asyncio.ensure_future(_aclose(), loop=self.loop)


class StreamPeerFinder:
    def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: 'BlobFileManager', node: 'Node', sd_hash: str,
                 peer_timeout: typing.Optional[float] = 30.0, peer_connect_timeout: typing.Optional[float] = 3.0):
        self.loop = loop
        self.blob_manager = blob_manager
        self.sd_hash = sd_hash
        self.sd_blob = self.blob_manager.get_blob(self.sd_hash)
        self.node = node
        self.peer_timeout = peer_timeout
        self.peer_connect_timeout = peer_connect_timeout
        self.peers: asyncio.Queue['Peer'] = asyncio.Queue(loop=self.loop)
        self.attempted: typing.Set['Peer'] = set()
        self.find_task: asyncio.Task = None
        self.wait_head_blob_task: asyncio.Task = None
        self.finished = asyncio.Event(loop=self.loop)
        self.peer_generator: AsyncGeneratorJunction = None
        self.task: asyncio.Task = None

    async def _find_peers(self):
        self.peer_generator = AsyncGeneratorJunction(self.loop)
        # find peers for the sd blob
        self.peer_generator.add_generator(
            self.node.get_iterative_value_finder(binascii.unhexlify(self.sd_hash.encode()), bottom_out_limit=20,
                                                 max_results=-1)
        )

        async def got_head_blob_info():
            await self.sd_blob.verified.wait()
            log.info("add head blob peer finder")
            # the sd blob has been downloaded, now find peers for the head blob
            sd = await StreamDescriptor.from_stream_descriptor_blob(
                self.loop, self.blob_manager, self.sd_blob
            )
            self.peer_generator.add_generator(
                self.node.get_iterative_value_finder(binascii.unhexlify(sd.blobs[0].blob_hash.encode()),
                                                     bottom_out_limit=20, max_results=-1)
            )

        # the head blob is already known, find peers for it
        if self.sd_blob.get_is_verified():
            descriptor = await StreamDescriptor.from_stream_descriptor_blob(
                self.loop, self.blob_manager, self.sd_blob
            )
            log.info("had sd blob, add head blob finder")
            self.peer_generator.add_generator(
                self.node.get_iterative_value_finder(binascii.unhexlify(descriptor.blobs[0].blob_hash.encode()),
                                                     bottom_out_limit=20, max_results=-1)
            )
        else:
            self.wait_head_blob_task = self.loop.create_task(got_head_blob_info())

        async for peers in self.peer_generator:
            if not peers or not isinstance(peers, list):
                break
            for peer in peers:
                if peer not in self.attempted:
                    if not peer.tcp_last_down or (peer.tcp_last_down + 300) < self.loop.time():
                        self.attempted.add(peer)
                        self.peers.put_nowait(peer)
        log.info("peer finder exhausted")

        self.finished.set()

    def __aiter__(self):
        self.find_task = self.loop.create_task(self._find_peers())
        return self

    async def __anext__(self):
        finished = self.loop.create_task(self.finished.wait())
        peer = self.loop.create_task(self.peers.get())

        self.task = self.loop.create_task(asyncio.wait([finished, peer], return_when='FIRST_COMPLETED'))
        try:
            await self.task
            return peer.result()
        except asyncio.CancelledError:
            raise StopAsyncIteration()
        finally:
            if not finished.done() and not finished.cancelled():
                finished.cancel()
            if not peer.done() and not peer.cancelled():
                peer.cancel()
            self.task = None

    def aclose(self):
        async def _aclose():
            if self.peer_generator:
                await self.peer_generator.aclose()
            cancel_tasks([self.find_task, self.wait_head_blob_task, self.task])

        return asyncio.ensure_future(_aclose(), loop=self.loop)
