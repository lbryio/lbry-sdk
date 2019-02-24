import asyncio
import json
import typing

if typing.TYPE_CHECKING:
    from typing import Optional
    from asyncio import transports


path = r'\\.\pipe\lbrypipe'

class WindowsPipeProtocol(asyncio.Protocol):
    def __init__(self):
        self.transport = None
        self.closed = asyncio.Event()

    def connection_made(self, transport: 'transports.BaseTransport'):
        self.transport = transport
        message = {'method': 'account_balance', 'params': {}}
        message = json.dumps(message)
        self.transport.write(message.encode())

    def connection_lost(self, exc: 'Optional[Exception]'):
        self.closed.set()

    def data_received(self, data: bytes):
        print(data.decode())
        self.transport.close()
        self.closed.set()

    def eof_received(self):
        pass


def windows_pipe_factory():
    return WindowsPipeProtocol

async def main():
    loop = asyncio.get_event_loop()
    transport, protocol = await loop.create_pipe_connection(windows_pipe_factory(), path)
    await protocol.closed.wait()


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.ProactorEventLoop())
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
