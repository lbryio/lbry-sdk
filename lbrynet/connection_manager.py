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
        self._status = {}

        self._task: typing.Optional[asyncio.Task] = None

    @property
    def status(self):
        return self._status

    def sent_data(self, host_and_port: str, size: int):
        self.outgoing[host_and_port] += size

    def received_data(self, host_and_port: str, size: int):
        self.incoming[host_and_port] += size

    def connection_made(self, host_and_port: str):
        self.outgoing_connected.add(host_and_port)

    def connection_received(self, host_and_port: str):
        # self.incoming_connected.add(host_and_port)
        pass

    def outgoing_connection_lost(self, host_and_port: str):
        if host_and_port in self.outgoing_connected:
            self.outgoing_connected.remove(host_and_port)

    def incoming_connection_lost(self, host_and_port: str):
        if host_and_port in self.incoming_connected:
            self.incoming_connected.remove(host_and_port)

    async def _update(self):

        self._status = {
            'incoming_bps': {},
            'outgoing_bps': {},
            'total_incoming_mbps': 0.0,
            'total_outgoing_mbps': 0.0,
        }

        while True:
            last = self.loop.time()
            await asyncio.sleep(1, loop=self.loop)
            self._status['incoming_bps'].clear()
            self._status['outgoing_bps'].clear()
            while self.outgoing:
                k, v = self.outgoing.popitem()
                self._status['outgoing_bps'][k] = v
            while self.incoming:
                k, v = self.incoming.popitem()
                self._status['incoming_bps'][k] = v
            now = self.loop.time()
            self._status['total_outgoing_mbps'] = int(sum(list(self._status['outgoing_bps'].values()))
                                                      / (now - last)) / 1000000.0
            self._status['total_incoming_mbps'] = int(sum(list(self._status['incoming_bps'].values()))
                                                      / (now - last)) / 1000000.0
            self._status['time'] = now

    def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None
        self.outgoing.clear()
        self.outgoing_connected.clear()
        self.incoming.clear()
        self.incoming_connected.clear()
        self._status.clear()

    def start(self):
        self.stop()
        self._task = self.loop.create_task(self._update())
