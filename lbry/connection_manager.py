import time
import asyncio
import typing
import collections
import logging

log = logging.getLogger(__name__)


CONNECTED_EVENT = "connected"
DISCONNECTED_EVENT = "disconnected"
TRANSFERRED_EVENT = "transferred"


class ConnectionManager:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.incoming_connected: typing.Set[str] = set()
        self.incoming: typing.DefaultDict[str, int] = collections.defaultdict(int)
        self.outgoing_connected: typing.Set[str] = set()
        self.outgoing: typing.DefaultDict[str, int] = collections.defaultdict(int)
        self._max_incoming_mbs = 0.0
        self._max_outgoing_mbs = 0.0
        self._status = {}
        self._running = False
        self._task: typing.Optional[asyncio.Task] = None

    @property
    def status(self):
        return self._status

    def sent_data(self, host_and_port: str, size: int):
        if self._running:
            self.outgoing[host_and_port] += size

    def received_data(self, host_and_port: str, size: int):
        if self._running:
            self.incoming[host_and_port] += size

    def connection_made(self, host_and_port: str):
        if self._running:
            self.outgoing_connected.add(host_and_port)

    def connection_received(self, host_and_port: str):
        # self.incoming_connected.add(host_and_port)
        pass

    def outgoing_connection_lost(self, host_and_port: str):
        if self._running and host_and_port in self.outgoing_connected:
            self.outgoing_connected.remove(host_and_port)

    def incoming_connection_lost(self, host_and_port: str):
        if self._running and host_and_port in self.incoming_connected:
            self.incoming_connected.remove(host_and_port)

    async def _update(self):
        self._status = {
            'incoming_bps': {},
            'outgoing_bps': {},
            'total_incoming_mbs': 0.0,
            'total_outgoing_mbs': 0.0,
            'total_sent': 0,
            'total_received': 0,
            'max_incoming_mbs': 0.0,
            'max_outgoing_mbs': 0.0
        }

        while True:
            last = time.perf_counter()
            await asyncio.sleep(0.1)
            self._status['incoming_bps'].clear()
            self._status['outgoing_bps'].clear()
            now = time.perf_counter()
            while self.outgoing:
                k, sent = self.outgoing.popitem()
                self._status['total_sent'] += sent
                self._status['outgoing_bps'][k] = sent / (now - last)
            while self.incoming:
                k, received = self.incoming.popitem()
                self._status['total_received'] += received
                self._status['incoming_bps'][k] = received / (now - last)
            self._status['total_outgoing_mbs'] = int(sum(list(self._status['outgoing_bps'].values())
                                                         )) / 1000000.0
            self._status['total_incoming_mbs'] = int(sum(list(self._status['incoming_bps'].values())
                                                         )) / 1000000.0
            self._max_incoming_mbs = max(self._max_incoming_mbs, self._status['total_incoming_mbs'])
            self._max_outgoing_mbs = max(self._max_outgoing_mbs, self._status['total_outgoing_mbs'])
            self._status['max_incoming_mbs'] = self._max_incoming_mbs
            self._status['max_outgoing_mbs'] = self._max_outgoing_mbs

    def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None
        self.outgoing.clear()
        self.outgoing_connected.clear()
        self.incoming.clear()
        self.incoming_connected.clear()
        self._status.clear()
        self._running = False

    def start(self):
        self.stop()
        self._running = True
        self._task = self.loop.create_task(self._update())
