import struct
import typing
import asyncio
import logging


log = logging.getLogger(__name__)


class ElasticNotifierProtocol(asyncio.Protocol):
    """notifies the reader when ES has written updates"""

    def __init__(self, listeners):
        self._listeners = listeners
        self.transport: typing.Optional[asyncio.Transport] = None

    def connection_made(self, transport):
        self.transport = transport
        self._listeners.append(self)
        log.warning("got es notifier connection")

    def connection_lost(self, exc) -> None:
        self._listeners.remove(self)
        self.transport = None

    def send_height(self, height: int, block_hash: bytes):
        log.warning("notify es update '%s'", height)
        self.transport.write(struct.pack(b'>Q32s', height, block_hash) + b'\n')


class ElasticNotifierClientProtocol(asyncio.Protocol):
    """notifies the reader when ES has written updates"""

    def __init__(self, notifications: asyncio.Queue):
        self.notifications = notifications
        self.transport: typing.Optional[asyncio.Transport] = None

    def close(self):
        if self.transport and not self.transport.is_closing():
            self.transport.close()

    def connection_made(self, transport):
        self.transport = transport
        log.warning("connected to es notifier")

    def connection_lost(self, exc) -> None:
        self.transport = None

    def data_received(self, data: bytes) -> None:
        height, block_hash = struct.unpack(b'>Q32s', data.rstrip(b'\n'))
        self.notifications.put_nowait((height, block_hash))
