import asyncio
import logging
import typing

from lbrynet.peer import PeerManager, Peer
from lbrynet.dht import constants

log = logging.getLogger(__name__)


class PingQueue:
    def __init__(self, peer_manager: PeerManager, loop: asyncio.BaseEventLoop):
        self._peer_manager = peer_manager
        self._loop = loop
        self._enqueued_contacts: typing.List[Peer] = []
        self._pending_contacts: typing.Dict[Peer, float] = {}
        self._process_task: asyncio.Task = None
        self._next_task: asyncio.Future = None
        self._next_timer: asyncio.TimerHandle = None
        self._lock = asyncio.Lock()
        self._running = False

    @property
    def running(self):
        return self._running

    async def enqueue_maybe_ping(self, *peers: Peer, delay: typing.Optional[float] = None):
        delay = constants.check_refresh_interval if delay is None else delay
        async with self._lock:
            for peer in peers:
                if delay and peer not in self._enqueued_contacts:
                    self._pending_contacts[peer] = self._loop.time() + delay
                elif peer not in self._enqueued_contacts:
                    self._enqueued_contacts.append(peer)
                    if peer in self._pending_contacts:
                        del self._pending_contacts[peer]

    async def _process(self):
        async def _ping(p: Peer):
            try:
                if p.contact_is_good:
                    return
                await p.ping()
            except TimeoutError:
                pass

        if self._enqueued_contacts or self._pending_contacts:
            # async with self._lock:
            now = self._loop.time()
            scheduled = [k for k, d in self._pending_contacts.items() if now >= d]
            for k in scheduled:
                del self._pending_contacts[k]
                if k not in self._enqueued_contacts:
                    self._enqueued_contacts.append(k)
            while self._enqueued_contacts:
                peer = self._enqueued_contacts.pop()
                delay = 1.0 / float(len(self._enqueued_contacts))
                self._loop.create_task(self._loop.call_later(delay, _ping, peer))

        if not self._next_timer and not self._next_task and self._running:
            self._next_timer = self._loop.call_later(300, self._schedule_next)

    def _schedule_next(self):
        self._next_task = self._loop.create_task(self._process())

    def start(self):
        assert not self._running
        self._running = True
        if not self._process_task:
            self._process_task = self._loop.create_task(self._process())

    def stop(self):
        assert self._running
        self._running = False
        if self._process_task:
            self._process_task.cancel()
            self._process_task = None
        if self._next_task:
            self._next_task.cancel()
            self._next_task = None
        if self._next_timer:
            self._next_timer.cancel()
            self._next_timer = None
