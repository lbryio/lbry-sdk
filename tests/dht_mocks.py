import typing
import contextlib
import socket
from unittest import mock
import functools
import asyncio
if typing.TYPE_CHECKING:
    from lbry.dht.protocol.protocol import KademliaProtocol


def get_time_accelerator(loop: asyncio.AbstractEventLoop,
                         instant_step: bool = False) -> typing.Callable[[float], typing.Awaitable[None]]:
    """
    Returns an async advance() function

    This provides a way to advance() the BaseEventLoop.time for the scheduled TimerHandles
    made by call_later, call_at, and call_soon.
    """

    original = loop.time
    _drift = 0
    loop.time = functools.wraps(loop.time)(lambda: original() + _drift)

    async def accelerate_time(seconds: float) -> None:
        nonlocal _drift
        if seconds < 0:
            raise ValueError(f'Cannot go back in time ({seconds} seconds)')
        _drift += seconds
        await asyncio.sleep(0)

    async def accelerator(seconds: float):
        steps = seconds * 10.0 if not instant_step else 1

        for _ in range(max(int(steps), 1)):
            await accelerate_time(seconds/steps)

    return accelerator


@contextlib.contextmanager
def mock_network_loop(loop: asyncio.AbstractEventLoop,
                      dht_network: typing.Optional[typing.Dict[typing.Tuple[str, int], 'KademliaProtocol']] = None):
    dht_network: typing.Dict[typing.Tuple[str, int], 'KademliaProtocol'] = dht_network if dht_network is not None else {}

    async def create_datagram_endpoint(proto_lam: typing.Callable[[], 'KademliaProtocol'],
                                       from_addr: typing.Tuple[str, int]):
        def sendto(data, to_addr):
            rx = dht_network.get(to_addr)
            if rx and rx.external_ip:
                # print(f"{from_addr[0]}:{from_addr[1]} -{len(data)} bytes-> {rx.external_ip}:{rx.udp_port}")
                return rx.datagram_received(data, from_addr)

        protocol = proto_lam()
        transport = asyncio.DatagramTransport(extra={'socket': mock_sock})
        transport.is_closing = lambda: False
        transport.close = lambda: mock_sock.close()
        mock_sock.sendto = sendto
        transport.sendto = mock_sock.sendto
        protocol.connection_made(transport)
        dht_network[from_addr] = protocol
        return transport, protocol

    with mock.patch('socket.socket') as mock_socket:
        mock_sock = mock.Mock(spec=socket.socket)
        mock_sock.setsockopt = lambda *_: None
        mock_sock.bind = lambda *_: None
        mock_sock.setblocking = lambda *_: None
        mock_sock.getsockname = lambda: "0.0.0.0"
        mock_sock.getpeername = lambda: ""
        mock_sock.close = lambda: None
        mock_sock.type = socket.SOCK_DGRAM
        mock_sock.fileno = lambda: 7
        mock_socket.return_value = mock_sock
        loop.create_datagram_endpoint = create_datagram_endpoint
        yield
