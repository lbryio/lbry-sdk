import asyncio
import typing
import logging
import binascii
from lbrynet.blob.blob_manager import BlobFileManager
from lbrynet.stream.descriptor import StreamDescriptor
from lbrynet.dht.node import Node
if typing.TYPE_CHECKING:
    from lbrynet.peer import Peer

log = logging.getLogger(__name__)


class AsyncGeneratorJunction:
    """
    A helper to interleave the results from multiple async generators into one
    async generator.
    """

    def __init__(self, loop: asyncio.BaseEventLoop, queue: typing.Optional[asyncio.Queue] = None):
        self.loop = loop
        self.queue = queue or asyncio.Queue(loop=loop)
        self.handles: typing.List[asyncio.TimerHandle] = []
        self.running_iterators: typing.Dict[typing.AsyncGenerator, bool] = {}

    @property
    def running(self):
        return any(self.running_iterators.values())

    def add_generator(self, async_gen: typing.AsyncGenerator):
        """
        Add an async generator. This can be called during an iteration of the generator junction.
        """

        async def iterate(iterator: typing.AsyncGenerator):
            async for item in iterator:
                self.queue.put_nowait(item)
            self.running_iterators[iterator] = False

        self.running_iterators[async_gen] = True
        self.handles.append(self.loop.call_soon(lambda : self.loop.create_task(iterate(async_gen))))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.running:
            return await self.queue.get()
        else:
            raise StopAsyncIteration()


class StreamPeerFinder:
    def __init__(self, loop: asyncio.BaseEventLoop, blob_manager: BlobFileManager, node: Node, sd_hash: str,
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
        self.finished = asyncio.Event(loop=self.loop)

    async def _find_peers(self):
        peer_generator = AsyncGeneratorJunction(self.loop)
        # find peers for the sd blob
        peer_generator.add_generator(
            self.node.get_iterative_value_finder(binascii.unhexlify(self.sd_hash.encode()), bottom_out_limit=5,
                                                 max_results=-1)
        )

        async def got_head_blob_info():
            await self.sd_blob.verified.wait()
            log.info("add head blob peer finder")
            # the sd blob has been downloaded, now find peers for the head blob
            sd = await StreamDescriptor.from_stream_descriptor_blob(
                self.loop, self.blob_manager, self.sd_blob
            )
            peer_generator.add_generator(
                self.node.get_iterative_value_finder(binascii.unhexlify(sd.blobs[0].blob_hash.encode()),
                                                     bottom_out_limit=5, max_results=-1)
            )

        # the head blob is already known, find peers for it
        if self.sd_blob.get_is_verified():
            descriptor = await StreamDescriptor.from_stream_descriptor_blob(
                self.loop, self.blob_manager, self.sd_blob
            )
            log.info("had sd blob, add head blob finder")
            peer_generator.add_generator(
                self.node.get_iterative_value_finder(binascii.unhexlify(descriptor.blobs[0].blob_hash.encode()),
                                                     bottom_out_limit=5, max_results=-1)
            )
        else:
            self.loop.create_task(got_head_blob_info())

        async for peers in peer_generator:
            assert isinstance(peers, list)
            for peer in peers:
                if peer not in self.attempted:
                    if not peer.tcp_last_down or (peer.tcp_last_down + 300) < self.loop.time():
                        log.info("download stream from %s:%i", peer.address, peer.tcp_port)
                        self.attempted.add(peer)
                        self.peers.put_nowait(peer)
        self.finished.set()

    def __aiter__(self):
        self.find_task = self.loop.create_task(self._find_peers())
        return self

    async def __anext__(self):
        if self.finished.is_set():
            self.stop()
            raise StopAsyncIteration()
        return await self.peers.get()

    def stop(self):
        if self.find_task and not (self.find_task.done() or self.find_task.cancelled()):
            self.find_task.cancel()

